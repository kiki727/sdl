# SDL Core 0.2 — Language Foundations

Status: Working Draft. This document locks the language foundations: YAML subset, document envelope, identifiers and references, imports, and the type system. JSON Schema, conformance examples, and a reference validator exist; a production parser, validator, and canonical IR are not implemented. Flow semantics, backend, LLM protocol, and extensions are out of scope for 0.2.

## 0. Normative Language

- **MUST** — mandatory. Violation makes the document invalid.
- **SHOULD** — recommended. Deviation must be justified.
- **MAY** — optional.
- Language keywords are in English; specification prose is in English.
- SDL 0.2 is not compatible with 0.1. Documents must be migrated; 0.1 remains a historical version.

## 1. Scope of 0.2

In scope:

- strict YAML subset and parsing rules;
- document envelope (`sdl`, `kind`, root key);
- ID grammar, namespaces, and references;
- imports and visibility;
- type expression grammar, built-in types, aliases, enums, classes, and function/interface signatures;
- validation diagnostics for this layer.

Out of scope for 0.2:

- flow execution and data-flow;
- interface compatibility and binding rules;
- implementation selection, backend, and build;
- LLM proposal protocol;
- extensions;
- package resolver and lockfile;
- `requirements` and `constraints`.

Documents containing fields outside the scope of 0.2 are invalid in 0.2; they must not be silently ignored.

## 2. YAML Subset

SDL uses the YAML 1.2 core schema. The parser MUST reject everything not in this subset.

### 2.1 Mandatory Rules

| Rule | Level |
| --- | --- |
| YAML 1.2 core schema, without custom tags | MUST |
| UTF-8 without BOM | MUST |
| One YAML document per file | MUST |
| Duplicate mapping keys are an error | MUST |
| Anchors (`&`), aliases (`*`), and merge keys (`<<`) are forbidden | MUST |
| Multi-document (`---`/`...` separation) is forbidden | MUST |
| Complex mapping keys are forbidden | MUST |
| Tabs in indentation are forbidden; indent is 2 spaces | MUST |
| Unnamed null (`key:`) is permitted only if the schema allows null | MUST |
| String fields must not be implicit booleans, numbers, or dates | MUST |
| `sdl` and `version` MUST be in double quotes; IDs and enum values that look like bool/number/null MUST also be quoted | MUST |
| Inline code uses literal block `|`; folded `>` is forbidden | MUST |
| Maximum depth is 64; maximum document size is 1 MiB | MUST |
| Comments are permitted and have no semantic meaning | MAY |
| Flow style is permitted only for empty collections `[]` and `{}` | MUST |

### 2.2 Implicit Types

- Booleans are only `true` and `false`.
- `yes`, `no`, `on`, `off` are not booleans; if used as strings, they must be quoted.
- Numbers are decimals. Hexadecimal, octal, and sexagesimal notations are not permitted.
- Dates and times are not implicit YAML types; quoted ISO 8601 strings are used.
- If a field requires a string, a plain scalar that YAML can interpret as a bool/number/null is an error; the value must be quoted.

### 2.3 Canonical Form

- The source file MAY use comments and arbitrary key order; key order has no semantic meaning.
- The canonical IR is a JSON with sorted keys and no comments.
- The canonical IR retains `sdl`, `kind`, and the root key; all object keys are sorted lexicographically.
- Array order remains the same as in the source, except for union type members, which are sorted and deduplicated.
- Type expressions in the IR are normalized without redundant spaces; parentheses are removed when they do not change meaning.
- The parser MUST preserve source locations (`file`, `line`, `column`) for every node; locations are not part of the canonical IR.
- The parser MUST reject unknown fields, except for those defined by this specification.
- Diagnostics in the IR are sorted according to the rule in §7.2.

### 2.4 Forbidden Features

- environment interpolation;
- implicit include;
- arbitrary YAML tags;
- automatic YAML timestamp/date conversion;
- reliance on key or file order.

## 3. Document Envelope

Every SDL file is a single document with a mandatory envelope:

```yaml
sdl: "0.2"
kind: module

module:
  id: example
```

