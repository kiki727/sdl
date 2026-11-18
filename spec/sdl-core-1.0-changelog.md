# SDL Core 1.0 — Changelog against Core 0.3

This file records every normative difference between the archived Core 0.3
specification (`archive/specs/sdl-core-0.3.md`) and the current Core 1.0
specification (`spec/sdl-core-1.0.md`).

The Core 0.3 text was renamed to "SDL Core 1.0" during the 0.3 development
cycle, but the rename was not propagated to the filename, the envelope string,
or the section headings. This consolidation completes that rename.

## 1. Normative changes

| # | Section | Change | Rationale |
| :--- | :--- | :--- | :--- |
| C1 | New §0 "Versioning" | Added. Defines the Core version / envelope version / document version distinction and states that the envelope version equals the Core version. | The repository carried three labels (`0.3`, `1.0`, `SDL Core 1.0`) for one thing. This section makes the rule explicit so it cannot drift again. |
| C2 | §1 heading | `## 1. Scope of 0.3` → `## 1. Scope of 1.0` | Heading consistency with the Core version. |
| C3 | §2.1, §6.1.1, §6.2.1, §8.2 | `sdl: "0.3"` → `sdl: "1.0"` in all four envelope examples | Rule 1.1 of `spec/VERSIONING.md`. |
| C4 | §4.2 | "the 0.3 validator" → "the 1.0 validator" | Terminology consistency. |
| C5 | §8.4 step 4 | "violates any rule from 0.2 or 0.3" → "violates any rule from 0.2 or 1.0" | Terminology consistency. |
| C6 | Title block | Removed the "(Formerly 0.3)" marker. | The historical marker is now recorded in `spec/VERSIONING.md` §2 and in this changelog, where it belongs. |

## 2. Non-normative changes

None. The prose of Core 0.3 was not rewritten, reworded, or reordered.

## 3. What did **not** change

The following sections are byte-identical to the archived Core 0.3 text:

* §2 Flow Documents (2.1 Envelope, 2.2 Flow Components, 2.3 Data-flow and Mapping)
* §3 Control Flow (3.1 Sequentiality, 3.2 Conditional Execution, 3.3 Errors in Flow)
* §4 Constraints & Guardrails (4.1 Architectural Prohibitions, 4.2 Semantic Invariants, 4.3 Procedural Prohibitions)
* §5 Interface Compatibility (5.2 Method Signature Compatibility, 5.3 Implementation Rules, 5.4 Version Compatibility)
* §6 Implementations and Bindings (6.2 Binding System, 6.3 Replacement Lifecycle)
* §7 Backend and Build Configuration (7.1 Backend Targets, 7.2 Build Profiles)
* §8 LLM Proposal Protocol (8.1 – 8.5)
* §9 Canonical IR (9.1 – 9.4)

## 4. Clarifications to section 9 (the Canonical IR)

Section 9.2 lists the symbols and the relations of the canonical IR. The list
is illustrative: section 9.2.1 states that *every element in SDL becomes a
symbol*, and section 9.2.2 that relations are explicit. The implementation
therefore uses the following, each of which is required by another section of
the specification.

### 4.1 Symbols

| Symbol | Required by |
| :--- | :--- |
| `S_Implementation` | Section 6.1 defines the implementation document as an element of SDL. |
| `S_FlowStep` | Section 2.2.2 defines the step as an element of a flow. |
| `S_Type` with kind `alias`, `enum`, `compound` | Section 2.3.2 maps a flow output onto a field of a type, which requires fields to exist. |

### 4.2 Relations

| Relation | Required by |
| :--- | :--- |
| `CONTAINS` | Section 9.2.2: structural membership of the project, the module, the interface and the flow. |
| `HAS_STEP` | Section 2.2.2: a flow is composed of steps. |
| `NEXT` | Section 3.1: the steps are executed strictly in the order they are defined. |
| `IMPLEMENTS` | Section 5.3, from a method to the interface that declares it. |
| `BINDS_TO` | Section 6.2: a binding connects an interface to the implementation that is bound to it. |

The relations `INPUT_BINDING` and `OUTPUT_BINDING` of the earlier design notes
are not used. The data a step reads and writes is held in the step itself, in
its `mapping` and `output_map` attributes, because the Flow State is a
per-execution container and not a graph node.

### 4.3 Determinism

Section 9.1 requires the canonical IR to be a stable format. The identifier of
a symbol is derived from its qualified name and never from a counter or a
random source, so two builds of the same document produce the same graph, byte
for byte. The built-in types are part of the language and are not contained by
the project.

---

## 5. Artifacts added by this consolidation

These are not specification rules; they are the machine-verifiable companions
of Core 1.0.

| Artifact | Purpose |
| :--- | :--- |
| `sdl/schema/sdl-1.0.schema.json` | JSON Schema 2020-12 for Core 1.0 documents (`project`, `module`, `interface`, `types`, `flow`, `implementation`, `proposal`). |
| `sdl/schema/sdl-1.0.validation.schema.json` | Shape of the validation report emitted by the Core 1.0 validator. |
| `conformance/1.0/` | Conformance manifest and fixtures for Core 1.0. |

### 5.1 The `approve` field of a proposal

Section 8.5 states that the final acceptance is performed by an administrator
who confirms `approve: true`, but the envelope of section 8.2 does not list
the field. The JSON Schema accepts it as an optional boolean on the proposal
root object.

### 5.2 The target syntax of a patch

Section 8.3 defines the target of a patch as a path to an element of the
specification, with the syntax `object.field` or `list[index]`. Two forms are
accepted, and both are written in the form the specification uses:

* `<kind>.<id>.<path>` or `<kind>.<path>`, where the document is named by its
  kind and, when it has one, its identifier — `project.bindings[PaymentProvider]`,
  `module.payment_logic.imports`;
