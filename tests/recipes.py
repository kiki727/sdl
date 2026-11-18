"""Recipes: small, complete changes that exercise one rule each.

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
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sdl.proposal.engine import ProposalEngine, ProposalResult
from sdl.proposal.models import MigrationEntry, Patch, PatchAction, Proposal

#: The project every recipe runs against.
HELLO = Path(__file__).resolve().parent.parent / "examples" / "hello"

#: The actions, shorter to write.
REPLACE = PatchAction.REPLACE
ADD = PatchAction.ADD
REMOVE = PatchAction.REMOVE


@dataclass
class Recipe:
    """One request for change, and the outcome the specification demands."""

    name: str
    rule: str
    patches: list[Patch]
    expect: str  # "accepted" or "rejected"
    phase: str | None = None  # the phase a rejection must come from
    code: str | None = None  # the diagnostic code a rejection must carry
    setup: Callable[[Path], None] | None = None  # prepare the project
    approve: bool = True
    #: The version the project must have after the merge.
    version: str | None = None
    #: The version of the project the proposal claims to be based on.
    target_version: str = "1.0.0"
    #: The build of the merged project must be refused by the toolchain.
    build_fails: bool = False
    #: The migration plan of section 4.3.1, when the project requires one.
    migration: list[MigrationEntry] = field(default_factory=list)

    def proposal(self) -> Proposal:
        """The proposal of the recipe."""
        return Proposal(
            id=f"prop_{self.name.replace(' ', '_')}",
            target_version=self.target_version,
            author="recipe",
            rationale=f"The recipe {self.name!r}.",
            patches=list(self.patches),
            migration=list(self.migration),
            approve=self.approve,
        )


@dataclass
class Outcome:
    """What the toolchain did with a recipe."""

    recipe: Recipe
    result: ProposalResult
    project_version: str | None = None
    build_output: str = ""

    @property
    def ok(self) -> bool:
        """Does the outcome match what the specification demands?"""
        recipe = self.recipe
        result = self.result
        if recipe.expect == "accepted":
            if not result.accepted:
                return False
            if recipe.version is not None and self.project_version != recipe.version:
                return False
            if recipe.build_fails and "SDL-E605" not in self.build_output:
                return False
            if not recipe.build_fails and "SDL-E605" in self.build_output:
                return False
            return True
        if result.accepted:
            return False
        if recipe.phase is not None and result.phase != recipe.phase:
            return False
        if recipe.code is not None and recipe.code not in result.codes():
            return False
        return True

    def describe(self) -> str:
        """A one line description of the outcome."""
        result = self.result
        if result.accepted:
            version = f" (version {self.project_version})" if self.project_version else ""
            build = " build refused" if "SDL-E605" in self.build_output else ""
            return f"accepted{version}{build}"
        codes = ",".join(sorted(result.codes())) or "-"
        return f"rejected in {result.phase}: {codes}"


def run(recipe: Recipe) -> Outcome:
    """Run a recipe against a copy of the example project."""
    with tempfile.TemporaryDirectory(prefix="sdl-recipe-") as temporary:
        root = Path(temporary) / "project"
        shutil.copytree(HELLO, root)
        if recipe.setup is not None:
            recipe.setup(root)

        engine = ProposalEngine(root / "project.sdl.yaml")
        result = engine.process_proposal(recipe.proposal())

        version = None
        project = root / "project.sdl.yaml"
        if project.is_file():
            for line in project.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("version:"):
                    version = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                    break

        build_output = _build(root)

        return Outcome(
            recipe=recipe,
            result=result,
            project_version=version,
            build_output=build_output,
        )


def _build(root: Path) -> str:
    """The output of the build of a project."""
    import contextlib
    import io

    from sdl.cli.build import build

    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        try:
            build(root / "project.sdl.yaml", root / "build")
        except Exception as error:  # noqa: BLE001 - the output is the result
            stream.write(str(error))
    return stream.getvalue()


def run_all(recipes: list[Recipe]) -> list[Outcome]:
    """Run every recipe."""
    return [run(recipe) for recipe in recipes]


# ---------------------------------------------------------------------------
# The setups. Each one prepares a project for the recipe that needs it.
# ---------------------------------------------------------------------------


def _write(root: Path, name: str, text: str) -> None:
    """Write a document into the copy of the project."""
    (root / name).write_text(text, encoding="utf-8")


def setup_with_second_interface(root: Path) -> None:
    """Add a second interface and a second implementation."""
    _write(
        root,
        "farewell.sdl.yaml",
        """sdl: "1.0"
