"""The SDL command line.

    python -m sdl validate <file> ...
    python -m sdl build <project>
"""

from __future__ import annotations

import sys

from sdl.cli import build as build_command
from sdl.cli import propose as propose_command
from sdl.cli import run as run_command
from sdl.cli import validate as validate_command

COMMANDS = {
    "validate": validate_command.main,
    "build": build_command.main,
    "propose": propose_command.main,
    "run": run_command.main,
}


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    if not arguments or arguments[0] in ("-h", "--help"):
        print("usage: python -m sdl <command> [options]")
        print()
        print("commands:")
        print("  validate   validate SDL documents")
        print("  build      compile an SDL project into the canonical IR")
        print("  propose    run a proposal through the governance engine")
        print("  run        execute a flow of an SDL project")
        return 0

    command = arguments[0]
    if command not in COMMANDS:
        print(f"unknown command {command!r}", file=sys.stderr)
        print("usage: python -m sdl <command> [options]", file=sys.stderr)
        return 2

    return COMMANDS[command](arguments[1:])


if __name__ == "__main__":
    raise SystemExit(main())