Rules:

- `sdl` MUST be exactly `"0.2"` for this version.
- `kind` MUST be one of: `project`, `module`, `interface`, `types`.
- The root key MUST match the `kind` and MUST exist exactly once.
- No other top-level keys are permitted.
- A document MUST be complete; fragments are permitted only in the prose of the specification, not in `.sdl.yaml` files.
- `implementation` and `build` are reserved for 0.3 and are invalid in 0.2.
- `extensions` is reserved and invalid in 0.2.

### 3.1 Permitted Fields by Kind

| `kind` | Root | Permitted fields in 0.2 |
| --- | --- | --- |
| `project` | `project` | `id`, `version`, `mode`, `imports`, `types`, `interfaces` |
| `module` | `module` | `id`, `mode`, `imports`, `types`, `interfaces`, `classes`, `functions` |
| `interface` | `interface` | `id`, `version`, `methods` |
| `types` | `types` | `types` |

All other fields are invalid in 0.2.

Mandatory fields:

- `project.id` and `project.version`;
- `module.id`;
- `interface.id` and `interface.version`;
- `types` must be a non-empty list when the root document is `kind: types`.

Meaning of collections:

- `types` is a list of aliases or enums.
- `interfaces` is a list of interface objects of the same shape as the root `interface`, without the envelope.
- In the project document, `types` and `interfaces` enter the project scope.
- In the module document, `types` and `interfaces` enter the scope of that module.
- A `kind: types` document contributes to the project scope as it is imported exclusively at the project level.
- A `kind: interface` document defines exactly one interface in the project scope.

### 3.2 Modes

- `mode` MAY be `structural` or `declarative`.
- The default mode is `structural`.
- Project mode is inherited by modules; a module MAY override it.
- Rules on which fields are permitted by mode will be defined in 0.3. In 0.2, `mode` is only parsed and inherited.

### 3.3 Object Shapes

Every object permits only the listed fields; unknown fields are an error.

| Object | Mandatory Fields | Optional Fields |
| --- | --- | --- |
| `project` | `id`, `version` | `mode`, `imports`, `types`, `interfaces` |
| `module` | `id` | `mode`, `imports`, `types`, `interfaces`, `classes`, `functions` |
| `interface` | `id`, `version` | `methods` |
| `types` document | `types` | — |
| project import | `path` | — |
| module import | `module` | — |
| package import | `package`, `version` | — |
| type alias | `id`, `type` | — |
| enum | `id`, `enum` | — |
| class | `id` | `properties` |
| function | `id`, `output` | `input` |
| method | `id`, `output` | `input` |
| output | `type` | — |
| interface reference | `id` | `module`, `version` |
| inferred type | `origin: inferred`, `type` | `confidence`, `status` |
| unresolved type | `origin: unresolved`, `reason` | — |
| validation report (`validation` object) | `status`, `diagnostics` | — |
| diagnostic | `phase`, `severity`, `code`, `message`, `location` | — |
| location | `file`, `path`, `line`, `column` | — |

- A project import contains exactly one `path`; a module import contains exactly one of `module` or `package` (+ `version`).
- A type declaration contains exactly one of `type` or `enum`.
- `output.type` is a type expression string; inference objects are not permitted in `output`.
- `methods`, `properties`, and `input` MAY be omitted; then they are empty.
- `interfaces` is a list of interface objects; an interface object does not contain nested `interfaces`.
- A validation report is not an SDL document and does not follow envelope rules.
- `line` and `column` are positive integers; `path` is a JSON Pointer.

## 4. Identifiers and References

### 4.1 ID Grammar

| Element | Pattern | Example |
| --- | --- | --- |
| Project, module, function, method, field | `[a-z][a-z0-9_]*` | `task_manager`, `create_task` |
| Type, interface, class, enum | `[A-Z][A-Za-z0-9]*` | `TaskId`, `PaymentProvider` |
| Enum value | `[a-z][a-z0-9_]*` | `todo` |
| Package | `[A-Za-z0-9][A-Za-z0-9._-]*` | `sqlalchemy` |
| Semver version | `MAJOR.MINOR.PATCH` | `"1.0.0"` |

