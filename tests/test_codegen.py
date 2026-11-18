"""Tests of the Python back end.

The generated source must be valid Python, it must be deterministic, and it
must not carry anything the document wrote as raw text.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sdl.backends.codegen.python_gen import PythonCodegen
from sdl.compiler import compile_project

EXAMPLES = REPO_ROOT / "examples"
PAYMENT = EXAMPLES / "payment_system" / "project.sdl.yaml"
FIXTURES = Path(__file__).parent / "fixtures"
CONDITIONAL = FIXTURES / "conditional" / "project.sdl.yaml"
GENERIC = FIXTURES / "compatibility" / "generic" / "project.sdl.yaml"


def _generate(entry: Path) -> dict[str, str]:
    result = compile_project(entry)
    assert result.ok, result.report.as_dict()
    return PythonCodegen(result.graph).generate()


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
]


def run_all() -> bool:
    print("=== SDL PYTHON BACK END TEST ===")
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
