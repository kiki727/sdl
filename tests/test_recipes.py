"""The recipes of the proposal protocol.

A recipe is a request for change, written the way an agent would write it,
together with the outcome the specification demands. The recipes are the
counterpart of the conformance suites: the suites check that the toolchain
accepts and rejects documents, the recipes check that the *proposal protocol*
does.

Every recipe runs against a copy of ``examples/hello``, so a recipe never
touches the repository.

The value of a recipe is not the outcome alone. It is the pair

    (the outcome the specification demands, the outcome the toolchain gives)

When the two differ, the toolchain has a hole. A recipe that passes for the
wrong reason is as bad as a recipe that fails, so every recipe states the
phase and the diagnostic code it expects, not only whether it was accepted.

Run it with:

    python tests/test_recipes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from recipes import RECIPES, run  # noqa: E402


CHECKS = list(RECIPES)


def _check(recipe) -> bool:
    """Run one recipe and report whether it behaves as it should."""
    outcome = run(recipe)
    if outcome.ok:
        print(f"{recipe.name} | PASS")
        return True

    print(f"{recipe.name} | FAIL | {outcome.describe()}")
    print(f"    expected: {recipe.expect} phase={recipe.phase} code={recipe.code}")
    for diagnostic in outcome.result.diagnostics:
        print(f"    got: {diagnostic.code} | {diagnostic.message}")
    return False


def main() -> int:
    passed = 0
    for recipe in CHECKS:
        if _check(recipe):
            passed += 1

    print()
    print(f"{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
