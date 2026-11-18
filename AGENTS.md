# AGENTS.md — Working with the SDL repository

## 🛡️ Project Status: Core 1.0 — specification frozen, implementation in progress

This repository contains the **SDL (Specification Description Language) core**.

* The **specification** for Core 1.0 is frozen: `spec/sdl-core-1.0.md`.
* The **implementation** is **not** complete. `README.md` carries a status
  table that is kept honest. Do not describe the project as production ready.

### ⚠️ The Golden Rule

**Do not modify the frozen parts of Core 1.0 without an explicit instruction.**

Frozen:
* `spec/sdl-core-1.0.md` — the specification text
* `archive/specs/**` — superseded specifications (read only)
* `conformance/**` — the conformance suites (unless a rule genuinely changes)

Not frozen, and where the work actually is:
* `sdl/` — the implementation
* `tests/` — the test suite
* `examples/` — the reference architectures
* `spec/VERSIONING.md`, `spec/sdl-core-1.0-changelog.md` — the version policy
  and the record of what changed

## 🛠️ Operational Workflow

### 1. Proposing Changes

An agent does not modify the architecture of an SDL project directly. It
submits a `Proposal` through `sdl.proposal`, which applies the patches to a
shadow copy, runs the Semantic Firewall, and merges only if every check
passes. See `LLM_CONTRACT.md` for the interface boundary and section 8 of the
specification for the protocol.

### 2. Verification Requirement

Any change to the implementation **must** be followed by:

```powershell
python tests/run_all.py
```

Required result: **all eleven groups pass**.

* Core 0.2 conformance: 30/30
* Core 1.0 conformance: 31/31
* Proposal protocol self-check: 18/18
* Package structure: 6/6
* Pipeline integration: 24/24
* Code generation: 28/28
* SDL runtime: 10/10
* Assignability: 20/20
* Compatibility: 15/15
* Proposal recipes: 44/44
* Every example document validates
* The test suite changes nothing in the repository

The conformance suites are the contract. If you change a rule, change the
fixture with it and update `conformance/*/README.md`.

### 3. Diagnostics

Every diagnostic uses the `SDL-Exxx` registry in `sdl/diagnostics.py`. Do not
introduce free-form rule identifiers. If you need a new code, add it to the
registry with a description and document it in the conformance README.

## 📁 Repository Map

| Path | Contents |
| :--- | :--- |
| `VERSION` | The current core version. Single source of truth. |
| `spec/` | The current specification and the version policy. |
| `sdl/` | The implementation, one package, layered. |
| `conformance/` | The conformance suites for Core 0.2 and Core 1.0. |
| `examples/` | Reference architectures. |
| `tests/` | The firewall self-check and the runner. |
| `archive/` | Superseded material. Read only. |

## 🚀 Development Policy

New features are developed in the working tree. The Core 1.0 *specification* is
frozen, so a feature that needs a new rule requires a specification amendment
first: add it to `spec/sdl-core-1.0-changelog.md`, bump the Core version in
`VERSION`, and state the migration in `spec/VERSIONING.md`.

## Order of work

Every layer of the Core 1.0 specification is implemented. The pipeline runs
end to end:

```powershell
python -m sdl build examples/payment_system/project.sdl.yaml
python -m sdl propose examples/hero_site/proposal.sdl.yaml
python -m sdl run examples/payment_system/project.sdl.yaml --flow process_customer_payment
```

What is left is not a layer but a breadth:

* **other back ends.** The `backend.target` of a project may name another
  language. Python and NodeJS/TypeScript are implemented. The build refuses a
  target it cannot produce (`SDL-E605`) instead of producing something else,
  and the rule of section 7.2 is only checked for the back ends the toolchain
  implements, because only those know which languages they can host.
* **the normalisation of a merged document.** A merged document is
  re-serialised from its data, so its *indentation*, its *quoting* and its
  line breaks are the toolchain's, not the author's. The *comments* and the
  *blank lines* are preserved: they are read out of the original text and put
  back around the nodes they belong to (`sdl/yaml/layout.py`). A comment or a
  blank line that belonged to a node the proposal removed is dropped, because
  there is no longer a node to hold it.

### The back ends

