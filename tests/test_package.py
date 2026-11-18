"""Structural invariants of the package.

These checks guard the things that are easy to break while restructuring the
repository: the version must be stated in exactly one place and agree with
``VERSION``, every layer of the pipeline must be importable, and the JSON
Schemas must be shipped with the package.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import sdl

LAYERS = [
    "sdl.yaml.subset",
    "sdl.schema.envelope",
    "sdl.types.expressions",
    "sdl.semantics.scope",
    "sdl.semantics.core10",
    "sdl.parser.yaml_parser",
    "sdl.ir.graph",
    "sdl.lowering.symbol_builder",
    "sdl.lowering.resolver",
    "sdl.validation.validator",
    "sdl.proposal.engine",
    "sdl.backends.codegen.python_gen",
    "sdl.backends.codegen.typescript_gen",
    "sdl.backends.codegen.go_gen",
    "sdl.cli.validate",
]

SCHEMA_FILES = [
    "sdl-0.2.schema.json",
    "sdl-0.2.validation.schema.json",
    "sdl-1.0.schema.json",
    "sdl-1.0.validation.schema.json",
]


def test_version_matches_the_version_file() -> None:
    """``sdl.__version__`` must equal the content of ``VERSION``."""
    declared = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert sdl.__version__ == declared, (
        f"sdl.__version__ is {sdl.__version__!r} but VERSION declares {declared!r}"
    )


def test_every_layer_imports() -> None:
    """Every layer of the pipeline must be importable."""
    import importlib

    for module in LAYERS:
        importlib.import_module(module)


def test_schemas_are_packaged_and_parse() -> None:
    """Every JSON Schema must ship with the package and be valid JSON."""
    schema_dir = Path(sdl.__file__).parent / "schema"
    for name in SCHEMA_FILES:
        path = schema_dir / name
        assert path.is_file(), f"missing schema: {name}"
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document.get("$schema"), f"{name} has no $schema declaration"


def test_every_subpackage_is_declared() -> None:
    """Every subpackage of ``sdl`` must be declared in ``pyproject.toml``.

    An undeclared subpackage still imports from the working tree, because
    Python treats a directory without an ``__init__.py`` as a namespace
    package. It does *not* ship in a wheel, so a real installation would be
    broken while every check run from the repository passes. This is the trap
    ``sdl.flow`` fell into.
    """
    import re

    declared = set(
        re.findall(
            r'"sdl(?:\.[A-Za-z_][A-Za-z0-9_]*)*"',
            (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        )
    )
    declared = {name.strip('"') for name in declared}

    package_dir = Path(sdl.__file__).parent
    for child in sorted(package_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name == "__pycache__":
            continue
        if not any(child.glob("*.py")):
            continue
        module = f"sdl.{child.name}"
        assert module in declared, (
            f"{module} is a subpackage of sdl but is not listed in the "
            f"packages of pyproject.toml, so it would not ship in a wheel"
        )


def test_diagnostic_registry_is_complete() -> None:
    """Every code in the registry must have a description, and vice versa."""
    from sdl.diagnostics import CODES_0_2, CODES_1_0, DIAGNOSTIC_CODES

    assert DIAGNOSTIC_CODES == {**CODES_0_2, **CODES_1_0}
    for code, description in DIAGNOSTIC_CODES.items():
        assert code.startswith("SDL-"), f"malformed code: {code}"
        assert description, f"{code} has no description"


def test_spec_envelope_examples_use_the_current_version() -> None:
    """Every YAML example in the current specification must declare 1.0.

    The specification mentions the historical envelope ``sdl: "0.3"`` in its
    prose, which is correct. What must not happen is a YAML example in the
    current specification declaring anything other than the current version,
    because that would contradict the rule in section 0 of the same document.
    """
    import re

    declared = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    spec = (REPO_ROOT / "spec" / "sdl-core-1.0.md").read_text(encoding="utf-8")

    blocks = re.findall(r"```yaml\n(.*?)```", spec, re.S)
    assert blocks, "the specification contains no YAML examples"

    for index, block in enumerate(blocks):
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped.startswith("sdl:"):
                continue
            value = stripped.split(":", 1)[1].strip().strip('"')
            assert value == declared, (
                f"YAML example {index + 1} declares sdl: {value!r} "
                f"but the current core version is {declared!r}"
            )


CHECKS = [
    test_version_matches_the_version_file,
    test_every_layer_imports,
    test_schemas_are_packaged_and_parse,
    test_every_subpackage_is_declared,
    test_diagnostic_registry_is_complete,
    test_spec_envelope_examples_use_the_current_version,
]


def run_all() -> bool:
    print("=== SDL PACKAGE STRUCTURE CHECK ===")
    failures = 0
    for check in CHECKS:
        name = check.__name__
        try:
            check()
        except AssertionError as error:
            failures += 1
            print(f"{name} | FAIL | {error}")
        else:
            print(f"{name} | PASS")
    print()
    print(f"{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return failures == 0


if __name__ == "__main__":
    raise SystemExit(0 if run_all() else 1)