- IDs are case-sensitive.
- An ID must not contain `::`, spaces, or dots. Dots are permitted only in package names.
- Built-in types (`String`, `Boolean`, `Int`, `Float`, `Decimal`, `UUID`, `Date`, `DateTime`, `Bytes`, `Unit`, `List`, `Map`, `Result`, `Optional`) must not be redeclared.
- IDs that YAML can interpret as bool/number/null MUST be quoted.
- Semver in 0.2 does not allow prerelease or build metadata; only `MAJOR.MINOR.PATCH` is permitted.

### 4.2 Scope and Uniqueness

- The project has scope `project`.
- Every module has a scope equal to its `module.id`.
- `module.id` is unique within the project.
- Project IDs are unique in the project scope. This includes `types` and `interfaces` from the project document and from imported `types`/`interface` documents.
- IDs within a module are unique in that module, including its `types` and `interfaces`.
- Methods are unique within an interface; fields within a class; enum values within an enum.
- A name in a module must not shadow the same name in the project scope. Such a collision is an error.

### 4.3 Qualified Names

- A local reference is simply a name: `Task`.
- A reference to another module is `module_id::Type`.
- A reference to the project scope is `project::Type`.
- The colon `::` is the only separator; `module.Type` is not permitted.
- In the project, `interface`, and `types` documents, local names are searched in the project scope.
- In a module document, a local name is first searched in the current module, then in the project scope.
- `module::Type` is permitted only if that module is imported by the current module or is the current module itself.
- `project::Type` always references the project scope.
- Order of documents and declarations does not affect resolution; forward references are permitted.
- A qualified name must reference an alias, enum, class, or interface; functions and methods are not types.
- Cross-module references require the module to be imported.

### 4.4 Structured References

Interface references use objects, not dotted strings. The following block is a reference fragment, not an SDL document:

```yaml
interface:
  module: payments
  id: PaymentProvider
  version: "^1.0.0"
```

- `module` MAY be omitted for local references.
- `project` is a permitted value for `module` when referencing the project scope.
- `version` MAY be omitted; if provided, it is a semver range string.
- In 0.2, there is at most one version of a given interface per scope; if `version` exists, it must cover that version.
- Structured references to implementations will be defined in 0.3; `implementation` is not part of 0.2.

### 4.5 Semver Range

The following subset is supported:

```text
range      := comparator (" " comparator)*
comparator := ("^" | "~" | ">=" | "<=" | ">" | "<" | "=") version
             | version
```

- The comma is not a separator; space is used.
- `||` is not supported in 0.2.
- An exact version is a valid range.
- Semver must have all three parts: `"1.0.0"`, not `"1.0"`.
- Prerelease and build metadata are not permitted in 0.2.
- `^1.2.3` means `>=1.2.3 <2.0.0`; `~1.2.3` means `>=1.2.3 <1.3.0`.
- Without an operator, the version means an exact match.
- Multiple comparators in the same range are combined with a logical AND.

## 5. Imports and Visibility

### 5.1 Project Imports

The project imports SDL documents by path:

```yaml
project:
  id: task_manager
  version: "1.0.0"

  imports:
    - path: modules/tasks.sdl.yaml
    - path: interfaces/task_service.sdl.yaml
```

Rules:

- `path` is relative to the project root.
- The separator is `/`, regardless of the OS.
- Absolute paths, `..` outside the root, and symlinks outside the root are forbidden.
- Every import must be a `.sdl.yaml` file.
- Project imports may reference `module`, `interface`, or `types` documents; the `project` document is not permitted.
- Duplicate imports are an error.
- Imported `types` and `interface` documents contribute to the project scope.
- Project `types` and `interfaces` are visible to all modules.

### 5.2 Module Imports

Modules import other modules or external packages:

```yaml
module:
  id: tasks

  imports:
    - module: users
    - package: sqlalchemy
      version: ">=2.0.0 <3.0.0"
```

Rules:

