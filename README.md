# SDL — Specification Description Language

**Core version: 1.0** (see [`VERSION`](VERSION) and [`spec/VERSIONING.md`](spec/VERSIONING.md))

SDL is a formal language for specifying software architecture and execution.
A document is validated, lowered into the Canonical IR (a typed symbol graph),
checked by the Semantic Firewall, and then either executed by the SDL runtime or
compiled to source code by a backend.

The point of SDL is to move architectural governance from human review to
automated verification: an AI agent or a human developer cannot introduce a
type mismatch, a broken reference or a forbidden dependency without the
Semantic Firewall rejecting the change.

---

## Current status — read this first

The specification for Core 1.0 is **frozen and complete**
([`spec/sdl-core-1.0.md`](spec/sdl-core-1.0.md)). The **implementation is not
finished**. This repository tracks that gap explicitly rather than claiming
readiness it does not have.

| Area | State | Notes |
| :--- | :--- | :--- |
| YAML subset (layer 0) | **Done** | Inherited from Core 0.2, proven by 30 conformance cases. |
| Envelope + JSON Schema (layer 1) | **Done** | Separate schemas for Core 0.2 and Core 1.0. |
| Document semantics (layer 2) | **Done for 1.0** | Scope, imports, types, flow rules, bindings. 31 conformance cases. |
| AST parser (layer 3) | **Done** | Every Core 1.0 document kind, with source locations. |
| Canonical IR lowering (layer 4) | **Done** | Nothing of the specification is lost. |
| Reference resolution (layer 4) | **Done** | Repeatable, so the firewall can re-derive references. |
| Determinism (layer 4) | **Done** | The same document always produces the same IR, byte for byte. |
| Semantic Firewall (layer 5) | **Done** | The references are derived again after every patch, so a proposal that breaks one is rejected. |
| Proposal protocol (layer 6) | **Done** | The four validation phases of section 8.4, the policy of section 4.3, the approval of section 8.5 and the merge. |
| Code generation (layer 7) | **Done** | Two back ends: Python and NodeJS/TypeScript. Types, interfaces, flows, implementations, runtime. The output is valid in its language, deterministic, and free of raw document text. |
| Runtime (layer 7) | **Done** | The `execute` mode: the runtime executes the flows of the canonical IR directly, with the dynamic binding of section 6.2. |
| Compatibility engine | **Done** | Section 5: the assignability rules of 0.2 §6.7, the signature compatibility of §5.2, the completeness of §5.3 and the version compatibility of §5.4. Fail closed: a Python signature the validator cannot read is `SDL-E607`, never a silent pass. |

Every row above is backed by a check in this repository. Run them with:

```powershell
python tests/run_all.py
```

| Group | Result |
| :--- | :--- |
| Core 0.2 conformance | 30/30 |
| Core 1.0 conformance | 31/31 |
| Proposal protocol self-check | 18/18 |
| Package structure | 6/6 |
| Pipeline integration | 24/24 |
| Code generation | 28/28 |
| SDL runtime | 10/10 |
| Assignability | 20/20 |
| Compatibility | 15/15 |
| Proposal recipes | 44/44 |
| Every example document | 22/22 validate |
| Examples unchanged by the test suite | yes |

The **recipes** are the youngest group. A recipe is a small, complete change
that exercises one rule of the specification, together with the outcome the
specification demands. Writing them is what found the defects that the
conformance suites could not see, because the conformance suites check the
documents and the recipes check the *protocol*. See
[`tests/recipes.py`](tests/recipes.py).

---

## Repository layout

```
VERSION                     the current core version, single source of truth
spec/                       the specifications
  sdl-core-1.0.md           CURRENT specification
  sdl-core-1.0-changelog.md what changed from 0.3 to 1.0
  VERSIONING.md             version policy, migration tables, errata
sdl/                        the implementation, one package, layered
  yaml/       layer 0       YAML subset
  schema/     layer 1       envelope, JSON Schema, shape checks
  types/      layer 2       type expression grammar
  semantics/  layer 2       scope, imports, types, flow rules, bindings
  parser/     layer 3       YAML to AST
  lowering/   layer 4       AST to Canonical IR
  validation/ layer 5       the Semantic Firewall
  proposal/   layer 6       the LLM proposal protocol
  backends/   layer 7       code generation and runtime
  compiler.py               the orchestrator
  documents.py              the document set of a project
  cli/                       command line entry points
conformance/
  0.2/                      the Core 0.2 conformance baseline
  1.0/                      the Core 1.0 conformance suite
examples/                   reference architectures
  payment_system/           a Python backend target
  hero_site/                a TypeScript backend target
tests/                      the firewall self-check and the test runner
archive/                    superseded specifications, notes and legacy tools
```

---

## The pipeline

