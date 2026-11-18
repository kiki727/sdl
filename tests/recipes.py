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


def setup_with_go_implementation(root: Path) -> None:
    """Add an implementation written in Go.

    The Go back end of the toolchain can host it, so a project that names
    ``go`` and binds it is valid; a project that names a target which cannot
    host it is refused (``SDL-E606``).
    """
    _write(
        root,
        "go_implementation.sdl.yaml",
        """sdl: "1.0"
kind: implementation

implementation:
  id: greeter_go
  version: "1.0.0"
  implements:
    - interface: Greeter
      version: "1.0.0"
  language: go
  source:
    file: "src/greeter.go"
    symbol: Greeter
""",
    )
    _write(root, "src/greeter.go", "package main\n\ntype Greeter struct{}\n")
    project = root / "project.sdl.yaml"
    text = project.read_text(encoding="utf-8")
    text = text.replace(
        '    - path: "flow.sdl.yaml"',
        '    - path: "flow.sdl.yaml"\n    - path: "go_implementation.sdl.yaml"',
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


def setup_with_farewell_implementation(root: Path) -> None:
    """Give the implementation the method the proposal adds to the interface."""
    source = root / "src" / "greeter.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "    def greet(self, name: str) -> Greeting:",
            "    def farewell(self, name: str) -> str:\n"
            '        """Say goodbye to the person with that name."""\n'
            '        return f"Bye, {name}!"\n\n'
            "    def greet(self, name: str) -> Greeting:",
        ),
        encoding="utf-8",
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
                target="project.bindings[Greeter].version",
                action=REPLACE,
                value="2.0.0",
            ),
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
        name="add an alias and use it as a field type in the same proposal",
        rule="§8.4 phase two a name defined within the proposal exists",
        patches=[
            Patch(
                target="types.sdl.yaml:Nickname",
                action=ADD,
                value={"id": "Nickname", "version": "1.0.0", "type": "String"},
            ),
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "Nickname"},
            ),
        ],
        expect="accepted",
        version="1.1.0",
    ),
    Recipe(
        name="add an enum type",
        rule="§8.3 add a new element to a collection",
        patches=[
            Patch(
                target="types.sdl.yaml:Status",
                action=ADD,
                value={
                    "id": "Status",
                    "version": "1.0.0",
                    "enum": ["active", "closed"],
                },
            )
        ],
        expect="accepted",
        version="1.1.0",
    ),
    Recipe(
        name="add an alias and use it as a flow input in the same proposal",
        rule="§9.3.2 an alias is transparent",
        patches=[
            Patch(
                target="types.sdl.yaml:Nickname",
                action=ADD,
                value={"id": "Nickname", "version": "1.0.0", "type": "String"},
            ),
            Patch(
                target="flow.sdl.yaml:inputs",
                action=REPLACE,
                value={"name": "Nickname"},
            ),
        ],
        expect="accepted",
        version="1.1.0",
    ),
    Recipe(
        name="change a parameter to an alias of the same type",
        rule="§9.3.2 an alias is transparent to the policy of section 4.3",
        patches=[
            Patch(
                target="types.sdl.yaml:Nickname",
                action=ADD,
                value={"id": "Nickname", "version": "1.0.0", "type": "String"},
            ),
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={"name": "Nickname"},
            ),
        ],
        expect="accepted",
        version="1.1.0",
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
        name="point a go backend at a Go implementation",
        rule="§7.2 the target must be compatible with the languages of the implementations",
        patches=[
            Patch(target="project.backend.target", action=REPLACE, value="go"),
            Patch(
                target="project.bindings[Greeter].implementation",
                action=REPLACE,
                value="greeter_go",
            ),
        ],
        setup=setup_with_go_implementation,
        expect="accepted",
    ),
    Recipe(
        name="point a go backend at a TypeScript implementation",
        rule="§7.2 the target must be compatible with the languages of the implementations",
        patches=[
            Patch(target="project.backend.target", action=REPLACE, value="go"),
            Patch(
                target="project.bindings[Greeter].implementation",
                action=REPLACE,
                value="greeter_ts",
            ),
        ],
        setup=setup_with_typescript_implementation,
        expect="rejected",
        phase="semantic",
        code="SDL-E606",
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
    Recipe(
        name="bind an interface the proposal does not declare",
        rule="§8.4 phase two a reference in a value field must exist",
        patches=[
            Patch(
                target="project.bindings",
                action=ADD,
                value={
                    "interface": "Nonexistent",
                    "version": "1.0.0",
                    "implementation": "greeter_impl",
                },
            )
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="bind an implementation the proposal does not declare",
        rule="§8.4 phase two a reference in a value field must exist",
        patches=[
            Patch(
                target="project.bindings",
                action=ADD,
                value={
                    "interface": "Farewell",
                    "version": "1.0.0",
                    "implementation": "nowhere",
                },
            )
        ],
        setup=setup_with_second_interface,
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="point a binding at an implementation that does not exist",
        rule="§8.4 phase two a reference in a value field must exist",
        patches=[
            Patch(
                target="project.bindings[Greeter].implementation",
                action=REPLACE,
                value="nowhere",
            )
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="add a method with an input type that does not exist",
        rule="§8.4 phase two a reference in a value field must exist",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods",
                action=ADD,
                value={
                    "id": "farewell",
                    "version": "1.0.0",
                    "inputs": {"name": "Nonexistent"},
                    "outputs": {"type": "String"},
                },
            )
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="add a method whose output type does not exist",
        rule="§8.4 phase two a reference in a value field must exist",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods",
                action=ADD,
                value={
                    "id": "farewell",
                    "version": "1.0.0",
                    "inputs": {"name": "String"},
                    "outputs": {"type": "Nonexistent"},
                },
            )
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="add a field whose type does not exist",
        rule="§8.4 phase two a reference in a value field must exist",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=ADD,
                value={"language": "Nonexistent"},
            )
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="change the output type of a method to a type that does not exist",
        rule="§8.4 phase two a reference in a value field must exist",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].outputs.type",
                action=REPLACE,
                value="Nonexistent",
            )
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="add an import of a document that does not exist",
        rule="§4.1 an import must name a document of the project",
        patches=[
            Patch(
                target="project.imports",
                action=ADD,
                value={"path": "nowhere.sdl.yaml"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E302",
    ),
    Recipe(
        name="add a second binding for the same interface",
        rule="§6.2 a binding is exclusive",
        patches=[
            Patch(
                target="project.bindings",
                action=ADD,
                value={
                    "interface": "Greeter",
                    "version": "1.0.0",
                    "implementation": "greeter_impl_v2",
                },
            )
        ],
        setup=setup_with_second_greeter,
        expect="rejected",
        phase="semantic",
        code="SDL-E603",
    ),
    Recipe(
        name="change a parameter to an alias of another type",
        rule="§4.3 a change of type still needs a version increment",
        patches=[
            Patch(
                target="types.sdl.yaml:Count",
                action=ADD,
                value={"id": "Count", "version": "1.0.0", "type": "Int"},
            ),
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={"name": "Count"},
            ),
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    # -- error handling and retry (spec section 3.3.1) -----------------------
    Recipe(
        name="guard a step with the fail strategy",
        rule="§3.3.1 on_error: fail terminates the flow",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="fail",
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="guard a step with the ignore strategy",
        rule="§3.3.1 on_error: ignore skips the failure",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="ignore",
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="retry a step with a retry policy",
        rule="§3.3.1.1 on_error: retry needs a retry block",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="retry",
            ),
            Patch(
                target="flow.sdl.yaml:steps[greet].retry",
                action=ADD,
                value={"attempts": 3},
            ),
        ],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="retry a step without a retry policy",
        rule="§3.3.1.1 on_error: retry needs a retry block",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="retry",
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E505",
    ),
    Recipe(
        name="give a step a retry policy without on_error",
        rule="§3.3.1.1 a retry policy needs on_error: retry",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].retry",
                action=ADD,
                value={"attempts": 3},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E505",
    ),
    Recipe(
        name="retry a step a zero number of times",
        rule="§3.3.1.1 retry.attempts is at least one",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="retry",
            ),
            Patch(
                target="flow.sdl.yaml:steps[greet].retry",
                action=ADD,
                value={"attempts": 0},
            ),
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E505",
    ),
    Recipe(
        name="give a step an unknown error strategy",
        rule="§3.3.1 the strategies are fail, ignore, retry and goto",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="explode",
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E506",
    ),
    Recipe(
        name="jump to a step that does not exist",
        rule="§3.3.1 on_error: goto names a step of the flow",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="goto nowhere",
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E507",
    ),
    Recipe(
        name="jump to a step of the same flow",
        rule="§3.3.1 on_error: goto names a step of the flow",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps",
                action=ADD,
                value={
                    "id": "second",
                    "call": "Greeter::greet",
                    "mapping": {"name": "name"},
                    "output_map": {"again": "result"},
                },
            ),
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="goto second",
            ),
        ],
        expect="accepted",
        version="1.1.0",
    ),
    Recipe(
        name="jump to the step itself",
        rule="§3.3.1 on_error: goto names a step of the flow",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].on_error",
                action=ADD,
                value="goto greet",
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    # -- flow outputs (spec sections 2.2.1 and 3.3.2) ------------------------
    Recipe(
        name="remove the output mapping of a flow that declares outputs",
        rule="§2.2.1 output_mapping is mandatory when outputs are declared",
        patches=[
            Patch(target="flow.sdl.yaml:output_mapping", action=REMOVE, value=None)
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E503",
    ),
    Recipe(
        name="leave a declared output unpopulated",
        rule="§2.2.1 every declared output must be populated",
        patches=[
            Patch(
                target="flow.sdl.yaml:outputs",
                action=REPLACE,
                value={"message": "String", "extra": "String"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E503",
    ),
    Recipe(
        name="remove the outputs of a flow",
        rule="§2.2.1 outputs are optional",
        patches=[
            Patch(target="flow.sdl.yaml:outputs", action=REMOVE, value=None),
            Patch(target="flow.sdl.yaml:output_mapping", action=REMOVE, value=None),
        ],
        expect="accepted",
        version="1.0.1",
    ),
    # -- flow state (spec section 2.3.3) -------------------------------------
    Recipe(
        name="guard a step with a variable that does not exist",
        rule="§2.3.3 a condition reads state that exists",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].condition",
                action=ADD,
                value='mystery != ""',
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E502",
    ),
    Recipe(
        name="map a parameter from a variable that does not exist",
        rule="§2.3.3 a mapping reads state that exists",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].mapping",
                action=REPLACE,
                value={"name": "mystery"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E502",
    ),
    Recipe(
        name="omit a parameter a method requires",
        rule="§2.3.3 the mapping must supply every required parameter",
        patches=[
            Patch(target="flow.sdl.yaml:steps[greet].mapping", action=REMOVE, value=None)
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E501",
    ),
    Recipe(
        name="read the output of an earlier step",
        rule="§2.3.3 a step may read what an earlier step placed in the state",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps",
                action=ADD,
                value={
                    "id": "second",
                    "call": "Greeter::greet",
                    "mapping": {"name": "greeting.message"},
                    "output_map": {"again": "result"},
                },
            )
        ],
        expect="accepted",
        version="1.1.0",
    ),
    # -- type expressions (spec section 4.2, inherited from Core 0.2) --------
    Recipe(
        name="declare an alias that refers to itself",
        rule="§4.2 an alias chain must not be cyclic",
        patches=[
            Patch(
                target="types.sdl.yaml:Loop",
                action=ADD,
                value={"id": "Loop", "version": "1.0.0", "type": "Loop"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E402",
    ),
    Recipe(
        name="declare two aliases that refer to each other",
        rule="§4.2 an alias chain must not be cyclic",
        patches=[
            Patch(
                target="types.sdl.yaml:A",
                action=ADD,
                value={"id": "A", "version": "1.0.0", "type": "B"},
            ),
            Patch(
                target="types.sdl.yaml:B",
                action=ADD,
                value={"id": "B", "version": "1.0.0", "type": "A"},
            ),
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E402",
    ),
    Recipe(
        name="give a type a field of a type that does not exist",
        rule="§4.2 a field names a type of the specification",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "Missing"},
            )
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E702",
    ),
    Recipe(
        name="add a Map field to a type",
        rule="§4.2 a field may be a generic type",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "String", "labels": "Map<String, String>"},
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="add a List field to a type",
        rule="§4.2 a field may be a generic type",
        patches=[
            Patch(
                target="types.sdl.yaml:Greeting.fields",
                action=REPLACE,
                value={"message": "String", "tags": "List<String>"},
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="give a type a Unit field that no flow reads",
        rule="§4.2 Unit is not allowed in this position",
        patches=[
            Patch(
                target="types.sdl.yaml:Weird",
                action=ADD,
                value={"id": "Weird", "version": "1.0.0", "fields": {"x": "Unit"}},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E405",
    ),
    Recipe(
        name="give a type a bare generic field that no flow reads",
        rule="§4.2 a generic type needs its arguments",
        patches=[
            Patch(
                target="types.sdl.yaml:Weird",
                action=ADD,
                value={"id": "Weird", "version": "1.0.0", "fields": {"x": "List"}},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E406",
    ),
    Recipe(
        name="give a type a Map field whose key is not allowed",
        rule="§4.2 a Map key is String, Int or UUID",
        patches=[
            Patch(
                target="types.sdl.yaml:Weird",
                action=ADD,
                value={
                    "id": "Weird",
                    "version": "1.0.0",
                    "fields": {"x": "Map<Float, String>"},
                },
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E406",
    ),
    Recipe(
        name="declare an alias to Unit",
        rule="§4.2 Unit is not allowed in this position",
        patches=[
            Patch(
                target="types.sdl.yaml:Nothing",
                action=ADD,
                value={"id": "Nothing", "version": "1.0.0", "type": "Unit"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E405",
    ),
    Recipe(
        name="declare an alias to a bare generic",
        rule="§4.2 a generic type needs its arguments",
        patches=[
            Patch(
                target="types.sdl.yaml:Bad",
                action=ADD,
                value={"id": "Bad", "version": "1.0.0", "type": "List"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E406",
    ),
    Recipe(
        name="declare an enum with a repeated value",
        rule="§4.2 the values of an enum are distinct",
        patches=[
            Patch(
                target="types.sdl.yaml:Status",
                action=ADD,
                value={"id": "Status", "version": "1.0.0", "enum": ["a", "a"]},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E211",
    ),
    # -- interfaces and implementations (spec sections 5 and 6) --------------
    Recipe(
        name="add a method the implementation does not have",
        rule="§5.3.1 every method of the interface must be implemented",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods",
                action=ADD,
                value={
                    "id": "farewell",
                    "version": "1.0.0",
                    "inputs": {"name": "String"},
                    "outputs": {"type": "String"},
                },
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E604",
    ),
    Recipe(
        name="add a method and implement it",
        rule="§5.3.1 every method of the interface must be implemented",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods",
                action=ADD,
                value={
                    "id": "farewell",
                    "version": "1.0.0",
                    "inputs": {"name": "String"},
                    "outputs": {"type": "String"},
                },
            )
        ],
        setup=setup_with_farewell_implementation,
        expect="accepted",
        version="1.1.0",
    ),
    Recipe(
        name="widen the input of a method to an optional",
        rule="§5.2 the input of the contract must be accepted by the implementation",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={"name": "Optional<String>"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E604",
    ),
    Recipe(
        name="change the output of a method to an optional",
        rule="§5.2 the output of the implementation must satisfy the contract",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].outputs",
                action=REPLACE,
                value={"type": "Optional<Greeting>"},
            )
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="add a parameter the client cannot omit",
        rule="§5.2 an added parameter must be optional",
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
        name="rename a parameter of a method",
        rule="§5.2 the names of the parameters are identical",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={"who": "String"},
            )
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="remove a parameter of a method",
        rule="§5.2 a parameter the client supplied is gone",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods[greet].inputs",
                action=REPLACE,
                value={},
            )
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="add a method whose input is Unit",
        rule="§4.2 Unit is not allowed in this position",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:methods",
                action=ADD,
                value={
                    "id": "farewell",
                    "version": "1.0.0",
                    "inputs": {"name": "Unit"},
                    "outputs": {"type": "String"},
                },
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E405",
    ),
    # -- invariants (spec section 4.2.1) -------------------------------------
    Recipe(
        name="declare a valid invariant",
        rule="§4.2.1 an invariant is a logical expression",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:invariants",
                action=ADD,
                value=['name != ""'],
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    Recipe(
        name="declare an invariant that is not an expression",
        rule="§4.2.1 an invariant is a logical expression",
        patches=[
            Patch(
                target="interfaces.sdl.yaml:invariants",
                action=ADD,
                value=["name >>"],
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E504",
    ),
    # -- bindings (spec section 6.2) -----------------------------------------
    Recipe(
        name="bind an interface to a version it does not have",
        rule="§6.2 the version of a binding is compatible with the interface",
        patches=[
            Patch(
                target="project.bindings[Greeter].version",
                action=REPLACE,
                value="9.9.9",
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E603",
    ),
    Recipe(
        name="remove the version of a binding",
        rule="§6.2 the version of a binding is optional",
        patches=[
            Patch(
                target="project.bindings[Greeter].version",
                action=REMOVE,
                value=None,
            )
        ],
        expect="accepted",
        version="1.0.1",
    ),
    # -- identifiers (spec section 4.3) --------------------------------------
    Recipe(
        name="change the identifier of the project",
        rule="§4.3 the identifiers of the components are stable",
        patches=[
            Patch(target="project.id", action=REPLACE, value="renamed_project")
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    Recipe(
        name="change the identifier of a flow step",
        rule="§4.3 the identifiers of the components are stable",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].id",
                action=REPLACE,
                value="greet_again",
            )
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    # -- imports (spec section 4.1) ------------------------------------------
    Recipe(
        name="add an import of a document twice",
        rule="§4.1 an import is declared once",
        patches=[
            Patch(
                target="project.imports",
                action=ADD,
                value={"path": "types.sdl.yaml"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E205",
    ),
    Recipe(
        name="add an import that leaves the project root",
        rule="§4.1 an import stays inside the project root",
        patches=[
            Patch(
                target="project.imports",
                action=ADD,
                value={"path": "../escape.sdl.yaml"},
            )
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E300",
    ),
    # -- schema (envelope and documents) -------------------------------------
    Recipe(
        name="add an unknown field to a flow",
        rule="§2 a document has no field the schema does not declare",
        patches=[
            Patch(target="flow.sdl.yaml:totally_unknown", action=ADD, value=1)
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E203",
    ),
    Recipe(
        name="set a backend mode that does not exist",
        rule="§7.1 the mode is codegen or execute",
        patches=[
            Patch(target="project.backend.mode", action=REPLACE, value="teleport")
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E205",
    ),
    Recipe(
        name="give the project a version that is not semver",
        rule="§8.5 the version of a project is a semver",
        patches=[
            Patch(target="project.version", action=REPLACE, value="not-a-version")
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E220",
    ),
    Recipe(
        name="remove the identifier of an interface",
        rule="§4.3 the identifiers of the components are stable",
        patches=[
            Patch(target="interfaces.sdl.yaml:id", action=REMOVE, value=None)
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E602",
    ),
    # -- backend (spec section 7) --------------------------------------------
    Recipe(
        name="point a nodejs backend at a python implementation",
        rule="§7.2 the target must host the languages of the implementations",
        patches=[
            Patch(target="project.backend.target", action=REPLACE, value="nodejs")
        ],
        expect="rejected",
        phase="semantic",
        code="SDL-E606",
    ),
    Recipe(
        name="build the project in codegen mode",
        rule="§7.1 the mode names how the specification is built",
        patches=[
            Patch(target="project.backend.mode", action=REPLACE, value="codegen")
        ],
        expect="accepted",
        version="1.0.1",
    ),
    # -- proposal protocol (spec section 8) ----------------------------------
    Recipe(
        name="patch the same field twice with different values",
        rule="§8.3 two patches on one target conflict",
        patches=[
            Patch(
                target="flow.sdl.yaml:steps[greet].condition",
                action=ADD,
                value='name != ""',
            ),
            Patch(
                target="flow.sdl.yaml:steps[greet].condition",
                action=ADD,
                value='name == ""',
            ),
        ],
        expect="rejected",
        phase="policy",
        code="SDL-E704",
    ),
    Recipe(
        name="patch a field that does not exist",
        rule="§8.3 the target of a patch must resolve",
        patches=[
            Patch(target="project.policy.nowhere", action=REPLACE, value=True)
        ],
        expect="rejected",
        phase="referential",
        code="SDL-E701",
    ),
    Recipe(
        name="a proposal with no patch changes nothing",
        rule="§8.5 a proposal with no change merges nothing",
        patches=[],
        expect="accepted",
        version="1.0.0",
    ),
]
