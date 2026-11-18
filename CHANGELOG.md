# Changelog

All notable changes to the SDL repository. The format follows
[Keep a Changelog](https://keepachangelog.com/).

The project follows the core versions defined in `spec/VERSIONING.md`. The
version in `VERSION` is the current core version of the working tree.

---

## [Unreleased]

### Changed

* The breaking-change policy of section 4.3 is now as precise as the contract
  of section 5.2. A signature change is breaking only when a client written
  against the old signature no longer works against the new one: a removed
  parameter, a parameter that accepts less (contravariance), a new parameter
  that is not `Optional`, or an output that is no longer assignable to what the
  client expected (covariance). A change that only widens the inputs, only
  narrows the output, or only adds optional parameters no longer requires a
  version increment. The rule is applied both to the policy check
  (`sdl/proposal/policy.py`) and to the project version of a merge
  (`sdl/proposal/engine.py`), so the two agree.
* The form of the migration plan of section 4.3.1 is defined: a `migration`
  list on the proposal document, each entry naming the changed `type` and the
  `documents` the plan covers. The plan is checked against the documents that
  depend on the type, and a plan that omits one, or that names a document
  outside the project, is refused (`SDL-E602`).
* The resolver now records whether a parameter or a field is `Optional<T>`, so
  a flow does not have to map a parameter the caller may omit.
* An alias is transparent (section 9.3.2) wherever the assignability rules of
  section 6.7 are applied. The type checker of a flow, and the breaking-change
  policy of section 4.3, expand an alias to its base type before comparing, so
  a change that only writes a type through its alias is neither a type mismatch
  nor a breaking change. `sdl/types/assignability.py` gains `expand_aliases`,
  and `assignable_expressions` and `is_optional_expression` take an optional
  alias map. The policy and the version of a merge both use it, so the two
  agree.
* The generated runtime of the Python back end resolves a step that names an
  interface method (`Interface::method`) through the bindings table, as section
  6.2 requires and as the interpreter already did. The generated dispatcher had
  looked the whole name up directly, which only worked for a module function.

### Added

* The **NodeJS/TypeScript back end** (`sdl/backends/codegen/typescript_gen.py`),
  selected by `backend.target: nodejs`. It generates the types as interfaces,
  an SDL enum as a union type and a `const` object, the interfaces as
  interfaces whose methods return a `Promise`, the flows as async functions
  with an explicit data flow, and a small runtime (a registry and a dispatcher
  that resolves `Interface::method` through the bindings, as section 6.2
  requires). The output is **erasable** TypeScript, so `node` runs it by
  stripping the types. `sdl.backends.codegen_for` selects the back end of a
  project, and `sdl/semantics/core10.py` now knows that `nodejs` hosts
  TypeScript and JavaScript.
* `sdl/flow/expressions.py` — `render_typescript`, the TypeScript counterpart
  of `render_python`, so a condition is parsed and rendered rather than copied.
* `tests/test_codegen.py` — checks of the NodeJS back end: every generated file
  runs under Node, the generation is deterministic, a condition is not copied
  as text, and the dispatcher resolves an interface method through the
  bindings. A new fixture, `tests/fixtures/typescript/`, exercises an enum, an
  alias, `Optional`, `List`, `Map`, a condition and an error strategy.
* The **Go back end** (`sdl/backends/codegen/go_gen.py`), selected by
  `backend.target: go`. It generates the types as structs, an SDL enum as a
  string type with constants, the interfaces as Go interfaces, the flows as
  functions with an explicit data flow, and a small runtime (a registry, a
  dispatcher that resolves `Interface::method` through the bindings by
  reflection, the `Field`/`Truth`/`Compare` helpers a condition needs, and a
  `Result` type). The inputs of a method travel as a `map[string]any` and the
  Flow State is a `map[string]any`, because Go has no keyword arguments and no
  dynamic typing. The generated project uses nothing but the standard library,
  and `sdl/semantics/core10.py` now knows that `go` hosts Go.
* `sdl/flow/expressions.py` — `render_go`, the Go counterpart of
  `render_python`, so a condition is parsed and rendered rather than copied.
* `tests/test_codegen.py` — checks of the Go back end: the generation is
  deterministic, every generated project builds and vets with `go build ./...`
  and `go vet ./...`, a condition is not copied as text, and a generated flow
  calls the bound implementation at run time through the registry. The checks
  that need the Go toolchain are skipped, with a printed note, when no `go` is
  on the `PATH`.
* `sdl/types/assignability.py` — `assignable_expressions` and
  `is_optional_expression`, the rules of section 6.7 applied to the type
  *expressions* of the documents, so the proposal policy can decide a
  signature change before the project is compiled.
* Recipes: adding an optional parameter, a type change with a migration plan,
  and a type change without one, with too narrow a plan, and with a document
  that does not exist; and pointing a `nodejs` back end at a TypeScript
  implementation (`tests/recipes.py`).
* Recipes for the referential phase of section 8.4: an `add` that binds an
  interface or an implementation the proposal does not declare, a `replace`
  that points a binding at an implementation that does not exist, and an `add`
  whose type expressions do not resolve — a method input, a method output, a
  field, and the output of an existing method. One accepted recipe proves the
  other half of the rule: a name the proposal declares itself may be referenced
  in the same proposal. Three more touch other domains of a project: an import
  of a document that does not exist (`SDL-E302`), an enum type (accepted, a
  MINOR change), and a second binding for an interface that already has one
  (`SDL-E603`). Three more fix the transparency of an alias: an alias used as
  the type of a flow input, a parameter changed to an alias of its own type
  (both accepted), and a parameter changed to an alias of another type (still a
  breaking change, `SDL-E602`). `tests/recipes.py` is now 99 recipes: a large
  batch covering error handling and retry (section 3.3.1), flow outputs and
  state (sections 2.2.1 and 2.3.3), the type-expression rules inherited from
  Core 0.2 (section 4.2), the interface and implementation rules (sections 5
  and 6), invariants (section 4.2.1), bindings (section 6.2), identifiers
  (section 4.3), imports (section 4.1), the schema, the back end (section 7)
  and the protocol itself (section 8), plus pointing a `go` back end at a Go
  implementation (accepted) and at a TypeScript one (`SDL-E606`).
* `tests/test_assignability.py` — the expression-level rules, now including the
  expansion of an alias, of an alias of an `Optional`, and of an alias cycle.

### Fixed

* A type expression that is a union or a nested generic keeps its members in
  both back ends. The resolver computed the shape of a field, of a flow input
  and of a `type` alias from the *resolved identifier*, which is a bare name, so
  `List<Optional<String>>` became `List` (or `any[]`) and `String | Int` became
  the first member. The shape is now derived from the expression the document
  wrote (`sdl/lowering/resolver.py`), and both generators render it
  (`sdl/backends/codegen/python_gen.py`, `.../typescript_gen.py`). A field of
  type `Optional<T>` is now marked optional, which the TypeScript interface
  writes as `field?: T | null`. The resolver stays repeatable: a second pass
  over the same graph reproduces it byte for byte.
* The code generation test is now 39 checks: it covers a union, a nested
  generic and a generic flow input in every back end, and the Go back end in
  full. The pipeline integration test gained a check that the resolver is
  repeatable (`tests/test_integration.py`).
* A merged document keeps its comments and its blank lines. The data of a
  document carries neither — the YAML parser drops them — so a document that a
  proposal changed used to be written back without them. They are now read out
  of the original text and put back around the nodes they belong to
  (`sdl/yaml/layout.py`, called from `SourceDocument.render`). A comment or a
  blank line whose node the proposal removed is dropped; a comment on a list
  element follows the element by its `id` rather than by its position, so
  removing a neighbour does not move it. A `#` inside a multi-line scalar is
  not a comment. The indentation and the quoting are still normalised, because
  the document is re-serialised from the data, and re-attaching the layout is
  idempotent, so repeated merges do not accumulate blank lines.
* `LLM_CONTRACT.md` no longer lists the form of a migration plan as undefined.
  The plan of section 4.3.1 is defined and enforced, so the limitation was
  stale; the contract now states the rule among the ones the engine already
  enforces.
* The referential phase of section 8.4 now checks every reference a patch
  writes, not only the ones at the top of its value. Two things were wrong in
  `sdl/proposal/references.py`. The `interface` and the `implementation` of a
  binding were counted as names the proposal *introduces*, so a proposal that
  bound an interface it does not declare passed phase two and was caught only
  by the simulation. And a reference nested in a value — a method input, a
  field type, an `outputs.type` — was not looked at, so the simulation caught
  it instead. Both are `SDL-E702` in the referential phase, which is where the
  specification puts them.
* A Core 1.0 document is now checked against the type-expression rules it
  inherits from Core 0.2 (section 4.2), whatever shape it is written in. The
  checker only looked at a `types` document whose root was a *list*; a Core 1.0
  `types` document is a *mapping* (`types:` then the declarations), so a `Unit`
  field (`SDL-E405`), a bare generic (`SDL-E406`) and a `Map` key that is not
  `String`, `Int` or `UUID` (`SDL-E406`) escaped the check whenever no flow read
  the type. `sdl/semantics/core10.py` now walks every type expression a
  document can carry — a field, an alias, a method input, a method output, a
  flow input and a flow output — and applies the arity, `Map` key and `Unit`
  rules there.
* An invariant of section 4.2.1 is now parsed. The specification says the 1.0
  validator checks that an invariant is syntactically correct; the checker did
  not look at the list at all, so `invariants: ["name >>"]` was accepted. It is
  now parsed by the condition grammar and refused as `SDL-E504` when it is not
  an expression.
* The version of a binding is now checked (section 6.2, rule two). The binding
  of `examples/hello` names an exact version; the checker never compared it to
  the version the interface declares, so `version: 9.9.9` was accepted. It is
  now `SDL-E603` when the two differ. A recipe that changed an interface
  version and left its binding behind was itself stale, and was corrected.

### Removed from the known gaps

* a project whose `backend.target` is `nodejs` now builds, so `examples/hero_site`
  compiles to TypeScript;
* a project whose `backend.target` is `go` now builds, so a project compiles to
  Go;
* the form of the migration plan is now defined and checked;
* the policy no longer requires a version increment for a signature change that
  does not break the contract;
* a union or a nested generic keeps its members in the generated source, in
  both back ends;
* a merged document keeps the comments and the blank lines of the original, so
  a change to a type no longer erases the notes and the grouping a human wrote
  around it;
* the type-expression rules of Core 0.2 apply to every shape of a Core 1.0
  document, not only to a `types` document with a list root;
* an invariant is parsed, so one that is not an expression is refused;
* the version of a binding is checked against the interface it names.

---

## [1.0] — consolidation

The core was renamed from 0.3 to 1.0 during the 0.3 development cycle, but the
rename never reached the filename, the envelope string or the section headings.
This release completes the rename and rebuilds the repository around a single,
explicitly versioned layout.

### Added

* `spec/` — the current specification (`sdl-core-1.0.md`), the changelog
  against Core 0.3 (`sdl-core-1.0-changelog.md`), and the version policy
  (`VERSIONING.md`) with the migration tables and the errata against the
  superseded specifications.
* `VERSION` — the single source of truth for the core version.
* `sdl/schema/sdl-1.0.schema.json` — JSON Schema 2020-12 for Core 1.0
  documents: `project`, `module`, `interface`, `types`, `flow`,
  `implementation` and `proposal`.
* `sdl/schema/sdl-1.0.validation.schema.json` — the shape of the validation
  report.
* `sdl/semantics/core10.py` — Core 1.0 document semantics: scope and duplicate
  identifiers, name shadowing, import resolution, type resolution, alias
  cycles, compound type recursion, the flow data-flow rules, the condition
  expression grammar, the error handling and retry rules, and the binding
  rules.
* `sdl/diagnostics.py` — the single diagnostic registry for every layer, with
  the `SDL-Exxx` code catalogue and the reserved code list.
* `conformance/1.0/` — the Core 1.0 conformance suite: 31 cases covering the
  envelope, the schema, the YAML subset, the scope rules, the flow rules and
  the binding rules.
* `tests/recipes.py` and `tests/test_recipes.py` — the recipes of the
  proposal protocol: 24 complete changes, each with the outcome the
  specification demands. A recipe that fails is a hole of the toolchain, and
  a recipe that passes for the wrong reason is a hole of the test.
* `tests/test_verification.py` — the Semantic Firewall self-check, rewritten
  to run under pytest and standalone.
* `tests/test_package.py` — structural invariants: the version, the layers, the
  packaged schemas, the diagnostic registry and the envelope examples of the
  specification.
* `tests/test_integration.py` — the end to end pipeline test: documents in,
  canonical IR out.
* `tests/run_all.py` — a single command that runs every check.
* `pyproject.toml` — packaging, with the version read from `VERSION`.

### The pipeline

The chain that was missing now exists and runs end to end:

```
python -m sdl build examples/payment_system/project.sdl.yaml
```

* `sdl/compiler.py` — the orchestrator: validate, parse, lower, resolve,
  firewall, IR.
* `sdl/parser/ast.py` — a lossless AST for Core 1.0, with the location of
  every element. Every document kind is represented: project, module,
  interface, types, flow, implementation and proposal.
* `sdl/parser/yaml_parser.py` — layer 3, built on top of the YAML subset, so
  the subset rules are inherited rather than reimplemented.
* `sdl/lowering/identity.py` — deterministic identifiers. A symbol identifier
  is derived from its qualified name, never from a counter or a random
  source.
* `sdl/lowering/symbol_builder.py` — the lowering. Nothing of the document is
  lost: the constraints, the policy, the backend, the builds and the bindings
  of a project, the methods and the invariants of an interface, the outputs
  and the output mapping of a flow, the error handling and the retry policy of
  a step, and the source location of an implementation all reach the IR.
* `sdl/lowering/resolver.py` — reference resolution. It is **repeatable**: it
  removes the reference edges it owns and derives them again, which is what
  lets the firewall notice a proposal that broke a reference.
* `sdl/ir/serialization.py` — the canonical JSON form of the IR. Symbols are
  ordered by qualified name, edges by kind and endpoints, and every mapping is
  written with sorted keys, so two builds can be compared byte for byte.
* `sdl/cli/build.py` and `sdl/cli/__main__.py` — the `build` command and the
  `python -m sdl` entry point.

### The Flow State

The Flow State now holds every variable the flow can read: the declared inputs
and the variables the steps create through their `output_map`. The type of a
created variable is derived from what the called method returns — the whole
result for `result`, or the type of the field for `result.field`.

### The Semantic Firewall

The firewall now closes the loop that was open.

* `sdl/proposal/engine.py` derives the references of the patched graph again
  after the patches are applied. A proposal that points a call at a symbol
  that does not exist, or that breaks a type, now produces an unresolved
  reference, is rejected with `SDL-E511` or `SDL-E501`, and the production IR
  is never touched.
* `sdl/lowering/resolver.py` owns its edges precisely. It removes and
  rebuilds the reference edges it derives, and leaves the structural ones
  alone. The `IMPLEMENTS` edge of a method belongs to the interface, the one
  of an implementation belongs to the resolver.
* `sdl/validation/type_checker.py` checks the Flow State. A step that reads a
  variable which does not exist when the step runs is rejected with
  `SDL-E502`, whatever the types say.
* `sdl/proposal/patcher.py` restricts what a proposal may change. The
  identity of a symbol, its kind, and the qualified name other symbols refer
  to it by are never patchable. Before this, a patch could set any attribute
  of any symbol, which is a hole in an untrusted input path.

### The proposal protocol

The protocol now matches specification sections 4.3, 8.2, 8.3, 8.4 and 8.5,
and it operates on the **documents** of a project rather than on the compiled
IR. The specification is the single source of truth, so a change has to start
there: phase four of section 8.4 builds a *virtual* version of the
specification, and section 8.5 applies the patches to the primary source.

* `sdl/documents.py` — the document set of a project: the root document and
  everything it imports, with the raw text of each document so that a document
  that is not changed is written back byte for byte.
* `sdl/proposal/models.py` — the envelope and the patch model of section 8.2
  and 8.3: `target`, `action`, `value`.
* `sdl/proposal/paths.py` — the target syntax. `<kind>.<id>.<path>` or
  `<file>:<path>`, with the segments `.name`, `[name]` and `[3]`.
* `sdl/proposal/document_patcher.py` — applies the patches to a shadow copy
  of the document set.
* `sdl/proposal/references.py` — phase two, the referential validation: every
  new name a patch introduces must exist in the specification or be
  introduced by the same proposal.
* `sdl/proposal/policy.py` — phase three, the policy of section 4.3:
  `forbidden_id_changes`, `disallow_breaking_changes` and
  `require_migration_for_type_change`.
* `sdl/proposal/engine.py` — the phases, the approval of section 8.5 and the
  merge. The merge writes the changed documents back and increments the
  project version according to semver.
* `sdl/cli/propose.py` — the `propose` command.

The IR level patcher and the IR level shadow graph were removed. They are
replaced by the shadow copy of the document set, and by the semantic
simulation, which rebuilds the canonical IR from the virtual specification and
runs the whole pipeline on it.

### The Python back end

The back end was a prototype that produced an empty function. It is now a real
generator.

* `sdl/flow/expressions.py` — the condition grammar of specification section
  3.2.1, as a tree. The back end renders the tree, so a condition can never
  be injected into the generated source as raw text. The parser also supports
  the dotted state paths the specification asks for, which the earlier parser
  rejected.
* `sdl/backends/codegen/python_gen.py` — the generator. It produces the
  types as dataclasses, the interfaces as protocols, the implementations and
  the module functions as stubs, the flows as async functions with an explicit
  data flow, and the runtime the flows need: a registry that resolves a name
  to an implementation and a dispatcher that calls it.
* The data flow of a flow is explicit. A step reads the state and writes the
  state; the output mapping of a step binds the whole result or one of its
  fields, as section 2.3.2 defines.
* The error strategies of section 3.3.1 all reach the source: `fail`,
  `ignore`, `retry` with its policy, and `goto` to another step.
* The bindings of section 6.2 reach the registry, so a flow never imports a
  concrete implementation.
* The mandatory outputs of section 3.3.2 are checked before the flow
  returns.

The generator was rewritten from scratch: the earlier version read metadata
that the lowering never wrote, compared edge kinds by their number, and
emitted a condition as raw text.

### The runtime

The runtime of the `execute` mode exists now. Specification section 7.1: the
runtime *directly executes flows and calls implementations via dynamic
binding*.

* `sdl/backends/runtime/registry.py` — the registry of the callables. It is
  filled from the specification, by importing the source file an
  implementation declares, and it can be filled by hand.
* `sdl/backends/runtime/state.py` — reading the Flow State and the output of
  a step, as sections 2.3.1 and 2.3.2 define them.
* `sdl/backends/runtime/conditions.py` — evaluating the condition of a step.
  The condition is parsed into a tree and evaluated, never evaluated as text.
* `sdl/backends/runtime/interpreter.py` — the execution of a flow: the order of
  the steps, the conditions, the explicit data flow, the error strategies of
  section 3.3.1 and the mandatory outputs of section 3.3.2.
* `sdl/cli/run.py` — the `run` command.

The dynamic binding of section 6.2 is the part worth naming: when a step calls
`Checker::check`, the runtime resolves the interface through the bindings
table and calls the method of the implementation the project bound to it. The
registry holds the implementations, not the methods.

### The compatibility engine

The last layer of the specification is implemented.

* `sdl/types/assignability.py` — the assignability rules of Core 0.2 section
  6.7, exactly as they are written there: `T` to `T`, `T` to `Optional<T>`,
  `Optional<T>` to `Optional<U>`, `T` to `T | U`, `T | U` to `V` when both
  are, `List` and `Map` invariant, `Result` covariant, classes and enums
  nominal, `Unit` assignable to nothing, and no implicit conversions.
* `sdl/types/semver.py` — the version ranges of Core 0.2 section 4.5.
* `sdl/backends/python_signature.py` — reading the signatures of a Python
  class with the standard library parser. The validator parses the code of an
  implementation, it never runs it.
* `sdl/validation/compatibility.py` — the checks of specification section 5:
  the completeness of 5.3.1, the signature compatibility of 5.2 with the
  output covariance and the input contravariance, and the version
  compatibility of 5.4.

The canonical IR keeps the shape of a type expression, not only the
identifier of the type it names, because the assignability rules treat a
union, an optional and a generic differently. A type reference now holds the
references of its arguments.

* The semantic simulation of a proposal did not copy the code of the
  implementations, so the contracts of section 5 were never checked during a
  proposal. A change that broke an implementation was accepted.
* An element of a list could only be addressed by its `id`, so the target of
  specification section 8.2, `project.bindings[PaymentProvider]`, did not work.
  An element is now named by its `id`, `name`, `interface` or `key`.
* The flow of the runtime could not have an input called `name`, because the
  parameter of `run_flow` had the same name. The name of the flow is now
  positional only.
* The registry held the class of an implementation instead of an instance, so
  the call failed with a missing `self`. A class is now instantiated the
  first time it is needed.
* The runtime rejected a flow whose input was called `name`, because the
  method still referred to the old name of its parameter.

### Fixed by the firewall and the back end

* A proposal that broke a reference was accepted and merged into the
  production IR. The reference checker only inspected edges, and the resolver
  only ran during lowering, so a `call_target` pointing at nothing was
  invisible to the firewall. The behaviour was pinned by a test that asserted
  the defect; the test is now inverted.
* A module could not import another module. The parser read only the `path`
  form of an import, so the `module` form of the Core 0.2 grammar was
  silently dropped, and the `DEPENDS_ON` relation was therefore never built.
  The architecture checker could not see a layering violation.
* The resolver lost its body during a refactoring, which made every proposal
  fail with an internal error rather than with a diagnostic. A test that
  passed for the wrong reason exposed it.
* The `call_target` of a flow step and the return type of a method were
  resolved as names even when they were already the identifier of a symbol,
  which broke a graph that was not built by the lowering stage.
* The test suite wrote to the documents of an example in the repository. The
  runner now verifies that the examples are unchanged, and every test that
  merges a proposal works on a temporary copy.
* Writing a document back lost the double quotes around a version, because a
  plain YAML scalar round trips as a plain scalar and the envelope requires a
  double quoted string. The dumper now keeps them.
* The canonical IR was **not deterministic**: symbol and edge identifiers were
  generated with `uuid4()`, so two builds of the same document produced
  different graphs. They are now derived from the qualified name.
* The condition grammar of the specification never accepted a dotted state
  path, even though section 3.2.1 names `status.is_valid` as an example. A
  valid condition was therefore rejected as malformed.
* The lowering dropped the constraints, the policy, the backend, the builds
  and the bindings of a project, the methods and the invariants of an
  interface, the outputs of a flow, and the error handling of a step.
* The type checker compared the wrong type kind: it tested for `SCALAR` where
  it meant `COMPOUND`, so it never looked at the fields of a compound type.
* The architecture checker read the forbidden imports from the wrong place
  and therefore never saw the constraints of a project.
* Two of the four `TYPE_MISMATCH` diagnostics still carried the old free-form
  rule identifier instead of `SDL-E501`.
* `examples/payment_system` called `payment_helper::build_request`, which did
  not exist anywhere in the project. The module `payment_helper` was added,
  and the flow now resolves to a real function.
* The Core 1.0 `types` document uses a mapping keyed by type id, and the
  parser could not read it at all.
* The back end emitted the `else` of a condition and the advance of a step at
  the wrong indentation, so the generated source was not valid Python.
* A step with the `goto` strategy did not advance when it succeeded, which
  made the generated flow loop forever.
* The bindings of a project were never registered in the generated registry,
  because the generator looked the implementation up by identifier where it
  had to look it up by name.
* The built-in types were generated as modules of their own, so a project
  without a single user type produced fourteen files of `string.py` and
  `boolean.py`.
* The variables a flow creates were generated as parameters of the flow,
  because the state of a flow holds the inputs and the created variables
  alike.

### Fixed by the recipes

The recipes of `tests/recipes.py` are small, complete changes that exercise
one rule each. Writing them found the defects below. Every one of them is
covered by a recipe or a regression test now.

* **The rules of `Optional` never fired.** The assignability engine decided
  that a type was optional by comparing the base of a generic with the
  *string* `"Optional"`, but the base of a generic is the identifier of the
  type, which is a digest. An implementation that accepted `Optional[str]`
  was therefore refused as incompatible, even though it accepts everything
  the contract sends. The unit test of the rule used identifiers that were
  the names of the types, so it passed for the wrong reason; the fixture now
  uses the identifiers the lowering produces.
* **`add` replaced a list instead of extending it.** The action `add` of
  section 8.3 resolved the parent of the target and wrote the value into it,
  so `project.bindings` was replaced by a single binding instead of
  receiving one. The example of section 8.2,
  `module.payment_logic.imports`, could not work.
* **The output mapping of a flow was never checked.** Section 2.3.3 was
  applied to the input mapping of a step only. A flow could promise an
  output of a type the state does not hold, and could read a field that does
  not exist.
* **A call without a binding was accepted.** Section 6.2, rule three, says a
  call is resolved through the bindings table, but nothing checked that the
  table had an entry for the interface a flow calls. A proposal could
  remove the binding of an interface and leave a project that cannot run.
* **A back end the toolchain cannot produce was built anyway.** The build
  always generated Python, whatever the `backend.target` of the project said.
  The build now refuses a target it cannot produce, with `SDL-E605`.
* **The target of a build was not compared with the language of the
  implementations.** Section 7.2 requires the target to be compatible with
  the languages the build uses. A Python build could be bound to an
  implementation written in another language.
* **A breaking change did not need a major version.** The policy of section
  4.3 accepts any version increment, but section 5.4 requires the MAJOR
  version of the interface. A signature change with a patch version was
  accepted.
* **The removal of a contract was a minor change.** A method that
  disappeared from an interface, and an interface or a type that
  disappeared, break the contract of every client, but the version of the
  project was incremented by a minor step.
* **A target that resolves to nothing was a policy failure.** Section 8.4
  orders the phases, and the referential validation comes before the policy
  check. The phase of the failure was wrong.
* **The referential phase could not see the references it was written to
  check.** A binding counts its `interface` and its `implementation` among the
  names it *introduces*, so a proposal that bound an interface it does not
  declare slipped past phase two. A reference nested in a value — a method
  input, a field type, an `outputs.type` — was never looked at at all. Both
  are `SDL-E702` in the referential phase now.
* **An alias was not transparent.** Section 9.3.2 says an alias is replaced by
  its base type. The type checker of a flow compared the *identifiers* of the
  state and of the parameter, so a flow input written through an alias of the
  type the method declares was refused with `SDL-E501`. The policy of section
  4.3 compared the *names* of the written expressions, so a parameter that only
  changed to an alias of its own type was refused as a breaking change with
  `SDL-E602`. Both apply the assignability rules of section 6.7 after alias
  expansion now.

### Hardened

The changes below do not alter the specification. They close holes in the
implementation and in the toolchain, and each one is covered by a test.

* **The compatibility check is fail closed.** An implementation that declares
  Python source the validator cannot read — the file is missing, the class is
  not there, or a parameter or return type has no annotation the reader
  understands — is now rejected with `SDL-E607` instead of being accepted
  without having looked at the code. A target in another language is out of
  scope of the reader and is not rejected. `sdl/backends/python_signature.py`
  never guesses a type: a default value no longer widens a parameter to
  `Optional`, and a method that declares `**kwargs` accepts the parameters the
  contract names.
* **The merge is a transaction.** `sdl/proposal/engine.py` writes the new text
  of every document to a temporary file first, replaces every target, and, if a
  replacement fails, restores the documents that were already replaced. A
  failed merge is `SDL-E705` and leaves no half merged document set.
* **A conflict is detected by identity, not by text.** Two patches that name
  the same element through different forms — `flow.sdl.yaml:version` and
  `flow.test_flow.version` — are now rejected with `SDL-E704`. The identity of
  a target is the document it selects plus its pointer.
* **The resolver keeps the arguments of a generic.** A parameter or a return
  type that was a generic or a union lost its arguments, so the compatibility
  engine compared the base type alone. The expression is now read before the
  resolved identifier overwrites it.
* **`propose --json`.** The `propose` command prints a machine readable
  verdict, and the project a proposal belongs to is found by parsing the
  `kind` of the envelope rather than by searching for the text `kind: project`.
* **A proposal that changes nothing does not move the version.** The version
  was incremented even when every patch was a no-op. The recipe *replace the
  implementation of an interface* was patching a value to itself and passing
  for that reason; it now adds a second implementation and moves the binding to
  it.
* **The `payment_system` example runs end to end.** It declared a module
  function and an implementation with no code, and its flow read
  `payment_result.success` from a `Result` that has no such field. The
  interface now returns `PaymentResponse`, the sources exist, and
  `python -m sdl run` executes the flow. The generic `Result` coverage moved
  to a dedicated compatibility fixture.
* **Continuous integration.** `.github/workflows/ci.yml` runs the whole suite
  on Python 3.10, 3.11 and 3.12.
* **`sdl.flow` ships in the wheel.** The subpackage was imported by the back
  end, the runtime and the semantic checks, but it was declared in neither the
  `packages` list of `pyproject.toml` nor with an `__init__.py`. Python treated
  the directory as a namespace package, so every check run from the working
  tree passed while a wheel omitted it. A package structure check now fails if
  a subpackage of `sdl` is not declared.

### Changed

* **The envelope version is now `1.0`.** Every Core 1.0 document declares  `sdl: "1.0"`. The rule that the envelope equals the core version is now
  written down in `spec/VERSIONING.md` §1 and in section 0 of the
  specification.
* **The Core 0.2 reference validator was integrated into the `sdl` package**
  as layers 0 to 2 instead of living in a separate `tools/` directory:

  | Before | Now |
  | :--- | :--- |
  | `tools/sdl_yaml.py` | `sdl/yaml/subset.py` |
  | `tools/sdl_common.py` | `sdl/diagnostics.py` |
  | `tools/sdl_types.py` | `sdl/types/expressions.py` |
  | `tools/sdl_schema.py` | `sdl/schema/envelope.py` |
  | `tools/sdl_semantics.py` | `sdl/semantics/scope.py` |
  | `tools/validate_0_2.py` | `python -m sdl.cli.validate` |
  | `schema/*.json` | `sdl/schema/*.json` |
  | `fixtures/0.2/` | `conformance/0.2/` |

  The rules are unchanged and the Core 0.2 conformance result is unchanged at
  30/30. The path deviations are recorded as errata in `spec/VERSIONING.md` §5.
* **The IR level firewall now reports `SDL-Exxx` codes** instead of free-form
  rule identifiers.
* **JSON Schema errors are reported precisely.** Conditional and `oneOf`
  failures are resolved to their most specific cause, so an undefined field is
  `SDL-E203` rather than a generic shape error.
* **The Core 1.0 schema uses conditional branches per document kind** instead
  of a single `oneOf` over the whole document, so the diagnostic points at the
  offending field.
* The example documents were renamed to the `.sdl.yaml` extension that Core
  0.2 §4 requires of every import, and their method identifiers were changed
  to snake_case as Core 0.2 §5 requires.
* `verification_suite.py` moved to `tests/test_verification.py`.

### Fixed by the consolidation

* The Core 0.3 envelope string was inconsistent with the Core 1.0 title.
* `examples/hero_site/interfaces.yaml` and `examples/hero_site/implementations.yaml`
  were multi-document files, which the Core 0.2 YAML subset forbids, and they
  duplicated the split `interface_content` / `interface_template` /
  `impl_content` / `impl_template` files that the project actually imports.
  They were removed.
* Both example flows declared `outputs` without an `output_mapping`, which
  Core 1.0 §2.2.1 makes mandatory. The mappings were added.
* `examples/payment_system` declared flow outputs that no type in the project
  could supply. The `PaymentResponse` type and the flow outputs were made
  consistent.

### Removed

* `verification_suite.py\`` — a stray duplicate with a backtick in the name.
* `verification_suite_gemmini.py` — a self-contained reimplementation that did
  not import the `sdl` package. Archived in `archive/legacy/`.
* `generated/` — the output of an LLM assisted transpiler. Every one of its 20
  Python files was syntactically invalid, because the markdown fences around
  the generated code were never stripped, and it carried 34 MB of
  `node_modules`. It will be regenerated once the code generator works.
* `New folder/ai-sdlc` — an unrelated third party repository that had been
  cloned into the working tree.
* `tools/` and the root `schema/` directory — merged into `sdl/`.

### Known gaps

These are unchanged by this release and are tracked in the status table of
`README.md`:

* a merged document is re-serialised, so its formatting is normalised
* the back end targets Python only; the `backend.target` of a project may
  name another language, which no back end implements yet
* the runtime resolves the source of an implementation from the file the
  specification declares; a module function is looked up in a Python module
  of the same name in the project root, because the specification does not
  say where the body of a module function lives

---

## [0.3] — never released

Superseded by 1.0 before release. The specification text is preserved in
`archive/specs/sdl-core-0.3.md`.

---

## [0.2] — language foundations

Superseded by 1.0, but its rules remain normative for everything Core 1.0
inherits. The specification text is preserved in
`archive/specs/sdl-core-0.2.md`, and the conformance suite that proves the
implementation still honours them lives in `conformance/0.2/`.

---

## [0.1] — initial draft

Superseded. Preserved in `archive/specs/sdl-core-0.1.md`.
