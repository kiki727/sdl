# The hello example

The smallest complete SDL project. It has a type, an interface, an
implementation, a flow and a project, and it runs the whole chain:

```
.sdl.yaml  ->  validate  ->  compile  ->  canonical IR  ->  execute
```

## The files

| File | What it is |
| :--- | :--- |
| `project.sdl.yaml` | the root: imports, bindings, policy, backend |
| `types.sdl.yaml` | the `Greeting` type |
| `interfaces.sdl.yaml` | the `Greeter` contract and its `greet` method |
| `implementations.sdl.yaml` | the realization, and where its code lives |
| `flow.sdl.yaml` | the business logic: greet someone by name |
| `src/greeter.py` | the code of the realization |
| `proposal_valid.sdl.yaml` | a change that passes every phase |
| `proposal_broken_reference.sdl.yaml` | a change that breaks a reference |
| `proposal_forbidden_id_change.sdl.yaml` | a change the policy forbids |

## Try it

Validate the documents:

```powershell
python -m sdl validate examples/hello/project.sdl.yaml
```

Compile the project into the canonical IR and the generated source:

```powershell
python -m sdl build examples/hello/project.sdl.yaml --out generated/hello
```

Execute the flow:

```powershell
python -m sdl run examples/hello/project.sdl.yaml --flow greet_someone --input name=Amir
```

```
The flow greet_someone returned:
  message = 'Hello, Amir!'
```

Run the three proposals:

```powershell
python -m sdl propose examples/hello/proposal_valid.sdl.yaml
python -m sdl propose examples/hello/proposal_broken_reference.sdl.yaml
python -m sdl propose examples/hello/proposal_forbidden_id_change.sdl.yaml
```

The first one is accepted, but nothing is merged until it carries
`approve: true`. The second one is rejected in the semantic phase, because the
virtual specification calls something that does not exist. The third one is
rejected in the policy phase, because the policy of the project forbids
changing the identifiers of existing components.

## The bindings

The flow never imports the implementation. It names the interface:

```yaml
steps:
  - id: greet
    call: Greeter::greet
```

and the runtime resolves `Greeter` through the bindings of the project:

```yaml
bindings:
  - interface: Greeter
    version: "1.0.0"
    implementation: greeter_impl
```

Replacing the implementation is therefore a change of one line in the project
document, and nothing in the business logic moves.