- `module` references a `module.id` and must exist in the project.
- `package` is an external package; package resolution is out of scope for 0.2.
- Package imports require a `version` semver range.
- A module cannot import itself.
- The import graph MUST be acyclic. The dependency graph is out of scope for 0.2.
- Duplicate imports are an error.

### 5.4 Path Resolution

- The project root is the directory containing the root `sdl.yaml` document or the first `project` document in the provided set of files.
- A `path` import is resolved relative to the file containing it; the result is normalized to a canonical path within the project root.
- Paths are normalized: `.` segments are removed, slashes are collapsed, and crossing the project root is forbidden.
- `\` is converted to `/`.
- Path comparison is case-sensitive. On case-insensitive file systems, two paths that differ only in case are considered duplicate imports.
- The resolved file must exist and be a `.sdl.yaml` file.
- Circular symlinks are an error.
- Importing the same normalized path multiple times is an error.

### 5.5 Import Graph

- Graph nodes are documents; edges exist for every `path` import and every `module` import.
- A `package` import is not a node in the import graph in 0.2.
- The import graph MUST be acyclic; a cycle is `SDL-E301`.
- Project import of a `project` document is forbidden, so the project document cannot be part of a cycle.

### 5.3 Visibility

- The project scope is visible to all modules.
- The module scope is visible only to that module and modules that import it.
- In 0.2, there are no `private`/`public` modifiers; visibility is determined solely by scope and imports.
- Cross-module access without an import is an error.

## 6. Type System

### 6.1 Type Expression Grammar

```ebnf
type_expr      := union ;
union          := primary { "|" primary } ;
primary        := builtin | qualified_name | generic | "(" type_expr ")" ;
generic        := qualified_name "<" type_expr { "," type_expr } ">" ;
qualified_name := [ scope "::" ] type_id ;
scope          := "project" | module_id ;
type_id        := pascal_id ;
```

- Union has the lowest priority.
- Generics are `List<T>`, `Map<K,V>`, `Result<T,E>`, `Optional<T>`.
- Only built-in generics are permitted in 0.2; user-defined generics are out of scope.
- Arity is mandatory: `List` 1, `Map` 2, `Result` 2, `Optional` 1 argument.
- A generic without arguments or with the wrong number of arguments is an error.
- Parentheses group; redundant parentheses are removed in the canonical form.
- Spaces around `|`, `<`, `,` are permitted; the canonical form has no redundant spaces.
- The canonical IR sorts and deduplicates union members; nested unions are flattened.
- `List`, `Map`, `Result`, and `Optional` are not permitted as bare types without arguments.

### 6.2 Built-in Types

| Type | Meaning | Constraint |
| --- | --- | --- |
| `String` | UTF-8 string | — |
| `Boolean` | `true`/`false` | — |
| `Int` | signed integer | — |
| `Float` | IEEE 754 binary64 | — |
| `Decimal` | decimal number | — |
| `UUID` | UUID | — |
| `Date` | ISO 8601 date | — |
| `DateTime` | ISO 8601 datetime | — |
| `Bytes` | binary data | — |
| `Unit` | no value | only output or first argument of `Result<Unit,E>` |
| `List<T>` | ordered list | `T` is not `Unit` |
| `Map<K,V>` | map | `K` is `String`, `Int`, or `UUID`; `V` is not `Unit` |
| `Result<T,E>` | success `T` or error `E` | `T` can be `Unit`; `E` cannot |
| `Optional<T>` | value or absence | `T` is not `Unit` |

- `Any` and `Unknown` do not exist in 0.2.
- `null` is permitted only where `Optional<T>` is expected.
- No implicit numeric conversion; `Int` is not assignable to `Decimal`.
- `Unit` cannot be used as an input, field, `List` element, `Map` key/value, or `Optional` argument; it is permitted as an output and as the first argument of `Result<Unit,E>`.

### 6.3 Type Declarations

Alias:

```yaml
types:
  - id: TaskId
    type: UUID
```

Enum:

```yaml
types:
  - id: Status
    enum:
      - todo
      - doing
      - done