A back end is selected by the `backend.target` of the project, through
`sdl.backends.codegen_for`. `IMPLEMENTED_TARGETS` is the list of the targets
the toolchain can produce, and `sdl.backends.CODEGEN` maps each to its
generator. The Python back end is `sdl/backends/codegen/python_gen.py`, the
NodeJS one is `sdl/backends/codegen/typescript_gen.py`.

The generated source must satisfy three rules, for either back end:

* it must be **valid in its language**. Every generated Python file is parsed
  by the test suite, and every generated TypeScript file is run by Node, which
  strips the types.
* it must be **deterministic**. The same canonical IR produces the same
  bytes.
* it must not carry **anything the document wrote as raw text**. A condition
  is parsed into a tree and rendered, a type is mapped to a type of the target,
  and a name is rendered as a string literal.

A rule that would break one of these needs a test in
`tests/test_codegen.py` first.

Two things are specific to TypeScript. JavaScript has no keyword arguments, so
the inputs of a method travel as a single object. And the output must be
**erasable** — no `enum`, no `namespace`, no parameter property — so that Node
can run the source by stripping the types; an SDL enum is written as a union
type and a `const` object. The checks that need Node are skipped, with a
printed note, when no Node with `--experimental-strip-types` is on the `PATH`;
CI installs one.

### The runtime

The runtime executes the flows of the canonical IR directly. It follows the
specification: the order of the steps, the conditions, the explicit data flow,
the error strategies and the mandatory outputs.

* A step that names an interface method is resolved through the **bindings
  table**, as section 6.2 requires. The registry holds the implementations,
  not the methods.
* A condition is parsed into a tree and evaluated against the state. It is
  never evaluated as text.
* The runtime of the `execute` mode and the runtime of the generated code are
  two different things. The first interprets the canonical IR, the second is
  the code the back end writes.

### The compatibility engine

The rules of section 5 rest on the assignability rules of Core 0.2 section
6.7, which the implementation follows exactly.

* `sdl/types/assignability.py` — the assignability engine. `T` to `T`, `T` to
  `Optional<T>`, `T` to `T | U`, `List` and `Map` invariant, `Result`
  covariant, classes and enums nominal, `Unit` assignable to nothing, and no
  implicit conversions.
* `sdl/types/semver.py` — the version ranges of Core 0.2 section 4.5.
* `sdl/backends/python_signature.py` — reading the signatures of a Python
  class. The validator never runs the code of an implementation, it only
  parses it.
* `sdl/validation/compatibility.py` — the checks of section 5: the
  completeness of 5.3.1, the signature compatibility of 5.2, and the version
  compatibility of 5.4.

A rule that changes the outcome of a compatibility check needs a test in
`tests/test_assignability.py` or `tests/test_compatibility.py` first.

The identifier of a type is a digest and not its name, so a rule that
depends on the *name* of a type has to resolve it through the graph. A test
fixture whose identifier is the name makes such a rule pass for the wrong
reason.

### The recipes

`tests/recipes.py` holds the **recipes** of the proposal protocol: small,
complete changes that exercise one rule each, together with the outcome the
specification demands. The conformance suites check the *documents*; the
recipes check the *protocol*, which is where the holes were.

A recipe states the phase and the diagnostic code it expects, not only
whether it was accepted, so that a recipe cannot pass for the wrong reason.
Writing recipes is the most effective way to find a hole: every defect listed
in `CHANGELOG.md` under "Fixed by the recipes" was found this way.

A rule that changes the outcome of a recipe needs a recipe first.

### The proposal protocol

A proposal is a transaction over the **documents** of a project, not over the
compiled IR. The specification is the single source of truth, so a change has
to start there.

* The phases are the ones of specification section 8.4: syntactic, referential,
  policy, semantic simulation.
* The policy of section 4.3 lives in `sdl/proposal/policy.py`. A new rule
  needs a new check there and a case in `conformance/1.0/`.
* The approval of section 8.5 is the `approve: true` field of the proposal
  document. Without it, a valid proposal changes nothing.
* The merge writes the changed documents back and increments the project
  version according to semver. A merged document is re-serialised from its
  data, so its indentation and its quoting are normalised; its comments and
  its blank lines are put back around the nodes they belong to
  (`sdl/yaml/layout.py`).
