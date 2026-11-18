"""Tests of the code generators, the Python and the NodeJS back end.

The generated source must be valid in its language, it must be deterministic,
and it must not carry anything the document wrote as raw text.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sdl.backends import IMPLEMENTED_TARGETS, codegen_for
from sdl.backends.codegen.python_gen import PythonCodegen
from sdl.backends.codegen.typescript_gen import TypeScriptCodegen
from sdl.compiler import compile_project

EXAMPLES = REPO_ROOT / "examples"
PAYMENT = EXAMPLES / "payment_system" / "project.sdl.yaml"
HERO_SITE = EXAMPLES / "hero_site" / "project.sdl.yaml"
FIXTURES = Path(__file__).parent / "fixtures"
CONDITIONAL = FIXTURES / "conditional" / "project.sdl.yaml"
GENERIC = FIXTURES / "compatibility" / "generic" / "project.sdl.yaml"
TYPESCRIPT = FIXTURES / "typescript" / "project.sdl.yaml"


def _generate(entry: Path) -> dict[str, str]:
    result = compile_project(entry)
    assert result.ok, result.report.as_dict()
    return PythonCodegen(result.graph).generate()


def _generate_typescript(entry: Path) -> dict[str, str]:
    result = compile_project(entry)
    assert result.ok, result.report.as_dict()
    return TypeScriptCodegen(result.graph).generate()


# ---------------------------------------------------------------------------
# The generated source is valid Python
# ---------------------------------------------------------------------------


def test_the_generated_source_compiles() -> None:
    """Every generated file must be valid Python."""
    for name, content in sorted(_generate(PAYMENT).items()):
        if not name.endswith(".py"):
            continue
        try:
            ast.parse(content, filename=name)
        except SyntaxError as error:
            raise AssertionError(f"{name} is not valid Python: {error}") from error


def test_the_generated_source_of_every_strategy_compiles() -> None:
    """The fixture exercises every error strategy, and it must compile too."""
    for name, content in sorted(_generate(CONDITIONAL).items()):
        if not name.endswith(".py"):
            continue
        try:
            ast.parse(content, filename=name)
        except SyntaxError as error:
            raise AssertionError(f"{name} is not valid Python: {error}") from error


# ---------------------------------------------------------------------------
# The generation is deterministic
# ---------------------------------------------------------------------------


def test_the_generation_is_deterministic() -> None:
    """The same specification must always produce the same source."""
    first = _generate(PAYMENT)
    second = _generate(PAYMENT)
    assert first == second, "two generations of the same project differ"


# ---------------------------------------------------------------------------
# The data flow is explicit
# ---------------------------------------------------------------------------


def test_the_flow_has_an_explicit_data_flow() -> None:
    """A step writes its output into the state, and reads it from the state."""
    files = _generate(PAYMENT)
    flow = files["src/flows/process_customer_payment.py"]

    assert "state['request'] = _result" in flow, flow
    assert "state['payment_result'] = _result" in flow, flow
    assert "amount=state['amount']" in flow, flow
    assert "request=state['request']" in flow, flow
    assert "result.result" not in flow, "the output mapping was read as a field"


def test_the_flow_reports_its_outputs() -> None:
    """The outputs of a flow are returned, and a missing one is an error."""
    files = _generate(PAYMENT)
    flow = files["src/flows/process_customer_payment.py"]

    assert "MandatoryOutputError" in flow, flow
    assert "'success': state['payment_result'].success" in flow, flow


# ---------------------------------------------------------------------------
# Nothing the document wrote is copied as raw text
# ---------------------------------------------------------------------------


def test_a_condition_is_parsed_and_rendered() -> None:
    """A condition becomes a Python expression, never a copy of the text."""
    files = _generate(CONDITIONAL)
    flow = files["src/flows/conditional_flow.py"]

    assert "check_result.is_valid == true" not in flow, "the condition was copied as text"
    assert "state['check_result'].is_valid == True" in flow, flow


def test_the_error_strategies_are_generated() -> None:
    """Every error strategy of the specification reaches the source."""
    files = _generate(CONDITIONAL)
    flow = files["src/flows/conditional_flow.py"]

    assert "call_with_retry" in flow, "the retry strategy is missing"
    assert "attempts=3" in flow, "the retry policy is missing"
    assert "backoff='exponential'" in flow, "the backoff strategy is missing"
    assert "the strategy is 'ignore'" in flow, "the ignore strategy is missing"
    assert "the strategy is 'goto'" in flow, "the goto strategy is missing"


def test_every_step_advances() -> None:
    """A step must move on when it succeeds, or the flow never ends."""
    files = _generate(CONDITIONAL)
    flow = files["src/flows/conditional_flow.py"]

    # Five steps, so the last one advances to five and the loop ends.
    assert "_step = 5" in flow, "the last step does not advance"
    # The goto strategy jumps to the step it names.
    assert "_step = 2" in flow, "the goto strategy does not jump"


# ---------------------------------------------------------------------------
# The bindings
# ---------------------------------------------------------------------------


def test_the_bindings_are_registered() -> None:
    """The registry registers what the specification binds."""
    files = _generate(PAYMENT)
    main = files["main.py"]

    assert "registry.register('PaymentProvider'" in main, main
    assert "registry.register('payment_helper::build_request'" in main, main


def test_the_types_are_generated_as_dataclasses() -> None:
    """A compound type becomes a dataclass with typed fields."""
    files = _generate(PAYMENT)
    request = files["src/types/payment_request.py"]

    assert "@dataclass" in request, request
    assert "amount: Decimal" in request, request
    assert "currency: str" in request, request
    assert "from decimal import Decimal" in request, request


def test_the_interfaces_are_generated_as_protocols() -> None:
    """An interface becomes a protocol with the method it declares."""
    files = _generate(PAYMENT)
    interface = files["src/interfaces/payment_provider.py"]

    assert "class PaymentProvider(Protocol):" in interface, interface
    assert "def charge(self, request: PaymentRequest)" in interface, interface
    assert "PaymentResponse" in interface, interface
    assert "Result[" not in interface, "the example no longer returns a Result"


def test_a_generic_return_type_is_generated() -> None:
    """The arguments of a generic survive the lowering and the codegen."""
    files = _generate(GENERIC)
    interface = files["src/interfaces/payment_provider.py"]

    assert "def charge(self, amount: Decimal) -> Result[PaymentResponse, Error]:" in interface, interface
    assert "from ..runtime.result import Result" in interface, interface


# ---------------------------------------------------------------------------
# The NodeJS/TypeScript back end
# ---------------------------------------------------------------------------


def _node_supports_strip_types() -> bool:
    """Whether Node can run the generated TypeScript directly.

    Node 22.6 and later can strip the types of a file as it loads it. When it
    cannot, the checks that need to *run* the generated source are skipped
    rather than failed, and the skip is printed.
    """
    node = shutil.which("node")
    if node is None:
        return False
    with tempfile.TemporaryDirectory() as folder:
        probe = Path(folder) / "probe.ts"
        probe.write_text(
            "const value: number = 1;\n"
            "if (value !== 1) { throw new Error('bad'); }\n",
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [node, "--experimental-strip-types", str(probe)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0


def _run_node(files: dict[str, str]) -> None:
    """Run every generated TypeScript file, and assert that Node accepts it."""
    node = shutil.which("node")
    assert node is not None, "Node is not on the PATH"
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for name in sorted(files):
            if not name.endswith(".ts"):
                continue
            result = subprocess.run(
                [node, "--experimental-strip-types", str(root / name)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, (
                f"{name} is not valid TypeScript:\n{result.stderr}"
            )


def test_a_target_selects_its_code_generator() -> None:
    """The target of the project picks the back end, not a fixed default."""
    assert "python" in IMPLEMENTED_TARGETS, IMPLEMENTED_TARGETS
    assert "nodejs" in IMPLEMENTED_TARGETS, IMPLEMENTED_TARGETS
    assert codegen_for("python") is PythonCodegen, "python does not select its back end"
    assert codegen_for("nodejs") is TypeScriptCodegen, "nodejs does not select its back end"
    assert codegen_for(None) is PythonCodegen, "no target must fall back to Python"


def test_the_typescript_is_erasable() -> None:
    """The generated TypeScript must be erasable, so Node can strip it.

    An ``enum``, a ``namespace`` or a parameter property emits JavaScript, so
    a file that uses one cannot be run by stripping the types. The back end
    therefore writes a union type and a ``const`` object instead of an enum.
    """
    files = _generate_typescript(TYPESCRIPT)
    for name, content in sorted(files.items()):
        if not name.endswith(".ts"):
            continue
        assert "enum " not in content, f"{name} declares a TypeScript enum"
        assert "namespace " not in content, f"{name} declares a namespace"


def test_the_generated_typescript_is_valid() -> None:
    """Every generated file must run under Node, which strips its types."""
    if not _node_supports_strip_types():
        print("      SKIP: no Node with --experimental-strip-types on the PATH")
        return
    _run_node(_generate_typescript(HERO_SITE))
    _run_node(_generate_typescript(TYPESCRIPT))
    _run_node(_generate_typescript(CONDITIONAL))
    _run_node(_generate_typescript(GENERIC))


def test_the_typescript_generation_is_deterministic() -> None:
    """The same specification must always produce the same TypeScript."""
    first = _generate_typescript(TYPESCRIPT)
    second = _generate_typescript(TYPESCRIPT)
    assert first == second, "two generations of the same project differ"


def test_the_typescript_flow_has_an_explicit_data_flow() -> None:
    """A step writes its output into the state, and reads it from the state."""
    flow = _generate_typescript(TYPESCRIPT)["src/flows/describe_order.ts"]

    assert 'state["priority"] = _result;' in flow, flow
    assert '{ "order": state["order"] }' in flow, flow
    assert "state[\"priority\"]" in flow, flow


def test_a_typescript_condition_is_parsed_and_rendered() -> None:
    """A condition becomes a TypeScript expression, never a copy of the text."""
    flow = _generate_typescript(TYPESCRIPT)["src/flows/describe_order.ts"]

    assert 'order.priority == "high"' not in flow, "the condition was copied as text"
    assert 'state["order"].priority == "high"' in flow, flow


def test_the_typescript_error_strategies_are_generated() -> None:
    """Every error strategy of the specification reaches the TypeScript."""
    result = compile_project(CONDITIONAL)
    assert result.ok, result.report.as_dict()
    flow = TypeScriptCodegen(result.graph).generate()["src/flows/conditional_flow.ts"]

    assert "call_with_retry" in flow, "the retry strategy is missing"
    assert "attempts: 3" in flow, "the retry policy is missing"
    assert 'backoff: "exponential"' in flow, "the backoff strategy is missing"
    assert "catch {" in flow, "the ignore strategy is missing"
    assert "continue;" in flow, "the goto strategy is missing"


def test_the_typescript_bindings_are_registered() -> None:
    """The registry registers what the specification binds."""
    main = _generate_typescript(HERO_SITE)["main.ts"]

    assert 'registry.register("ContentProvider", new JsonContentProvider());' in main, main
    assert 'registry.register("TemplateEngine", new HandlebarsEngine());' in main, main


def test_the_typescript_types_are_generated() -> None:
    """A compound type, an enum and an alias become the right declarations."""
    files = _generate_typescript(TYPESCRIPT)

    order = files["src/types/order.ts"]
    assert "export interface Order {" in order, order
    assert "note: string | null;" in order, order
    assert "tags: string[];" in order, order
    assert "scores: Record<string, number>;" in order, order

    priority = files["src/types/priority.ts"]
    assert 'export type Priority = "low" | "normal" | "high";' in priority, priority

    reference = files["src/types/reference.ts"]
    assert "export type Reference = string;" in reference, reference


def test_the_typescript_interfaces_are_generated() -> None:
    """An interface becomes an interface whose methods return a promise."""
    interface = _generate_typescript(TYPESCRIPT)["src/interfaces/priority_service.ts"]

    assert "export interface PriorityService {" in interface, interface
    assert "rank(input: { order: Order }): Promise<Priority>;" in interface, interface
    assert 'import type { Order } from "../types/order.ts";' in interface, interface


def test_the_typescript_generic_return_type_is_generated() -> None:
    """The arguments of a generic survive the lowering and the codegen."""
    interface = _generate_typescript(GENERIC)["src/interfaces/payment_provider.ts"]

    assert (
        "charge(input: { amount: number }): Promise<Result<PaymentResponse, Error>>;"
        in interface
    ), interface
    assert 'import type { Result } from "../runtime/result.ts";' in interface, interface


def test_the_typescript_project_files_are_generated() -> None:
    """The generated project must be runnable as an ES module without a build."""
    files = _generate_typescript(HERO_SITE)

    package = files["package.json"]
    assert '"type": "module"' in package, package
    assert '"start": "node main.ts"' in package, package

    tsconfig = files["tsconfig.json"]
    assert '"noEmit": true' in tsconfig, tsconfig
    assert '"allowImportingTsExtensions": true' in tsconfig, tsconfig


def test_the_typescript_dispatch_resolves_interface_methods() -> None:
    """The dispatcher resolves ``Interface::method`` through the bindings.

    Specification section 6.2: a step that names a method of an interface is
    resolved through the bindings table. The generated dispatcher must do the
    same, or a flow could not call the implementation the project bound.
    """
    dispatch = _generate_typescript(HERO_SITE)["src/runtime/dispatch.ts"]

    assert 'target.indexOf("::")' in dispatch, dispatch
    assert "registry.resolve(owner)" in dispatch, dispatch
    assert ".bind(implementation)" in dispatch, dispatch


def test_the_typescript_runtime_is_shipped() -> None:
    """The runtime the flows need must be generated with them."""
    files = _generate_typescript(HERO_SITE)

    for name in (
        "src/runtime/registry.ts",
        "src/runtime/errors.ts",
        "src/runtime/dispatch.ts",
        "src/runtime/result.ts",
        "package.json",
        "tsconfig.json",
    ):
        assert name in files, f"{name} is missing from the generated project"


CHECKS = [
    test_the_generated_source_compiles,
    test_the_generated_source_of_every_strategy_compiles,
    test_the_generation_is_deterministic,
    test_the_flow_has_an_explicit_data_flow,
    test_the_flow_reports_its_outputs,
    test_a_condition_is_parsed_and_rendered,
    test_the_error_strategies_are_generated,
    test_every_step_advances,
    test_the_bindings_are_registered,
    test_the_types_are_generated_as_dataclasses,
    test_the_interfaces_are_generated_as_protocols,
    test_a_generic_return_type_is_generated,
    test_a_target_selects_its_code_generator,
    test_the_typescript_is_erasable,
    test_the_generated_typescript_is_valid,
    test_the_typescript_generation_is_deterministic,
    test_the_typescript_flow_has_an_explicit_data_flow,
    test_a_typescript_condition_is_parsed_and_rendered,
    test_the_typescript_error_strategies_are_generated,
    test_the_typescript_bindings_are_registered,
    test_the_typescript_types_are_generated,
    test_the_typescript_interfaces_are_generated,
    test_the_typescript_generic_return_type_is_generated,
    test_the_typescript_project_files_are_generated,
    test_the_typescript_dispatch_resolves_interface_methods,
    test_the_typescript_runtime_is_shipped,
]


def run_all() -> bool:
    print("=== SDL CODE GENERATION TEST ===")
    failures = 0
    for check in CHECKS:
        name = check.__name__
        try:
            check()
        except AssertionError as error:
            failures += 1
            print(f"{name} | FAIL | {error}")
        except Exception as error:  # noqa: BLE001 - a broken check must not abort the run
            failures += 1
            print(f"{name} | ERROR | {type(error).__name__}: {error}")
        else:
            print(f"{name} | PASS")
    print()
    print(f"{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return failures == 0


if __name__ == "__main__":
    raise SystemExit(0 if run_all() else 1)
