# SDL Core 1.0 Conformance Suite

This suite proves that the SDL Core 1.0 document layers enforce the rules of
`spec/sdl-core-1.0.md`.

Run it with:

```powershell
python -m sdl.cli.validate --cases conformance/1.0/cases.yaml
```

## Layout

```
cases.yaml                     the manifest
valid/                         documents that must validate cleanly
invalid/envelope/              envelope rules (SDL-E200, SDL-E201, SDL-E202)
invalid/schema/                shape rules (SDL-E203, SDL-E204, SDL-E210)
invalid/yaml/                  the YAML subset inherited from Core 0.2
invalid/types/                 scope rules (SDL-E211, SDL-E213)
invalid/flow/                  flow rules (SDL-E502 - SDL-E507)
invalid/binding/               binding rules (SDL-E603, SDL-E604)
invalid/binding/unbound-interface/   a call without a binding (SDL-E603)
invalid/binding/foreign-language/    a target that cannot host a language (SDL-E606)
```

A module document has a scope of its own, next to the project scope. A
declaration inside a module is resolved in the module scope first and in the
project scope second.

Some cases import sibling files. The imported documents are validated as part
of the importing document, so a project case also proves that its imports are
clean.

## Rules covered

| Spec section | Rule | Code |
| :--- | :--- | :--- |
| 0 (envelope) | The envelope version equals the core version | `SDL-E200` |
| 0 (envelope) | The document kind is known | `SDL-E201` |
| 0 (envelope) | Exactly one root key, and no unknown top level keys | `SDL-E202` |
| 0.2 §3 | No undefined fields | `SDL-E203` |
| 0.2 §3 | No missing mandatory fields | `SDL-E204` |
| 0.2 §4 | Identifiers follow the declared grammar | `SDL-E210` |
| 0.2 §2 | No duplicate mapping keys | `SDL-E101` |
| 0.2 §2 | No flow style collections | `SDL-E102` |
| 0.2 §5 | No duplicate identifiers in a scope | `SDL-E211` |
| 0.2 §5 | No identifier shadows another document | `SDL-E213` || 2.2.1 | A flow with outputs must declare `output_mapping` | `SDL-E503` |
| 2.2.1 | Every declared output must be populated | `SDL-E503` |
| 2.3.3 | A mapping may only read state that exists | `SDL-E502` |
| 3.2.1 | A condition must follow the expression grammar | `SDL-E504` |
| 3.3.1 | `on_error: retry` requires a retry policy | `SDL-E505` |
| 3.3.1 | `on_error` must be a known strategy | `SDL-E506` |
| 3.3.1 | `on_error: goto` must name an existing step | `SDL-E507` |
| 6.2 | A binding must resolve to a known implementation | `SDL-E603` |
| 6.2 | Every interface a flow calls must be bound | `SDL-E603` |
| 5.3, 6.2 | The implementation must implement the bound interface | `SDL-E604` |
| 7.2 | The target must be able to host the language of an implementation | `SDL-E606` |

## Not covered here

The IR level firewall, the proposal engine and the code generator have their
own suites under `tests/`. The document layers above do not check interface
compatibility beyond the existence of the binding, nor do they type check a
flow mapping against the called method: both require the canonical IR and are
therefore IR level concerns.

The same holds for the output mapping of a flow: that a path of the output
mapping names a field that exists, and that the state holds a type that is
assignable to the type the flow declares, are rules of the canonical IR.

Two rules are not in this suite because they are not rules of the
specification, but of the toolchain:

* the back end a project names may be any language, because the
  specification is independent of the languages a toolchain speaks. The
  **build** refuses a target it cannot produce, with `SDL-E605`;
* the rule of section 7.2 is only checked for the back ends the toolchain
  implements, because only those know which languages they can host.

Two further diagnostics of the compatibility engine and the proposal engine
are IR level or toolchain level, so they are proven by `tests/` rather than by
a document case here:

* `SDL-E607` — a Python implementation that declares a source the validator
  cannot read, or a signature without the annotations the validator
  understands. The check is fail closed: an unreadable signature is an error,
  never a silent pass. A target in another language is out of scope of the
  reader and is not rejected. See `tests/test_compatibility.py`.
* `SDL-E705` — a merge of an approved proposal that could not be written. The
  merge is a transaction: a replacement that fails rolls the already replaced
  documents back. See `tests/test_integration.py`.
