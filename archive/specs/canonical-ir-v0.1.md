# SDL Canonical IR Specification (v0.1)

The Canonical IR is a **Typed, Attributed, Directed Symbol Graph**. It is the single source of truth for the SDL ecosystem.

## 1. Pipeline Architecture
`YAML` $\rightarrow$ `AST` $\rightarrow$ `Parsed IR` $\rightarrow$ `Resolved IR` $\rightarrow$ `Validated IR` $\rightarrow$ `Backends`

## 2. The Symbol Model
Every entity in the system is a **Symbol** with a unique `SymbolId` and a `qualified_name`.

| Symbol Kind | Description |
| :--- | :--- |
| `Project` | Root node. Contains settings, bindings, and modules. |
| `Module` | A namespace containing types, interfaces, and methods. |
| `Interface` | A contract defining method signatures and invariants. |
| `Method` | A function definition (Inputs $\rightarrow$ Output). |
| `Type` | A type definition (Scalar, Compound, Generic). |
| `Implementation` | A concrete code realization of an interface. |
| `Flow` | A state-machine for business logic orchestration. |
| `FlowStep` | A single operation within a flow. |

## 3. The Edge Model (Relations)
Relations between symbols define the semantic meaning of the system.

| Edge Kind | Source $\rightarrow$ Target | Meaning |
| :--- | :--- | :--- |
| `CONTAINS` | `Project/Module` $\rightarrow$ `Any` | Structural membership. |
| `IMPLEMENTS` | `Implementation` $\rightarrow$ `Interface` | Fulfills a contract. |
| `CALLS` | `Method/FlowStep` $\rightarrow$ `Method` | Hard dependency/execution flow. |
| `RETURNS` | `Method` $\rightarrow$ `Type` | Output type definition. |
| `HAS_PARAMETER`| `Method` $\rightarrow$ `Type` | Input type definition. |
| `DEPENDS_ON` | `Module` $\rightarrow$ `Module` | Import dependency. |
| `HAS_STEP` | `Flow` $\rightarrow$ `FlowStep` | Flow composition. |
| `NEXT` | `FlowStep` $\rightarrow$ `FlowStep` | Execution sequence. |
| `INPUT_BINDING`| `FlowStep` $\rightarrow$ `Symbol` | Maps state to parameter. |
| `OUTPUT_BINDING`| `FlowStep` $\rightarrow$ `Symbol` | Maps result to state. |

## 4. Validation States
- **Parsed**: Syntax is correct.
- **Resolved**: All string references are converted to `SymbolId` edges.
- **Validated**: Semantic rules (Type compatibility, architectural prohibitions) are satisfied.
