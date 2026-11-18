# Writing a proposal

A proposal is a request for change. It is a transaction over the **documents**
of a project, not over the compiled IR: the specification is the single source
of truth, so a change has to start there.

This guide is practical. Every target form shown here is covered by the test
suite.

---

## 1. The shape of a proposal

```yaml
sdl: "1.0"
kind: proposal

proposal:
  id: prop_guard_the_greeting     # unique name of the request
  target_version: "1.0.0"         # the version of the project it is based on
  author: "amir"                  # who asks for it
  rationale: "Only greet when a name was given."
  approve: true                   # optional; see section 5

  patches:
    - target: "flow.sdl.yaml:steps[greet].condition"
      action: add
      value: name != ""
```

The envelope is the one of specification section 8.2. The patch is the one of
section 8.3.

## 2. The target of a patch

A target says **which element** of the specification changes. Two forms are
accepted.

### By document kind

```
project.version
project.backend.target
project.bindings[Greeter]
project.bindings[Greeter].implementation
module.payment_helper.functions
```

The document is found by its kind, and by its identifier when it has one:
`module.<id>`, `interface.<id>`, `flow.<id>`, `implementation.<id>`.

### By file

```
types.sdl.yaml:Greeting.fields
interfaces.sdl.yaml:methods[greet].inputs
flow.sdl.yaml:steps[greet].call
flow.sdl.yaml:steps[greet].output_map
implementations.sdl.yaml:implements[0].version
```

The path is relative to the project root, and the pointer after the colon is
relative to the root object of the document — the value of the `kind` key.

### The segments of a path

| Segment | Means |
| :--- | :--- |
| `.name` | a key of a mapping |
| `[name]` | a key of a mapping, or the element of a list named `name` |
| `[3]` | the fourth element of a list |

An element of a list is named by its `id`, or, when it has none, by its
`name`, `interface` or `key`. That is why a binding is addressed as
`project.bindings[Greeter]`, and not by its position.

## 3. The three actions

| Action | Does | Fails when |
| :--- | :--- | :--- |
| `replace` | sets the value of an element that exists | the element does not exist |
| `add` | adds an element to a list, or a field to a mapping | the collection does not exist |
| `remove` | removes an element | the element does not exist |

The `value` is the new content. For `remove` it is not needed.

### What `add` means

The target of an `add` names the **collection that receives the value**, not
the position of the new value:

```yaml
# a new element at the end of the list of bindings
- target: "project.bindings"
  action: add
  value:
    interface: Farewell
    version: "1.0.0"
    implementation: farewell_impl

# a new field of the type
- target: "types.sdl.yaml:Greeting.fields"
  action: add
  value:
    language: String

# a new field of the step
- target: "flow.sdl.yaml:steps[greet].condition"
  action: add
  value: name != ""
```

An `add` on a target that already exists and is not a collection is refused:
use `replace` to change a value.

## 4. The workflow

### Step 1 — write it

Put it anywhere, for example `proposals/my_change.sdl.yaml`.

### Step 2 — run it

```powershell
python -m sdl propose proposals/my_change.sdl.yaml
```

You get one of three answers.

**Accepted, nothing merged:**

```
PROPOSAL ACCEPTED
The proposal is valid but has not been approved. Nothing was merged.
changed documents:
  flow.sdl.yaml
```

**Rejected, with the reason:**

```
PROPOSAL REJECTED
phase: semantic
The virtual specification violates the specification.
error ir SDL-E511 greet_someone::greet:1:1 Flow step 'greet' calls
  'Missing::Nothing', which does not exist.
```

**Rejected by the policy:**

```
PROPOSAL REJECTED
phase: policy
The proposal violates the policy of the project.
error proposal SDL-E602 prop_rename_the_greeting:1:1 The proposal removes the
  identifier Greeting from types.sdl.yaml. The policy forbids changing the
  identifiers of existing components.
```

### Step 3 — read the phase

The phase tells you where it failed, and the code tells you why.

| Phase | Means | Usual fix |
| :--- | :--- | :--- |
| `syntactic` | the proposal document itself is malformed | the schema message names the field |
| `referential` | a name the proposal uses does not exist | create it, or spell it as it is |
| `policy` | the project forbids this change | version the component, or do not change it |
| `semantic` | the virtual specification breaks a rule | the diagnostic names the rule |

A tool or an agent does not have to parse the text. `--json` prints one
machine readable object instead:

```powershell
python -m sdl propose proposals/my_change.sdl.yaml --json
```

```json
{
  "proposal": "prop_guard_the_greeting",
  "accepted": true,
  "merged": false,
  "phase": null,
  "message": "The proposal is valid but has not been approved. Nothing was merged.",
  "changed": ["flow.sdl.yaml"],
  "diagnostics": []
}
```

The process still exits non-zero when the proposal is rejected, so a script
can rely on the exit code and read the object for the detail.

### Step 4 — approve it

When it is accepted, add `approve: true` to the proposal and run it again.
Then the change is written into the documents and the project version is
incremented.

