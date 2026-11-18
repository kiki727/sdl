"""Tests of the SDL runtime.

The runtime executes the flows of a canonical IR directly. The checks prove
that it follows the specification: the order of the steps, the conditions,
the explicit data flow, the error strategies and the mandatory outputs.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sdl.backends.runtime import Runtime
from sdl.backends.runtime.errors import MandatoryOutputError, StepFailed
from sdl.compiler import compile_project

FIXTURES = Path(__file__).parent / "fixtures"
CONDITIONAL = FIXTURES / "conditional" / "project.sdl.yaml"


class Check:
    """The Check type of the fixture."""

    def __init__(self, is_valid: bool = True) -> None:
        self.is_valid = is_valid
        self.token = "token"


class Checker:
    """The Checker interface of the fixture."""

    def __init__(self, is_valid: bool = True, fail: bool = False) -> None:
        self.is_valid = is_valid
        self.fail = fail
        self.calls = 0

    def check(self, value: str) -> Check:
        self.calls += 1
        if self.fail:
            raise RuntimeError("the check failed")
        return Check(self.is_valid)


class Describer:
    """The helper module of the fixture.

    It counts the calls, so that a test can make a particular call fail.
    """

    def __init__(self, fail_on: tuple[int, ...] = ()) -> None:
        self.calls = 0
        self.fail_on = fail_on

    def __call__(self, value: str) -> str:
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError(f"the call {self.calls} failed")
        return f"described {value}"


def _runtime(checker: Checker | None = None, describe=None) -> Runtime:
    """A runtime of the fixture, with the implementations registered."""
    result = compile_project(CONDITIONAL)
    assert result.ok, result.report.as_dict()

    runtime = Runtime(result.graph)
    runtime.register("Checker", checker if checker is not None else Checker())
    runtime.register(
        "helper::describe",
        describe if describe is not None else Describer(),
    )
    return runtime


def _run(runtime: Runtime, **inputs):
    return asyncio.run(runtime.run_flow("conditional_flow", **inputs))


# ---------------------------------------------------------------------------
# The flow runs
# ---------------------------------------------------------------------------


def test_the_flow_runs() -> None:
    """A flow with every implementation registered returns its outputs."""
    outputs = _run(_runtime(), value="hello")
    assert outputs == {"description": "described hello"}, outputs


def test_the_flow_needs_its_inputs() -> None:
    """A flow refuses to run without the input it declares."""
    runtime = _runtime()
    try:
        _run(runtime)
    except TypeError as error:
        assert "value" in str(error), str(error)
    else:
        raise AssertionError("the flow ran without its input")


# ---------------------------------------------------------------------------
# The condition
# ---------------------------------------------------------------------------


def test_a_false_condition_skips_the_step() -> None:
    """A step whose condition is false does not change the state."""
    runtime = _runtime(checker=Checker(is_valid=False))
    try:
        _run(runtime, value="hello")
    except MandatoryOutputError as error:
        assert error.name == "description", error.name
    else:
        raise AssertionError("the skipped step did not fail the flow")


def test_a_true_condition_runs_the_step() -> None:
    """A step whose condition is true runs."""
    outputs = _run(_runtime(checker=Checker(is_valid=True)), value="hello")
    assert outputs == {"description": "described hello"}, outputs


# ---------------------------------------------------------------------------
# The error strategies
# ---------------------------------------------------------------------------


def test_the_fail_strategy_stops_the_flow() -> None:
    """A step without a strategy fails the flow."""
    runtime = _runtime(checker=Checker(fail=True))
    try:
        _run(runtime, value="hello")
    except StepFailed as error:
        assert "check_the_value" in str(error), str(error)
    else:
        raise AssertionError("the failing step did not fail the flow")


def test_the_ignore_strategy_continues_the_flow() -> None:
    """A step with the ignore strategy does not stop the flow.

    The third call to the helper is the step with the ignore strategy. The
    flow must go on and finish.
    """
    describer = Describer(fail_on=(3,))
    runtime = _runtime(describe=describer)
    outputs = _run(runtime, value="hello")
    assert outputs == {"description": "described hello"}, outputs
    assert describer.calls == 4, describer.calls


def test_the_retry_strategy_repeats_the_call() -> None:
    """A step with the retry policy repeats the call the number of times."""
    describer = Describer(fail_on=(1, 2, 3))
    runtime = _runtime(describe=describer)
    try:
        _run(runtime, value="hello")
    except StepFailed:
        pass
    else:
        raise AssertionError("the failing step did not fail the flow")

    # The retry policy allows three attempts, and all three failed.
    assert describer.calls == 3, f"the call was attempted {describer.calls} time(s)"


def test_the_runtime_reports_an_unknown_target() -> None:
    """A step that names something unregistered fails with a clear error."""
    from sdl.backends.runtime.errors import UnknownTargetError

    result = compile_project(CONDITIONAL)
    runtime = Runtime(result.graph)
    try:
        asyncio.run(runtime.run_flow("conditional_flow", value="hello"))
    except UnknownTargetError as error:
        assert "Checker" in str(error), str(error)
    else:
        raise AssertionError("the unknown target was not reported")


# ---------------------------------------------------------------------------
# The data flow is explicit
# ---------------------------------------------------------------------------


def test_the_data_flow_is_explicit() -> None:
    """A step receives what the mapping says, and nothing else."""

    seen = {}

    def describe(value: str) -> str:
        seen["value"] = value
        return "described"

    runtime = _runtime(describe=describe)
    _run(runtime, value="payload")
    assert seen["value"] == "payload", seen


def test_the_runtime_lists_its_flows() -> None:
    """The runtime knows which flows the project has."""
    runtime = _runtime()
    flows = runtime.flows()
    assert [flow.name for flow in flows] == ["conditional_flow"], flows


CHECKS = [
    test_the_flow_runs,
    test_the_flow_needs_its_inputs,
    test_a_false_condition_skips_the_step,
    test_a_true_condition_runs_the_step,
    test_the_fail_strategy_stops_the_flow,
    test_the_ignore_strategy_continues_the_flow,
    test_the_retry_strategy_repeats_the_call,
    test_the_runtime_reports_an_unknown_target,
    test_the_data_flow_is_explicit,
    test_the_runtime_lists_its_flows,
]


def run_all() -> bool:
    print("=== SDL RUNTIME TEST ===")
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
