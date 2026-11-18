# SDL Core 0.2 Conformance Baseline

Core 1.0 inherits every rule from Core 0.2. This directory holds the
conformance manifest and fixtures that prove the 0.2 layer still behaves
exactly as the frozen 0.2 specification requires.

The validator itself lives in the `sdl` package:

* `sdl/yaml/subset.py` — layer 0, YAML subset
* `sdl/schema/envelope.py` — layer 1, envelope and shape checks
* `sdl/types/expressions.py` — layer 2, type expression grammar
* `sdl/semantics/scope.py` — layer 2, scope / import / type resolution
* `sdl/diagnostics.py` — the SDL diagnostic registry

The frozen 0.2 specification is `archive/specs/sdl-core-0.2.md`. The
deviation between the paths listed in its §8.5 and the paths used here is
recorded as errata `SDL-E01` in `spec/VERSIONING.md` §5. **The rules are
unchanged; only the locations moved.**

## Requirements

* Python 3.10+
* `PyYAML`
* `jsonschema` (Draft 2020-12)

```powershell
python -m pip install pyyaml jsonschema
```

## Usage

Validate a single document:

```powershell
python -m sdl.cli.validate conformance/0.2/valid/project/sdl.yaml
python -m sdl.cli.validate --json conformance/0.2/valid/inference.sdl.yaml
```

When a `project` document is validated, the validator loads and validates every
`path` import as well, and builds the project scope. For a single `module`
document the project scope is empty; run the validator on the project document
for full project validation.

Run the full conformance manifest:

```powershell
python -m sdl.cli.validate --cases conformance/0.2/cases.yaml
```

## Exit codes

Defined in 0.2 §7.4:

| Code | Meaning |
| :--- | :--- |
| `0` | valid |
| `1` | validation errors |
| `2` | tool usage or I/O error |
| `3` | internal validator error |

## Phases

1. `sdl/yaml/subset.py` — UTF-8/BOM, size, depth, tabs, anchors/aliases/merge
   keys, duplicate keys, multi-document, flow style, folded scalars.
2. `sdl/schema/envelope.py` — envelope, permitted fields, ID formats, semver,
   import paths, type expression syntax, JSON Schema 2020-12.
3. `sdl/semantics/scope.py` — scope, duplicate IDs, shadowing, imports and
   visibility, type resolution, alias cycles, generic arity, `Unit`
   restrictions, direct class recursion, inference warnings.

## Scope limits

* The 0.2 layer has no canonical IR, flow semantics, interface
  compatibility/bindings, implementations, backend, LLM proposal protocol,
  extensions or package resolution. Those belong to Core 1.0 and are covered by
  `conformance/1.0/`.
* `SDL-E404` and `SDL-E410` are reserved for the code generation phase and are
  not emitted here.
* Direct class recursion uses `SDL-E403`; the 0.2 specification has no
  dedicated code for it.