```
.sdl.yaml document
  -> sdl.yaml        layer 0   YAML subset          SDL-E100 - SDL-E103
  -> sdl.schema      layer 1   envelope + schema   SDL-E200 - SDL-E220
  -> sdl.semantics   layer 2   scope and types     SDL-E300 - SDL-E408, SDL-W1xx
  -> sdl.parser      layer 3   AST
  -> sdl.lowering    layer 4   Canonical IR
  -> sdl.validation  layer 5   Semantic Firewall   SDL-E5xx, SDL-E6xx
  -> sdl.proposal    layer 6   proposal governance SDL-E7xx
  -> sdl.backends    layer 7   codegen / runtime
```

The toolchain implements two back ends, Python and NodeJS/TypeScript. A
project selects one with `backend.target`. A project may name any language,
because the specification is independent of the languages a toolchain speaks,
but the **build** refuses a target it cannot produce (`SDL-E605`) instead of
producing something else.

Every diagnostic carries a phase, a severity, an `SDL-Exxx` code, a message and
a location. The registry lives in [`sdl/diagnostics.py`](sdl/diagnostics.py).

---

## The proposal protocol

An agent may not modify the architecture directly. It submits a **proposal**,
which is a transaction over the **documents** of the project, not over the
compiled IR. The specification is the single source of truth, so a change has to
start there.

```
PROPOSAL
  -> phase 1  syntactic validation     the proposal document itself
  -> phase 2  referential validation  every new name must exist
  -> phase 3  policy check            section 4.3 of the specification
  -> phase 4  semantic simulation      the virtual specification is validated
  -> approval                          section 8.5
  -> merge                             the documents are written back
```

* the patches are applied to a **shadow copy** of the document set
* two patches that name the same element are rejected (`SDL-E704`), even when
  they write the target differently: the identity of a target is the document
  it selects plus its pointer, not the text the proposal wrote
* phase 4 builds a *virtual* specification and runs the whole pipeline on it:
  schema, semantics, lowering, resolution and the Semantic Firewall. A
  virtual specification that breaks a rule is rejected
* a proposal that has not been approved changes nothing
* the merge is a **transaction**: the new text of every document is written to
  a temporary file first, every target is replaced, and a replacement that
  fails rolls the already replaced documents back (`SDL-E705`)
* the merge writes the changed documents back and increments the project
  version according to semver. A proposal that changes nothing does not move
  the version
* the merge keeps the **comments** and the **blank lines** of the documents it
  rewrites. The data of a document carries neither, so they are read out of the
  original text and put back around the nodes they belong to
  (`sdl/yaml/layout.py`). Indentation and quoting are still normalised, because
  the document is re-serialised

A patch names an element of the specification:

```yaml
patches:
  - target: "types.sdl.yaml:HeroContent.fields"
    action: add
    value:
      description: String
```

The target of an `add` names the collection that receives the value: a list
receives an element, a mapping receives a field.

The boundary for agents is defined in
[`LLM_CONTRACT.md`](LLM_CONTRACT.md), and the rules it refers to live in
sections 4.3 and 8 of the Core 1.0 specification.

Run a proposal with:

```powershell
python -m sdl propose examples/hero_site/proposal.sdl.yaml
```

How to write one, what the target syntax is and what happens after the merge
is in [`docs/proposals.md`](docs/proposals.md).

---

## Getting started

```powershell
python -m pip install pyyaml jsonschema

# validate a single document
python -m sdl validate examples/payment_system/project.sdl.yaml

# compile a project into the canonical IR
python -m sdl build examples/payment_system/project.sdl.yaml

# execute a flow of the canonical IR (the `execute` mode)
python -m sdl run examples/payment_system/project.sdl.yaml `
  --flow process_customer_payment `
  --input order_id=42 --input amount=10.5 --input token=tok_demo

# run a proposal through the governance engine
python -m sdl propose examples/hero_site/proposal.sdl.yaml

# ... and read the verdict as JSON, for a tool or an agent
python -m sdl propose examples/hero_site/proposal.sdl.yaml --json

# run the conformance suites
python -m sdl validate --cases conformance/0.2/cases.yaml
python -m sdl validate --cases conformance/1.0/cases.yaml

# run every check in the repository
python tests/run_all.py
```

The `payment_system` example is the smallest project that runs end to end:
a type, an interface, an implementation, a module function, a flow and a
binding. See [`examples/payment_system/README.md`](examples/payment_system/README.md).

---

## Versioning

There are exactly two version axes, and the repository used to confuse them.

* **Core version** — the SDL language specification. The current one is `1.0`.
  It is recorded in [`VERSION`](VERSION) and in `sdl.__version__`.
* **Envelope version** — the value of the `sdl` field in a document. It always
  equals the Core version, so a Core 1.0 document declares `sdl: "1.0"`.

Core 0.3 was renamed to Core 1.0 during development, but the rename never
reached the filename, the envelope string or the section headings. That is now
fixed. The full history, the migration tables and the errata against the
superseded specifications are in [`spec/VERSIONING.md`](spec/VERSIONING.md).

---

## Historical specifications

The superseded specifications are kept verbatim in
[`archive/specs/`](archive/specs) and are not edited. Core 0.2 remains the
normative baseline for the rules that Core 1.0 inherits.

[`archive/README.md`](archive/README.md) explains what is in the archive and
why.