kind: interface

interface:
  id: Farewell
  version: "1.0.0"
  methods:
    - id: farewell
      version: "1.0.0"
      inputs:
        name: String
      outputs:
        type: String
""",
    )
    _write(
        root,
        "farewell_implementation.sdl.yaml",
        """sdl: "1.0"
kind: implementation

implementation:
  id: farewell_impl
  version: "1.0.0"
  implements:
    - interface: Farewell
      version: "1.0.0"
  language: python
  source:
    file: "src/farewell.py"
    symbol: Farewell
""",
    )
    _write(
        root,
        "src/farewell.py",
        '''"""The realization of the SDL interface Farewell."""


class Farewell:
    """Says goodbye."""

    def farewell(self, name: str) -> str:
        """Say goodbye to the person with that name."""
        return f"Bye, {name}!"
''',
    )
    project = root / "project.sdl.yaml"
    text = project.read_text(encoding="utf-8")
    text = text.replace(
        '    - path: "flow.sdl.yaml"',
        '    - path: "flow.sdl.yaml"\n    - path: "farewell.sdl.yaml"\n'
        '    - path: "farewell_implementation.sdl.yaml"',
    )
    project.write_text(text, encoding="utf-8")


def setup_with_second_greeter(root: Path) -> None:
    """Add a second implementation of ``Greeter``.

    The binding can only *move* to another implementation when there is
    another implementation to move to. Without this the recipe would patch a
    value to itself and pass for the wrong reason.
    """
    _write(
        root,
        "greeter_implementation_v2.sdl.yaml",
        """sdl: "1.0"
kind: implementation

implementation:
  id: greeter_impl_v2
  version: "1.0.0"
  implements:
    - interface: Greeter
      version: "1.0.0"
  language: python
  source:
    file: "src/greeter_v2.py"
    symbol: GreeterV2
""",
    )
    _write(
        root,
        "src/greeter_v2.py",
        '''"""A second realization of the SDL interface Greeter."""
from dataclasses import dataclass


@dataclass
class Greeting:
    """The Greeting type of the specification, in Python."""

    message: str


class GreeterV2:
    """Greets a person by name, in another way."""

    def greet(self, name: str) -> Greeting:
        return Greeting(message=f"Hi, {name}!")
''',
    )
    project = root / "project.sdl.yaml"
    text = project.read_text(encoding="utf-8")
    text = text.replace(
        '    - path: "flow.sdl.yaml"',
        '    - path: "flow.sdl.yaml"\n'
        '    - path: "greeter_implementation_v2.sdl.yaml"',
    )
    project.write_text(text, encoding="utf-8")


def setup_with_rust_implementation(root: Path) -> None:
    """Add an implementation that is written in another language."""
    _write(
        root,
        "rust_implementation.sdl.yaml",
        """sdl: "1.0"
kind: implementation

implementation:
  id: greeter_rust
  version: "1.0.0"
  implements:
    - interface: Greeter
      version: "1.0.0"
  language: rust
  source:
    file: "src/greeter.rs"
    symbol: Greeter
""",
    )
    _write(root, "src/greeter.rs", "pub struct Greeter;\n")
    project = root / "project.sdl.yaml"
    text = project.read_text(encoding="utf-8")
    text = text.replace(
        '    - path: "flow.sdl.yaml"',
        '    - path: "flow.sdl.yaml"\n    - path: "rust_implementation.sdl.yaml"',
    )
    project.write_text(text, encoding="utf-8")


def setup_with_typescript_implementation(root: Path) -> None:
    """Add an implementation written in TypeScript.

    The NodeJS back end of the toolchain can host it, so a project that names
    ``nodejs`` and binds it is valid; a project that names a target which
    cannot host it is refused (``SDL-E606``).
    """
    _write(
        root,
        "typescript_implementation.sdl.yaml",
        """sdl: "1.0"