```yaml
proposal:
  id: prop_guard_the_greeting
  approve: true
```

An approval is a decision of an administrator, not of the agent. An agent
writes proposals; it does not approve them.

### Step 5 — rebuild and run

```powershell
python -m sdl build examples/hello/project.sdl.yaml --out generated/hello
python -m sdl run examples/hello/project.sdl.yaml --flow greet_someone --input name=Amir
```

## 5. The codes you will meet

| Code | Means |
| :--- | :--- |
| `SDL-E200` | the envelope is wrong, often the version |
| `SDL-E203` | a field the specification does not have |
| `SDL-E501` | a type of a flow does not match the type that is declared |
| `SDL-E502` | a flow reads a state variable that does not exist |
| `SDL-E504` | a condition is not a valid expression |
| `SDL-E511` | a reference does not resolve |
| `SDL-E601` | an architectural prohibition is broken |
| `SDL-E602` | the policy of the project forbids the change |
| `SDL-E603` | a binding does not resolve, or an interface a flow calls is not bound |
| `SDL-E604` | an implementation does not satisfy the interface |
| `SDL-E606` | the back end cannot host the language of an implementation |
| `SDL-E607` | the validator cannot read the signature of a Python implementation |
| `SDL-E701` | the target of a patch does not exist |
| `SDL-E702` | a proposal refers to something that does not exist |
| `SDL-E703` | the proposal is based on another version of the project |
| `SDL-E704` | two patches name the same element of the specification |
| `SDL-E705` | the merge of an approved proposal could not be written |

The full registry is in `sdl/diagnostics.py`.

## 6. Recipes

### Change a flow

```yaml
patches:
  - target: "flow.sdl.yaml:steps[greet].call"
    action: replace
    value: Greeter::greet

  - target: "flow.sdl.yaml:steps[greet].condition"
    action: add
    value: name != ""
```

### Replace the implementation of an interface

```yaml
patches:
  - target: "project.bindings[Greeter].implementation"
    action: replace
    value: greeter_impl_v2
```

The flow does not change: it calls the interface, and the binding decides
which implementation answers.

### Add a parameter to a method

A parameter that a method accepts is part of its contract, so it changes in
three places at once: the interface, the flow that calls it, and the code of
the implementation.

```yaml
patches:
  - target: "interfaces.sdl.yaml:methods[greet].inputs"
    action: replace
    value:
      name: String
      locale: String

  - target: "interfaces.sdl.yaml:version"
    action: replace
    value: "1.1.0"

  - target: "flow.sdl.yaml:inputs"
    action: replace
    value:
      name: String
      locale: String

  - target: "flow.sdl.yaml:steps[greet].mapping"
    action: replace
    value:
      name: name
      locale: locale
```

The implementation has to accept the parameter as well, and that is code, not
specification. Until `src/greeter.py` accepts it, the proposal is rejected:

```
error ir SDL-E604 The method 'greet' of the implementation 'greeter_impl'
  does not accept the parameter 'locale' the interface 'Greeter' declares.
```

Once the code accepts it, the proposal is accepted, and the project version
becomes **2.0.0**: a change of a signature breaks the contract, so it is a
MAJOR change.

### Add a field to a type

```yaml
patches:
  - target: "types.sdl.yaml:Greeting.fields"
    action: replace
    value:
      message: String
      language: String
```

A change of a type needs a migration plan for the documents that depend on
it, when the policy of the project requires one.

### Remove the binding of an interface

```yaml
patches:
  - target: "project.bindings[Greeter]"
    action: remove
```

This is refused: the flow calls the interface, and a call is resolved
through the bindings table (section 6.2).

```
PROPOSAL REJECTED
phase: semantic
error ir SDL-E603 The step 'greet' calls the interface 'Greeter', but the
  project binds no implementation for it.
```

## 7. What the engine does with a proposal

1. **syntactic** — the proposal document is validated against the schema of
   Core 1.0.
2. **referential** — every name the proposal introduces must exist in the
   specification, or be introduced by the same proposal.
3. **policy** — the prohibitions of the project are checked: the identifiers of
   the components may not change, and a signature may not change without a
   version increment.
4. **semantic** — the patches are applied to a **shadow copy** of the
   documents, and the whole pipeline runs on the copy: the schema, the
   semantics, the lowering, the resolution and the Semantic Firewall. The code
   of the implementations is copied as well, so the copy is checked against
   the contracts of section 5. A copy that breaks a rule is rejected.
5. **approval** — without `approve: true` nothing is written.
6. **merge** — the changed documents are written back and the project version
   is incremented: MAJOR when a contract breaks, MINOR when a component is
   added or removed or a component version changes, PATCH otherwise. A
   contract breaks when a signature changes, when a method disappears from an
   interface, or when an interface or a type disappears.

A breaking change also needs the **interface** itself to be incremented by a
major step (section 5.4). A patch version is not enough:

```yaml
- target: "interfaces.sdl.yaml:version"
  action: replace
  value: "1.0.1"     # refused: a breaking change needs 2.0.0
```

A rejected proposal changes nothing, byte for byte.
