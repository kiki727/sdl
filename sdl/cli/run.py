"""The ``run`` command: execute a flow of an SDL project.

    python -m sdl run examples/payment_system/project.sdl.yaml --flow process_customer_payment
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sdl.backends.runtime import Runtime
from sdl.compiler import compile_project


def _parse_value(text: str) -> Any:
    """The value of an input, as the command line gives it."""
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("none", "null"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return Decimal(text)
    except InvalidOperation:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _parse_inputs(pairs: list[str]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"{pair!r} is not a name=value pair.")
        name, _, value = pair.partition("=")
        inputs[name] = _parse_value(value)
    return inputs


def run(entry: Path, flow: str | None, inputs: list[str], as_json: bool = False) -> int:
    """Run a flow of a project."""
    result = compile_project(Path(entry))
    if not result.ok:
        print("BUILD FAILED", file=sys.stderr)
        for diagnostic in result.report.errors:
            print(
                f"  {diagnostic.severity} {diagnostic.phase} {diagnostic.code} "
                f"{diagnostic.file}:{diagnostic.line}:{diagnostic.column} "
                f"{diagnostic.message}",
                file=sys.stderr,
            )
        return 1

    from sdl.cli.build import _unsupported_target

    unsupported = _unsupported_target(result)
    if unsupported is not None:
        from sdl.backends import IMPLEMENTED_TARGETS

        print("RUN FAILED", file=sys.stderr)
        print(
            f"  error build SDL-E605 The back end {unsupported!r} is not implemented. "
            f"The toolchain implements: {', '.join(IMPLEMENTED_TARGETS)}.",
            file=sys.stderr,
        )
        return 1

    runtime = Runtime.from_project(result.graph, Path(entry).parent)

    try:
        values = _parse_inputs(inputs)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    if flow is None:
        flows = runtime.flows()
        if as_json:
            import json

            print(
                json.dumps(
                    {
                        "flows": [
                            {
                                "id": item.name,
                                "inputs": sorted(item.metadata.get("inputs", {})),
                            }
                            for item in flows
                        ]
                    },
                    indent=2,
                )
            )
            return 0
        if not flows:
            print("The project has no flow.")
            return 0
        print("The flows of the project:")
        for item in flows:
            arguments = ", ".join(sorted(item.metadata.get("inputs", {})))
            print(f"  {item.name}({arguments})")
        return 0

    try:
        outputs = asyncio.run(runtime.run_flow(flow, **values))
    except Exception as error:  # noqa: BLE001 - the command reports the failure
        print(f"FLOW FAILED: {error}", file=sys.stderr)
        return 1

    if as_json:
        import json

        print(json.dumps(outputs, indent=2, default=str))
        return 0

    print(f"The flow {flow} returned:")
    for name in sorted(outputs):
        print(f"  {name} = {outputs[name]!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute a flow of an SDL project.")
    parser.add_argument("entry", help="the project document")
    parser.add_argument("--flow", metavar="NAME", help="the flow to execute")
    parser.add_argument(
        "--input",
        metavar="NAME=VALUE",
        action="append",
        default=[],
        help="an input of the flow; may be given several times",
    )
    parser.add_argument("--json", action="store_true", help="emit the outputs as JSON")
    args = parser.parse_args(argv)

    entry = Path(args.entry)
    if not entry.exists():
        print(f"{entry}: no such file", file=sys.stderr)
        return 2

    return run(entry, args.flow, args.input, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