```

- Every type declaration has an `id` and exactly one of `type` or `enum`.
- Alias `type` MUST be an explicit string; inference is not permitted in alias declarations.
- Enums must have at least one value; values are snake_case strings, unique within the enum.
- Alias cycles are errors, including indirect cycles.
- An alias is transparent and expands; an enum is a nominal type.
- An alias must not reference `Unit` or `null`.
- Enum values must not be identical to built-in types or reserved words.
- Type declarations may not have unknown fields or additional metadata in 0.2.

### 6.4 Classes

```yaml
classes:
  - id: Task
    properties:
      id: TaskId
      title: String
      status: Status
```

- Property names are snake_case.
- Property values are type expressions or inference objects from §6.6; `Unit` is not permitted.
- `properties` MAY be omitted; then the class has no properties.
- Duplicate property names are an error; property order has no semantic meaning.
- Classes are nominal; inheritance is not part of 0.2.
- Recursive classes are permitted through generic containers (`Optional`, `List`, `Map`, `Result`); direct recursion without indirection is an error.
- Direct recursion is detected on the class graph where edges exist only for property types that are not within a generic container.

### 6.5 Functions and Interfaces

Function:

```yaml
functions:
  - id: create_task
    input:
      title: String
    output:
      type: Task
```

Interface:

```yaml
interface:
  id: TaskService
  version: "1.0.0"

  methods:
    - id: create_task
      input:
        title: String
      output:
        type: UUID
```

- `input` MAY be omitted; then the function or method has no parameters. If present, it must be a mapping (can be `{}`); parameter names are snake_case and unique.
- A parameter cannot be `Unit`; inference objects are permitted.
- `output` is mandatory and contains exactly `type`; `type` is a type expression string, without an inference object.
- `output.type` can be `Unit`.
- A method has an `id` in snake_case; methods are unique within an interface.
- An interface has an `id` and `version`; `version` is an exact semver version, not a range.
- `methods` MAY be omitted or empty; then the interface is a marker without methods.
- When an interface is declared in the `interfaces` list of a project or module, its ID enters the scope of that document.
- An interface document and an inline interface use the same shape; only the envelope differs.
- An interface document can reference types from the project scope.
- In the example, `Task` is defined in the same scope; a standalone interface document uses built-in types or qualified references.
- Interface compatibility and `implements` rules are out of scope for 0.2.
- `errors` and effects are out of scope for 0.2.

### 6.6 Inference and Unresolved

Explicit type is a string:

```yaml
input:
  user_id: UUID
```

Proposed type is an object with mandatory `origin: inferred`:

```yaml
input:
  user_id:
    origin: inferred
    type: UUID
    confidence: 0.95
    status: proposed
```

Undefined type is an object with mandatory `origin: unresolved`; `type` is omitted:

```yaml
input:
  user_id:
    origin: unresolved
    reason: "Target type is not known yet."
