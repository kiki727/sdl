# Tests

## Running everything

```powershell
python tests/run_all.py
```

This runs, in order:

1. the Core 0.2 conformance suite — 30 cases
2. the Core 1.0 conformance suite — 31 cases
3. the proposal protocol self-check — 18 checks
4. the package structure check — 6 checks
5. the pipeline integration test — 18 checks
6. the code generation test — 24 checks
7. the SDL runtime test — 10 checks
8. the assignability test — 17 checks
9. the compatibility test — 15 checks
10. the proposal recipes — 30 checks
11. validation of every example document

It exits non-zero if any of the groups fails.

The code generation test runs the generated TypeScript with Node, which strips
the types. Those checks are skipped, with a printed note, when no Node with
`--experimental-strip-types` (Node 22.6 and later) is on the `PATH`. Everything
else needs only Python.

It also verifies that the test suite changed nothing in the repository. The
proposal protocol writes to the documents, so every test that merges a
proposal works on a temporary copy of the project.

## Running one part

```powershell
python -m sdl validate --cases conformance/0.2/cases.yaml
python -m sdl validate --cases conformance/1.0/cases.yaml
python tests/test_verification.py
python tests/test_package.py
python tests/test_integration.py
python tests/test_recipes.py
```

## `test_verification.py`

The self-check of the Semantic Firewall and the proposal engine. It builds a
small canonical IR directly and asserts the governance guarantees: immutability
on rejection, determinism, atomicity, version integrity, conflict detection,
architectural prohibitions and type safety.

It runs under pytest if pytest is installed, and standalone otherwise:

```powershell
python -m pip install pytest
python -m pytest tests
```

### The check that used to document a defect

`test_v09_metadata_reference_is_not_revalidated` asserted the *incorrect*
behaviour: a proposal that pointed a flow step's `call_target` at a symbol
that did not exist was accepted and merged, because the reference checker only
inspected edges and the resolver only ran during lowering.

The firewall now derives the references of the patched graph again, so the
proposal is rejected. The test was inverted and renamed to
`test_v09_broken_reference_is_rejected`, and
`test_v10_broken_reference_leaves_the_ir_untouched` was added to prove that
the production IR survives the rejection unchanged.

The proposal protocol was later moved from the canonical IR to the documents,
as specification section 8.4 requires. The checks were rewritten accordingly:
they now run against a real project on disk, in a temporary directory.

## `recipes.py` and `test_recipes.py`

The **recipes** are the youngest group, and the most effective one. A recipe
is a small, complete change that exercises one rule of the specification,
together with the outcome the specification demands:

```python
Recipe(
    name="remove the binding of an interface a flow calls",
    rule="§6.2 a call is resolved through the bindings table",
    patches=[Patch(target="project.bindings[Greeter]", action=REMOVE)],
    expect="rejected",
    phase="semantic",
    code="SDL-E603",
)
```

The conformance suites check the **documents**; the recipes check the
**protocol**. The holes the conformance suites could not see were all found
by writing recipes.

A recipe states the phase and the diagnostic code it expects, not only
whether it was accepted, so a recipe cannot pass for the wrong reason. Every
recipe runs against a copy of `examples/hello`, so a recipe never touches the
repository.

## Layout

| Path | Contents |
| :--- | :--- |
| `test_verification.py` | The proposal protocol self-check. |
| `recipes.py` | The recipes of the proposal protocol. |
| `test_recipes.py` | The runner of the recipes. |
| `test_package.py` | Structural invariants: the version, the layers, the packaged schemas, the diagnostic registry. |
| `test_integration.py` | The end to end pipeline: documents in, canonical IR out. |
| `test_codegen.py` | The back ends: valid source, deterministic source, no raw text. |
| `test_runtime.py` | The runtime: the order of the steps, the conditions, the error strategies, the mandatory outputs. |
| `test_assignability.py` | The assignability rules of Core 0.2 section 6.7. |
| `test_compatibility.py` | The compatibility rules of Core 1.0 section 5. |
| `fixtures/` | Fixtures for the integration, the back end, the runtime and the compatibility tests. |
| `run_all.py` | The single entry point that runs every check. |

The conformance suites live in `conformance/`, not here, because they are the
contract of the specification rather than tests of the implementation. Their
READMEs list the rules each case covers.
