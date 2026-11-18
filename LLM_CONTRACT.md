# SDL LLM Integration Contract (v1.0)

This document defines the strict boundaries and protocol for interactions between
an LLM (AI Agent) and the SDL Governance System.

The normative rules live in the specification:
[sections 4.3 and 8 of `spec/sdl-core-1.0.md`](spec/sdl-core-1.0.md). This
document is the short form an agent needs in order to act correctly.

## 1. The Principle of Least Privilege

The AI Agent is treated as an **untrusted proposer**. It has no direct access to
the production state of the system. It may only communicate via the `Proposal`
protocol.

## 2. Interface Boundaries

### A. READ Access (The Snapshot)

The AI Agent may receive a **Read-Only Snapshot** of the current IR.

- **Permitted**: access to the `SymbolGraph` (via a serialized format),
  `Type` definitions, and `Interface` contracts.
- **Forbidden**: direct access to the original YAML files, the `ProposalEngine`
  internal state, or the `ForbiddenImports` configuration.

### B. PROPOSE Access (The Transaction)

The AI Agent may submit a **Proposal** document, which is a transaction over
the SDL documents of the project.

- **Document kind**: `kind: proposal`, as defined in specification section 8.2.
- **Envelope**: `id`, `target_version`, `author`, `rationale`, `approve`,
  `patches`.
- **Patches**: `target`, `action` (`add`, `replace`, `remove`) and `value`, as
  defined in specification section 8.3.
- **Target syntax**: `<kind>.<id>.<path>`, or `<file>:<path>` where the path
  is relative to the root object of the document. A path segment is `.name`,
  `[name]` or `[3]`. For example
  `project.bindings[PaymentProvider]` or `types.sdl.yaml:HeroContent.fields`.
- **Requirement**: `target_version` must match the version of the project.
- **Approval**: the final acceptance is performed by an administrator who
  confirms `approve: true`. Without it, a valid proposal changes nothing.

### C. FORBIDDEN Actions

Any attempt by the AI Agent to perform the following actions must be blocked by
the system:

- Direct modification of the SDL documents.
- Bypassing the `ProposalEngine` to write directly to YAML files.
- Modifying the `ForbiddenImports` list or existing `Constraints`.
- Forcing a "merge" without going through the `Semantic Firewall`.

## 3. The Validation Loop

Every proposal submitted by the AI is subject to the pipeline of
specification section 8.4:

```
PROPOSAL
  -> phase 1  syntactic validation
  -> phase 2  referential validation
  -> phase 3  policy check
  -> phase 4  semantic simulation
  -> approval
  -> merge
```

The AI agent receives a validation report containing all errors (for example a
type mismatch or a broken reference), which the agent must then use to correct
its next proposal. Every diagnostic carries an `SDL-Exxx` code from the
registry in `sdl/diagnostics.py`.

The verdict is also available as one machine readable object:

```powershell
python -m sdl propose my_change.sdl.yaml --json
```

```json
{
  "proposal": "prop_guard_the_greeting",
  "accepted": false,
  "merged": false,
  "phase": "semantic",
  "message": "The virtual specification violates the specification.",
  "changed": [],
  "diagnostics": [
    {"phase": "ir", "severity": "error", "code": "SDL-E511", "message": "...",
     "location": {"file": "...", "path": "", "line": 1, "column": 1}}
  ]
}
```

The process exits non-zero when the proposal is rejected, so an agent can rely
on the exit code and read the object for the detail.

## 4. Governance Guarantee

No matter how convincing the AI's rationale is, the **Semantic Firewall** is
the final authority. A proposal is accepted only if it is semantically valid
according to the project's defined rules, and it changes nothing until an
administrator approves it.

## 5. Known limitations an agent must not rely on

These are gaps in the current implementation, not in the contract. An agent
must not assume they are enforced until the corresponding status row in
`README.md` says they are.

- A merged document is re-serialised from its data, so its layout is
  normalised: the blank lines, the quoting and the indentation are the
  toolchain's, not the author's. The comments are preserved, beside the nodes
  they annotate; a comment on a node a patch removed is dropped.

## 6. What the engine already enforces

* A proposal that cannot be applied is rejected.
* A proposal whose `target_version` does not match the version of the project
  is rejected with `SDL-E703`.
* A patch whose target names an element that does not exist is rejected with
  `SDL-E701`, in the referential phase.
* Two patches that target the same element are rejected with `SDL-E704`,
  whatever form the two targets are written in.
* Every new name a patch introduces must exist in the specification or be
  introduced by the same proposal, otherwise `SDL-E702`.
* The identifiers of existing components may not change, and a signature may
  not change without a version increment. A signature change needs the MAJOR
  version of the interface. All of them are `SDL-E602`.
* Phase four builds a virtual specification and runs the whole pipeline on
  it. A proposal that breaks a type, a reference, a binding or a layering
  prohibition is rejected with `SDL-E501`, `SDL-E502`, `SDL-E511`, `SDL-E603`
  or `SDL-E601`.
* The signature of a Python implementation is checked against the interface it
  declares. A signature the validator cannot read is `SDL-E607`, never a
  silent pass.
* A proposal without `approve: true` changes nothing, byte for byte.
* The merge is a transaction. A replacement that fails rolls the documents
  that were already replaced back, and the proposal is rejected with
  `SDL-E705`.
* A merged proposal leaves the project in a valid state.
* The `add` action adds an element to a list, or a field to a mapping. The
  target names the collection that receives the value.
* A type definition that changes needs a migration plan when the project turns
  on `require_migration_for_type_change`. The plan is the `migration` field of
  the proposal document: each entry names a `type` and the `documents` the plan
  covers, and every document that depends on the changed type must be named. A
  plan that names a document outside the project, or that omits a dependent
  document, is refused with `SDL-E602`.