```

Rules:

- A type object MUST have an `origin`.
- `origin: inferred` requires `type`; `status` MAY be `proposed` or `approved`, and defaults to `proposed`.
- `origin: unresolved` requires `reason` and MUST NOT have `type`, `status`, or `confidence`.
- `type` in an inferred object is a type expression string, not a nested inference object.
- `confidence` is a number in the range `0.0`–`1.0` and is informative; it is permitted only with `origin: inferred`.
- `status` is permitted only with `origin: inferred`; `reason` only with `origin: unresolved`.
- `proposed` inferred types must not be used for codegen; in 0.2, validation gives a warning.
- `approved` inferred types behave as explicit types.
- Explicit types have priority; inference must not change an explicit type.
- `unresolved` is not assignable to any type and blocks codegen.
- Inference objects are permitted only as values in `input` mappings and class `properties`; they are not permitted in `types` declarations, enums, `output.type`, or as generic arguments.
- Inference objects may not have unknown fields.
- A `metadata` block with `author`/`status` is not part of 0.2; only `origin`/`status` on the type is used.

### 6.7 Assignability

After alias expansion:

- `T` is assignable to `T`.
- `T` is assignable to `Optional<T>`.
- `Optional<T>` is assignable to `Optional<U>` if `T` is assignable to `U`.
- `T` is assignable to `T | U`.
- `T | U` is assignable to `V` if both `T` and `U` are assignable to `V`.
- `List<T>` is invariant: `List<A>` is not assignable to `List<B>` unless `A` is identical to `B`.
- `Map<K,V>` is invariant.
- `Result<T,E>` is covariant in `T` and `E`.
- Classes and enums are nominal; type identity is the name, not the structure.
- `Unit` is not assignable to any other type.
- `null` is assignable only to `Optional<T>`.
- No implicit conversions.
- in 0.2, there are no expressions, so assignability is used only for validating declarations; expression checks are part of 0.3.

## 7. Validation in 0.2

### 7.1 Phases

1. **Syntax** — YAML subset and parsing.
2. **Schema** — envelope, permitted fields, ID formats, mandatory fields; JSON Schema `schema/sdl-0.2.schema.json`.
3. **Semantic** — references, scope, imports, types, assignability.

The reference validator `tools/validate_0_2.py` executes all three phases and emits a report as in §7.2. It is a conformance runner, not a production parser. JSON Schema cannot check the YAML subset, duplicate keys, anchors, multi-document files, import paths, or semantic rules. These steps must be performed before or after schema validation, per §2.

### 7.2 Diagnostics

The following block is the output of the validation tool, not an SDL document:

```yaml
validation:
  status: failed
  diagnostics:
    - phase: semantic
      severity: error
      code: SDL-E401
      message: Unknown type reference.
      location:
        file: modules/tasks.sdl.yaml
        path: /module/classes/0/properties/status
        line: 18
        column: 15
```

- `status` is `passed` or `failed`.
- `status` is `failed` if at least one `error` exists; `warning` and `info` do not change the status.
- `diagnostics` is a list; it can be empty only when status is `passed`.
- `severity` is `error`, `warning`, or `info`.
- `phase` is `syntax`, `schema`, or `semantic`.
- `code` is stable; codes are not recycled.
- `message` is a non-empty string.
- `location.file` is relative to the project root.
- `location.path` is a JSON Pointer to the node; empty string denotes the root.
- `location.line` and `location.column` are positive integers.
- `validation`, `diagnostics`, diagnostic, and `location` permit only fields from §3.3.
- Diagnostics are sorted deterministically: `file`, `line`, `column`, `code`.

### 7.3 Code Registry

| Code | Meaning |
| --- | --- |
| `SDL-E100` | YAML parse error |
| `SDL-E101` | Duplicate mapping key |
| `SDL-E102` | Forbidden YAML feature |
| `SDL-E103` | Depth/size limit exceeded |
| `SDL-E200` | Invalid envelope |
| `SDL-E201` | Unknown `kind` |
| `SDL-E202` | Missing or multiple root keys |
| `SDL-E203` | Undefined field |
| `SDL-E204` | Missing mandatory field |
| `SDL-E205` | Invalid field type or value |
| `SDL-E210` | Invalid ID format |
| `SDL-E211` | Duplicate ID in scope |
| `SDL-E212` | Unknown reference |
| `SDL-E213` | Forbidden name shadowing |
| `SDL-E220` | Invalid semver version/range |
| `SDL-E300` | Import path outside root or invalid path |
| `SDL-E301` | Cyclic import |
| `SDL-E302` | Unknown module or file not found |
| `SDL-E303` | Duplicate import |
| `SDL-E400` | Invalid type expression |
| `SDL-E401` | Unknown type |
| `SDL-E402` | Cyclic alias |
| `SDL-E403` | Invalid assignability |
| `SDL-E404` | `unresolved` type in codegen (reserved for 0.3) |
| `SDL-E405` | Forbidden use of `Unit` |
| `SDL-E406` | Invalid arity or generic argument |
| `SDL-E407` | Invalid inference object |
| `SDL-E408` | Invalid type declaration |
| `SDL-E410` | Unapproved inference in codegen (reserved for 0.3) |
| `SDL-W100` | Unapproved inference in validation |
| `SDL-W101` | `unresolved` type in validation |

Codes `SDL-E404` and `SDL-E410` are reserved; the 0.2 validator does not emit them because codegen is not part of 0.2.

### 7.4 Exit Codes

- `0` — valid.
- `1` — validation errors.
- `2` — tool usage error or I/O.
- `3` — internal parser/validator error.

## 8. Conformance Examples

### 8.1 Valid Project

```yaml
sdl: "0.2"
kind: project