kind: implementation

implementation:
  id: greeter_ts
  version: "1.0.0"
  implements:
    - interface: Greeter
      version: "1.0.0"
  language: typescript
  source:
    file: "src/greeter.ts"
    symbol: Greeter
""",
    )
    _write(root, "src/greeter.ts", "export class Greeter {}\n")
    project = root / "project.sdl.yaml"
    text = project.read_text(encoding="utf-8")
    text = text.replace(
        '    - path: "flow.sdl.yaml"',
        '    - path: "flow.sdl.yaml"\n    - path: "typescript_implementation.sdl.yaml"',
    )
    project.write_text(text, encoding="utf-8")


def setup_with_optional_greeter(root: Path) -> None:
    """Let the implementation accept the parameter the proposal adds.

    A proposal is a transaction over the documents, not over the code. The
    code of an implementation has to change outside of the protocol, and the
    proposal is rejected until it does.
    """
    source = root / "src" / "greeter.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "def greet(self, name: str) -> Greeting:",
            "def greet(self, name: str, locale: str = 'en') -> Greeting:",
        ),
        encoding="utf-8",
    )


def setup_with_optional_parameter(root: Path) -> None:
    """Let the implementation accept the parameter the proposal adds.

    The interface adds ``locale`` as ``Optional<String>``, so the flow does not
    have to map it. The implementation has to accept it all the same, because
    the contract of section 5.2 is about what the implementation can be asked
    for, and the annotation is ``Optional`` to match.
    """
    source = root / "src" / "greeter.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace(
            "from dataclasses import dataclass",
            "from dataclasses import dataclass\nfrom typing import Optional",
        )
        .replace(
            "def greet(self, name: str) -> Greeting:",
            "def greet(self, name: str, locale: Optional[str] = None) -> Greeting:",
        ),
        encoding="utf-8",
    )


def setup_requiring_migration(root: Path) -> None:
    """Let the project require a migration plan for a changed type."""
    project = root / "project.sdl.yaml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            "    disallow_breaking_changes: true",
            "    disallow_breaking_changes: true\n"
            "    require_migration_for_type_change: true",
        ),
        encoding="utf-8",
    )


def setup_with_unused_method(root: Path) -> None:
    """Add a method that no flow calls."""
    interfaces = root / "interfaces.sdl.yaml"
    interfaces.write_text(
        interfaces.read_text(encoding="utf-8").replace(
            "      outputs:\n        type: Greeting\n",
            "      outputs:\n        type: Greeting\n"
            "    - id: farewell\n"
            "      version: \"1.0.0\"\n"
            "      inputs:\n"
            "        name: String\n"
            "      outputs:\n"
            "        type: String\n",
        ),
        encoding="utf-8",
    )


def setup_without_id_policy(root: Path) -> None:
    """Let the policy of the identifiers be switched off.

    The policy of section 4.3 is a choice of the project, not a rule of the
    specification. A project that does not forbid the removal of an
    identifier has to be able to remove one.
    """
    project = root / "project.sdl.yaml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            "forbidden_id_changes: true",
            "forbidden_id_changes: false",
        ),
        encoding="utf-8",
    )


def setup_without_greeting_field(root: Path) -> None:
    """Remove the field the flow reads, so the flow breaks."""
    _write(
        root,
        "types.sdl.yaml",
        """sdl: "1.0"
kind: types

types:
  Greeting:
    id: Greeting
    version: "1.0.0"
    fields:
      text: String
