"""The ``build`` command: compile an SDL project into the canonical IR."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sdl.cli.reporting import print_diagnostics
from sdl.compiler import CompileResult, compile_project
from sdl.ir import serialization


def _default_output(entry: Path) -> Path:
    """Where the build output goes when no output directory is given."""
    name = entry.stem.replace(".sdl", "") or "project"
    return Path("generated") / name


def _backend_target(result: CompileResult) -> str | None:
    """The target of the back end of the project."""
    for symbol in result.graph.symbols.values():
        backend = symbol.metadata.get("backend")
        if isinstance(backend, dict):
            target = backend.get("target")
            if isinstance(target, str):
                return target
    return None


def _unsupported_target(result: CompileResult) -> str | None:
    """The target of the back end, when the toolchain cannot produce it."""
    from sdl.backends import IMPLEMENTED_TARGETS

    target = _backend_target(result)
    if target is None or target in IMPLEMENTED_TARGETS:
        return None
    return target


def build(
    entry: Path,
    output: Path | None = None,
    as_json: bool = False,
    ir_only: bool = False,
) -> int:
    """Compile a project and write the canonical IR and the generated source."""
    result: CompileResult = compile_project(Path(entry))

    if not result.ok:
        print("BUILD FAILED", file=sys.stderr)
        print_diagnostics(result.report)
        return 1

    unsupported = _unsupported_target(result)
    if unsupported is not None:
        from sdl.backends import IMPLEMENTED_TARGETS

        print("BUILD FAILED", file=sys.stderr)
        print(
            f"  error build SDL-E605 The back end {unsupported!r} is not implemented. "
            f"The toolchain implements: {', '.join(IMPLEMENTED_TARGETS)}.",
            file=sys.stderr,
        )
        return 1

    target = Path(output) if output is not None else _default_output(Path(entry))
    target.mkdir(parents=True, exist_ok=True)
    ir_path = target / "ir.json"
    serialization.dump(result.graph, ir_path)

    generated: list[str] = []
    if not ir_only:
        from sdl.backends import codegen_for

        generator = codegen_for(_backend_target(result))(result.graph)
        files = generator.generate()
        for relative, content in sorted(files.items()):
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            generated.append(relative)

    if as_json:
        print(_summary_json(result, ir_path, generated))
    else:
        print(f"Compiled {len(result.documents)} document(s):")
        for document in result.documents:
            print(f"  {document}")
        print()
        print(f"Symbols: {result.symbol_count}")
        print(f"Edges:   {result.edge_count}")
        print(f"IR:      {ir_path}")
        if generated:
            print(f"Source:  {len(generated)} file(s) in {target}")
    return 0


def _summary_json(result: CompileResult, ir_path: Path, generated: list[str]) -> str:
    import json

    return json.dumps(
        {
            "status": "passed",
            "documents": result.documents,
            "symbols": result.symbol_count,
            "edges": result.edge_count,
            "ir": str(ir_path),
            "generated": generated,
        },
        indent=2,
        ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile an SDL project into the canonical IR.")
    parser.add_argument("entry", help="the project document, or a directory that holds one")
    parser.add_argument("--out", metavar="DIR", help="where to write the build output")
    parser.add_argument("--json", action="store_true", help="emit a machine readable summary")
    parser.add_argument(
        "--ir-only",
        action="store_true",
        help="write the canonical IR only, without the generated source",
    )
    args = parser.parse_args(argv)

    entry = Path(args.entry)
    if not entry.exists():
        print(f"{entry}: no such file or directory", file=sys.stderr)
        return 2

    return build(entry, Path(args.out) if args.out else None, args.json, args.ir_only)


if __name__ == "__main__":
    raise SystemExit(main())