project:
  id: task_manager
  version: "1.0.0"
  mode: structural

  imports:
    - path: modules/users.sdl.yaml
    - path: modules/tasks.sdl.yaml
    - path: interfaces/task_service.sdl.yaml
```

### 8.2 Valid Module

```yaml
sdl: "0.2"
kind: module

module:
  id: tasks
  mode: structural

  imports:
    - module: users

  types:
    - id: TaskId
      type: UUID

    - id: Status
      enum:
        - todo
        - doing
        - done

  classes:
    - id: Task
      properties:
        id: TaskId
        title: String
        status: Status

  functions:
    - id: create_task
      input:
        title: String
      output:
        type: Task
```

### 8.3 Valid Interface

```yaml
sdl: "0.2"
kind: interface

interface:
  id: TaskService
  version: "1.0.0"

  methods:
    - id: create_task
      input:
        title: String
      output:
        type: UUID
```

### 8.4 Invalid Examples

- `sdl: 0.2` — version not quoted.
- Two identical keys in the same mapping.
- `modules:` instead of `imports:`.
- `name: Task` instead of `id: Task`.
- `output: Task` instead of `output: {type: Task}`.
- `version: 1.0` instead of `"1.0.0"`.
- `tasks.Task` instead of `tasks::Task` or a structured reference.
- Alias cycle `A -> B -> A`.
- `origin: unresolved` without `reason`.
- `origin: inferred` without `type`.
- `type: unresolved` as a replacement for `origin: unresolved`.
- `Unit` as an input, field, or generic argument.

### 8.5 Machine-Verifiable Artifacts

- `schema/sdl-0.2.schema.json` — JSON Schema 2020-12 for `project`, `module`, `interface`, and `types` documents.
- `schema/sdl-0.2.validation.schema.json` — validation report schema; this is not an SDL document.
- `tools/validate_0_2.py` — reference validator and conformance runner for 0.2.
- `tools/sdl_yaml.py`, `tools/sdl_schema.py`, `tools/sdl_types.py`, `tools/sdl_semantics.py` — validator phases.
- `fixtures/0.2/cases.yaml` — conformance example manifest with expected codes.
- `fixtures/0.2/valid/` — examples that must pass schema and semantic validation.
- `fixtures/0.2/invalid/` — examples that must be rejected.

The validator is called as `python tools/validate_0_2.py --cases fixtures/0.2/cases.yaml`. JSON Schema does not replace the semantic validator; duplicate keys, YAML subset, import paths, alias cycles, and generic arity are checked separately. The validator is a reference implementation, not a production parser.

## 9. Migration from 0.1

| 0.1 | 0.2 |
| --- | --- |
| `sdl: "0.1"` | `sdl: "0.2"` |
| `modules:` in project | `imports:` with `path` |
| `name:` for declarations | `id:` |
| `output: Decimal` | `output: {type: Decimal}` |
| `version: 1.0` | `version: "1.0.0"` |
| `module.Class` | `module::Class` or structured reference |
| `language` inside `source` | `language` at implementation level (0.3) |
| `currency: string` | `currency: String` |
| `requirements`/`constraints` | out of scope for 0.2 |
| `implementation`/`build` kind | reserved for 0.3 |
| `extensions` | reserved for 0.3 |

## 10. Next Layer

0.3 should add:

1. flow semantics and data-flow;
2. interface compatibility and `implements`;
3. implementations, bindings, backend, and build;
4. LLM proposal protocol with base revision and patch payload;
5. validation phases four and five (consistency and backend);
6. requirements/constraints and extensions;
7. extension of JSON Schema to new `kind`s and canonical IR.

JSON Schema for 0.2, conformance examples, and the reference validator are already part of the 0.2 artifacts. 0.3 extends the same tools to new `kind`s; it does not replace them.