* `<file>:<path>`, where the document is named by its path relative to the
  project root — `types.sdl.yaml:HeroContent.fields`.

The path is relative to the root object of the document, that is to the value
of the `kind` key. A segment is `.name` for a key of a mapping, `[name]` for
a key of a mapping or for the element of a list whose `id` is `name`, and
`[3]` for the third element of a list.

### 5.3 The version increment of a merge

Section 8.5 says the project version is incremented according to semver rules,
and gives MAJOR as the example of a breaking change. The implementation
increments MAJOR when a method signature changes, MINOR when a component is
added or removed or a component version changes, and PATCH otherwise.

## 6. Implementation impact of C3

The envelope change from `"0.3"` to `"1.0"` applies to every Core 1.0 document
in the working tree.

| File | Occurrences |
| :--- | :--- |
| `examples/payment_system/{project,types,interfaces,implementations,flow}.sdl.yaml` | 1 each |
| `examples/hero_site/{project,types,interface_content,interface_template,impl_content,impl_template,flow,proposal}.sdl.yaml` | 1 each |

The 0.2 conformance fixtures are **not** affected: they are 0.2 documents and
correctly keep `sdl: "0.2"` under Rule 1.1.

### 6.1 Consequences for the example architectures

Applying the envelope change surfaced three pre-existing violations of the
rules Core 1.0 inherits from Core 0.2. They are recorded here because they are
consequences of the consolidation, not independent design changes. The full
list of example changes is in `CHANGELOG.md`.

1. **File extension.** Core 0.2 §4 requires that every import resolves to a
   `.sdl.yaml` file, and the Core 0.2 conformance suite has a case for it
   (`invalid/imports/wrong-extension.sdl.yaml`). The example documents used
   plain `.yaml` names, which the validator therefore rejected. All example
   documents were renamed to the `.sdl.yaml` extension and every `path:`
   reference was updated.
2. **Method identifiers.** Core 0.2 §5 requires a method `id` to be
   snake_case. `hero_site` used `getHeroContent` and `renderHero`. They were
   renamed to `get_hero_content` and `render_hero`, together with the `call:`
   and proposal patch targets that reference them.
3. **Flow output mapping.** Core 1.0 §2.2.1 makes `output_mapping` mandatory
   for a flow that declares `outputs`. Neither example flow declared one. The
   mappings were added, and the `payment_system` flow outputs were aligned with
   the `PaymentResponse` type that supplies them.

Two example files were removed rather than corrected:
`examples/hero_site/interfaces.yaml` and `examples/hero_site/implementations.yaml`.
Both were multi-document files, which the Core 0.2 YAML subset forbids, and
both duplicated the split `interface_content` / `interface_template` /
`impl_content` / `impl_template` files that the project actually imports.

---

## 7. How the rules of sections 2, 5, 6, 7 and 8 are read

The specification is frozen. The rules below were already in it; the
implementation had not applied all of them. This section records how each of
them is read, so that the behaviour of the toolchain is predictable and the
deviations are visible.

### 7.1 The output mapping of a flow (section 2.3.3)

Section 2.3.3 states that the data type in the Flow State must be assignable
to the type that is declared. The rule is stated for the input mapping of a
step; it is applied to the **output mapping of the flow** as well, because
the outputs of a flow are declared in section 2.2.1 and are populated by the
last mapping of the flow. A flow may therefore not promise a type that the
state does not hold.

A path is only checked as far as the specification describes the shape of the
value. A field of a compound type that does not exist is an error
(`SDL-E502`); a path that goes through a type whose shape the specification
does not describe, such as `Result<T, E>`, is not checked at all.

### 7.2 A call needs a binding (section 6.2, rule three)

Section 6.2, rule three, says that a call is resolved through the bindings
table. A call to an interface that the project binds no implementation for
cannot be resolved, neither by the runtime nor by the code generator, so it
is refused (`SDL-E603`). A call to a **module** function needs no binding:
the module is the code itself.

### 7.3 The language of an implementation (section 7.2)

Section 7.2 says the target must be compatible with the languages of all the
implementations the build uses. The specification does not define what
"compatible" means for languages, so the rule is checked for the back ends
the toolchain implements, which know the languages they can host. A project
that names another language is a valid document: the specification is
independent of the languages the toolchain speaks. The **build** refuses a
target it cannot produce (`SDL-E605`), instead of producing something else.

### 7.4 The version of a breaking change (section 5.4)

Section 5.4 says a change that breaks a signature must increment the **MAJOR**
version of the interface. The policy of section 4.3 only asks for a version
increment; the stricter rule of section 5.4 is applied, so a signature change
with a smaller version increment is refused (`SDL-E602`).

The version of the **project** follows section 8.5: MAJOR when the proposal
breaks a contract, MINOR when a component is added or removed or a component
version changes, PATCH otherwise. A method that disappears from an interface,
and an interface or a type that disappears, break a contract, so they are
MAJOR.

### 7.5 The `add` action (section 8.3)

Section 8.3 says `add` *adds a new element to a list or a new field to an
object*. The target therefore names the **collection that receives the
value**, not the position of the new value:

* a target that names a list receives a new element;
* a target that names a mapping receives the fields of the value;
* a target that does not exist yet receives the value as a new field of its
  parent, which has to exist.

The example of section 8.2, `module.payment_logic.imports` with the action
`add`, is an addition to a list, and it works.

### 7.6 The phase of a target that resolves to nothing (section 8.4)

Section 8.4 orders the phases: syntactic, referential, policy, semantic. A
target that names an element that does not exist is a **referential**
failure, not a policy failure, so it is reported in the second phase
(`SDL-E701`).
