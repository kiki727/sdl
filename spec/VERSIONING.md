# SDL Versioning Policy

This file is the normative reference for how SDL versions are named, how the
`VERSION` file at the repository root relates to the specification, and how to
migrate between versions.

## 1. The two version axes

SDL has exactly two version axes. They were previously conflated, which caused
the repository to carry three different labels for the same thing (`0.3`, `1.0`,
and `SDL Core 1.0`). They are now strictly separated.

| Axis | Name | Where it lives | Example |
| :--- | :--- | :--- | :--- |
| **Core version** | The SDL language specification version | `spec/sdl-core-<core>.md`, root `VERSION` | `1.0` |
| **Envelope version** | The value of the `sdl` field in a document | The document itself | `"1.0"` |
| **Document version** | The `version` field of a project/module/interface | The document | `"1.0.0"` |

**Rule 1.1 — The envelope version always equals the Core version.**
An SDL document that declares `sdl: "1.0"` is a Core 1.0 document.

**Rule 1.2 — The root `VERSION` file always equals the current Core version.**
`VERSION` contains `1.0` with no trailing content beyond the newline. It is the
single source of truth for the Core version of the working tree.

**Rule 1.3 — The document `version` field is independent.**
It uses semver (`MAJOR.MINOR.PATCH`), describes the *revision of that document*,
and has no relationship to the Core version except that the Core version sets
the rules the document must obey.

## 2. Version history

| Core | Status | Specification | Envelope | Notes |
| :--- | :--- | :--- | :--- | :--- |
| 0.1 | Superseded | `archive/specs/sdl-core-0.1.md` | `sdl: "0.1"` | Initial formal draft. No schema, no validator. |
| 0.2 | Superseded, **reference baseline** | `archive/specs/sdl-core-0.2.md` | `sdl: "0.2"` | Language foundations. Fully implemented — see `conformance/0.2/`. |
| 0.3 | Superseded, never released | `archive/specs/sdl-core-0.3.md` | `sdl: "0.3"` | Renamed to 1.0 mid-development. The envelope string was never updated. |
| **1.0** | **Current** | `spec/sdl-core-1.0.md` | `sdl: "1.0"` | Adds flow semantics, interface compatibility, implementations/bindings, LLM proposal protocol. |

Core 0.3 was renamed to 1.0 because the language had reached the feature
completeness required for a stable release. The rename was applied to the
document title but not to the filename or the envelope string, which left the
repository in a state where `sdl-0.3.md` declared itself to be "SDL Core 1.0".
The envelope string was corrected to `"1.0"` as part of the consolidation;
see `spec/sdl-core-1.0-changelog.md` for the full list of changes.

## 3. Current version

**Core 1.0** is the current version.

- Specification: `spec/sdl-core-1.0.md`
- Implementation: `sdl/` (package `sdl`, `__version__ == "1.0"`)
- Conformance baseline for 0.2: `conformance/0.2/` (the 0.2 rules remain normative for the 0.2 subset that 1.0 inherits)
- Conformance suite for 1.0: `conformance/1.0/`

## 4. Migration

### 4.1 From 0.2 to 1.0

Core 1.0 **inherits every rule from 0.2**. A document that is valid 0.2 and
uses only 0.2 constructs remains valid 1.0. The changes are additive plus the
envelope rename.

| 0.2 | 1.0 |
| :--- | :--- |
| `sdl: "0.2"` | `sdl: "1.0"` |
| `kind: project` / `module` / `interface` / `types` | unchanged, plus `kind: flow`, `kind: implementation`, `kind: proposal` |
| `project.imports[].path` | unchanged |
| `module.imports[].module` / `.package` | unchanged |
| `output: {type: T}` | unchanged |
| `version: "1.0.0"` | unchanged |
| — | `constraints.forbidden_imports` (layering prohibitions) |
| — | `policy` (procedural prohibitions) |
| — | `bindings` (interface → implementation) |
| — | `backend`, `builds` |
| — | `flow` documents: `inputs`, `steps`, `outputs`, explicit `mapping` / `output_map` |
| — | `implementation` documents: `implements`, `language`, `source` |
| — | `proposal` documents (§8) |

### 4.2 From 0.3 to 1.0

Only the envelope string and the section headings changed. The normative rules
are identical. See `spec/sdl-core-1.0-changelog.md`.

## 5. Errata against superseded specifications

Superseded specifications are frozen and are **not** edited. Where a path or a
rule in them no longer matches the repository, the deviation is recorded here.

### SDL-E01 — Machine-verifiable artifact paths (against 0.2 §8.5)

The 0.2 specification lists the machine-verifiable artifacts of the 0.2
reference validator. Those artifacts now live inside the `sdl` package:

| 0.2 §8.5 path | Current path |
| :--- | :--- |
| `schema/sdl-0.2.schema.json` | `sdl/schema/sdl-0.2.schema.json` |
| `schema/sdl-0.2.validation.schema.json` | `sdl/schema/sdl-0.2.validation.schema.json` |
| `tools/validate_0_2.py` | `python -m sdl.cli.validate` |
| `tools/sdl_yaml.py` | `sdl/yaml/subset.py` |
| `tools/sdl_schema.py` | `sdl/schema/envelope.py` |
| `tools/sdl_types.py` | `sdl/types/expressions.py` |
| `tools/sdl_semantics.py` | `sdl/semantics/scope.py` |
| `tools/sdl_common.py` | `sdl/yaml/diagnostics.py` |
| `fixtures/0.2/cases.yaml` | `conformance/0.2/cases.yaml` |
| `fixtures/0.2/valid/` | `conformance/0.2/valid/` |
| `fixtures/0.2/invalid/` | `conformance/0.2/invalid/` |

The **rules** described in 0.2 §8.5 are unchanged. Only the locations moved,
and the validator behaviour is expected to be byte-identical in its diagnostics.

### SDL-E02 — Envelope version of 0.3 documents

Documents written during the 0.3 development cycle carry `sdl: "0.3"`. Under
Rule 1.1 those are 0.3 documents and are not accepted by the 1.0 validator.
This is a deliberate, documented breaking change, not an oversight.