""",
    )


# ---------------------------------------------------------------------------
# The recipes.
# ---------------------------------------------------------------------------


RECIPES: list[Recipe] = [
    # -- accepted changes ----------------------------------------------------
    Recipe(
        name="guard a step with a condition",
        rule="§3.2 a step may declare a condition",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].condition",
                action=ADD,
                value='name != ""',
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="replace the implementation of an interface",
        rule="§6.2 a binding names the implementation that answers",
        patches=[
            Patch(
                target="project.bindings[Greeter].implementation",
                action=REPLACE,
                value="greeter_impl_v2",
            )
        ],
        setup=setup_with_second_greeter,
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="add a field to a type",
        rule="§5.3.3 an addition does not break a contract",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "String", "language": "String"},
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="add an optional parameter to a method",
        rule="§5.2 an added optional parameter does not break the contract",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={"name": "String", "locale": "Optional<String>"},
            )
        ],
        setup=setup_with_optional_parameter,
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="change a type with a migration plan for its dependents",
        rule="§4.3.1 a changed type needs a migration plan for every dependent",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "String", "language": "String"},
            )
        ],
        setup=setup_requiring_migration,
        migration=[MigrationEntry(type="Greeting", documents=["interfaces.sdl.yaml"])],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="add a parameter to a method and to the flow that calls it",
        rule="§5.4 a change of a signature needs a version and a MAJOR bump",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={"name": "String", "locale": "String"},
            ),
            Patch(target="interfaces.sdl.yaml:version", action=REPLACE, value="2.0.0"),
            Patch(
                target="flow.sdl.yaml:inputs",
                action=REPLACE,
                value={"name": "String", "locale": "String"},
            ),
            Patch(
                target="flow.sdl.yaml:steps[greet].mapping",
                action=REPLACE,
                value={"name": "name", "locale": "locale"},
            ),
        ],
        setup=setup_with_optional_greeter,
        expect="accepted",
        version="2.0.0",
    ),
    Recipe(
        name="add a second interface and bind it",
        rule="§6.1 an implementation may serve more than one interface",
        patches=[
            Patch(
                target="project.bindings",
                action=ADD,
                value={
                    "interface": "Farewell",
                    "version": "1.0.0",
                    "implementation": "farewell_impl",
                },
            )
        ],
        setup=setup_with_second_interface,
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="a proposal without an approval changes nothing",
        rule="§8.5 the approval of an administrator is required",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].condition",
                action=ADD,
                value='name != ""',
            )
        ],
        approve=False,
        expect="accepted",
    ),
    # -- rejected changes ----------------------------------------------------
    Recipe(
        name="call a method that does not exist",
        rule="§8.4 phase four, a reference must resolve",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].call",
                action=REPLACE,
                value="Greeter::missing",
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E511",
    ),
    Recipe(
        name="remove a method of an interface that a flow calls",
        rule="§4.3 the identifiers of the components are stable",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet]",
                action=REMOVE,
                value=None,
            )
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="remove a method that no flow calls",
        rule="§4.3 the identifiers of the components are stable",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[farewell]",
                action=REMOVE,
                value=None,
            )
        ],
        setup=setup_with_unused_method,
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="remove a method that no flow calls, without the policy on ids",
        rule="§5.4 a removal breaks the contract, so the version is a MAJOR one",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[farewell]",
                action=REMOVE,
                value=None,
            )
        ],
        setup=lambda root: (setup_with_unused_method(root), setup_without_id_policy(root)),
        expect="accepted",
        version="2.0.0",
    ),
    Recipe(
        name="change a signature and bump the interface by a patch",
        rule="§5.4 a breaking change increments the MAJOR version",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={"name": "String", "locale": "String"},
            ),
            Patch(target="interfaces.sdl.yaml:version", action=REPLACE, value="1.0.1"),
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="bind an interface to an implementation of another interface",
        rule="§5.3 an implementation must satisfy the interface it is bound to",
        patches=[
            Patch(
                target="project.bindings[Greeter].implementation",
                action=REPLACE,
                value="farewell_impl",
            )
        ],
        setup=setup_with_second_interface,
        expect="rejected",
        phase="semantic",
        code="SDL-E604",
    ),
    Recipe(
        name="remove the binding of an interface a flow calls",
        rule="§6.2 a call is resolved through the bindings table",
        patches=[
            Patch(
                target="project.bindings[Greeter]",
                action=REMOVE,
                value=None,
            )
        ],
        expect="rejected",
        phase="semantic",
    ),
    Recipe(
        name="change the type of a field a flow reads",
        rule="§4.2 the state of a flow must stay consistent",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "Int"},
            )
        ],
        expect="rejected",
        phase="semantic",
    ),
    Recipe(
        name="remove a field a flow reads",
        rule="§4.2 a flow may not read a state variable that does not exist",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"text": "String"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E502",
    ),
    Recipe(
        name="change the type of a flow input",
        rule="§2.3 the mapping of a step must match the signature",
        patches=[
            Patch(
                target="flow.sdl.yaml:inputs",
                action=REPLACE,
                value={"name": "Int"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E501",
    ),
    Recipe(
        name="write a condition that is not an expression",
        rule="§3.2 a condition is parsed, never evaluated as text",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].condition",
                action=ADD,
                value="name >>",
            )
        ],
        expect="rejected",
        phase="semantic",
    ),
    Recipe(
        name="refer to a type that does not exist",
        rule="§8.4 phase two, a name must exist",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].outputs",
                action=REPLACE,
                value={"type": "Nonexistent"},
            )
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="change a signature without a version",
        rule="§4.3 a breaking change needs a version increment",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={"name": "String", "locale": "String"},
            )
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="change a type without a migration plan",
        rule="§4.3.1 a changed type needs a migration plan for every dependent",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "String", "language": "String"},
            )
        ],
        setup=setup_requiring_migration,
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="migrate a type but not every dependent",
        rule="§4.3.1 the migration plan must cover every dependent module",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "String", "language": "String"},
            )
        ],
        setup=setup_requiring_migration,
        migration=[MigrationEntry(type="Greeting", documents=["flow.sdl.yaml"])],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="migrate a type with a document that does not exist",
        rule="§4.3.1 the migration plan names documents of the project",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "String", "language": "String"},
            )
        ],
        setup=setup_requiring_migration,
        migration=[
            MigrationEntry(
                type="Greeting",
                documents=["interfaces.sdl.yaml", "nowhere.sdl.yaml"],
            )
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="change the identifier of a component",
        rule="§4.3 the identifiers of the components are stable",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.id",
                action=REPLACE,
                value="Renamed",
            )
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="name a backend that is not implemented",
        rule="§7.1 the target names the language of the build",
        patches=[
            Patch(
                target="project.backend.target",
                action=REPLACE,
                value="rust",
            )
        ],
        expect="accepted",
        build_fails=True,
    ),
    Recipe(
        name="bind a python backend to an implementation in another language",
        rule="§7.2 the target must be compatible with the languages of the implementations",
        patches=[
            Patch(
                target="project.bindings[Greeter].implementation",
                action=REPLACE,
                value="greeter_rust",
            )
        ],
        setup=setup_with_rust_implementation,
        expect="rejected",
        phase="semantic",
    ),
    Recipe(
        name="point a nodejs backend at a TypeScript implementation",
        rule="§7.2 the target must be compatible with the languages of the implementations",
        patches=[
            Patch(target="project.backend.target", action=REPLACE, value="nodejs"),
            Patch(
                target="project.bindings[Greeter].implementation",
                action=REPLACE,
                value="greeter_ts",
            ),
        ],
        setup=setup_with_typescript_implementation,
        expect="accepted",
    ),
    Recipe(
        name="patch a document that does not exist",
        rule="§8.3 a target must resolve",
        patches=[
            Patch(
                target="nowhere.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "String"},
            )
        ],
        expect="rejected",
        phase="referential",
    ),
    Recipe(
        name="based on another version of the project",
        rule="§8.2 the target version is the version the proposal is based on",
        patches=[],
        target_version="0.9.0",
        expect="rejected",
        phase="referential",
        code="SDL-E703",
    ),
]
