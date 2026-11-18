# SDL Core 1.0 - Foundation Specification

This document defines the architectural and semantic foundations of SDL v1.0. It is the final stable spec used for the Production Readiness certification.

Status: Frozen / Stable.
This document extends the foundations from 0.2, introducing flow semantics, interface compatibility, and LLM protocols. 1.0 assumes that all rules from 0.2 (YAML subset, types, imports) are satisfied.


## 0. Versioning

The **envelope version** of an SDL document is the value of its `sdl` field. For SDL Core 1.0 it is exactly `"1.0"`.

```yaml
sdl: "1.0"
kind: flow
```

The envelope version always equals the SDL Core version. This is the same convention introduced in 0.2 (§9 of the 0.2 specification), which migrated `sdl: "0.1"` to `sdl: "0.2"`.

**Note on 0.3.** Core 0.3 was renamed to Core 1.0 during the 0.3 development cycle. The rename was not propagated to the envelope string, and documents written during that period carry `sdl: "0.3"`. Since 1.0 is the first stable release, `sdl: "0.3"` is **not** a valid envelope for Core 1.0. The historical specification text is preserved in `archive/specs/sdl-core-0.3.md`; the complete list of differences is in `spec/sdl-core-1.0-changelog.md`.


## 1. Scope of 1.0

In scope:
- **Flow Semantics**: Declarative description of operation sequences (flows).
- **Data-flow**: Rules for transferring data between steps.
- **Compatibility**: Rules for `implements` and subtypes.
- **Implementations**: Linking interfaces to a backend.
- **LLM Proposal Protocol**: Formal format for change proposals.

## 2. Flow Documents

A Flow is a specialized solution for defining business logic that connects multiple functions/methods into a single process.

### 2.1 Envelope and Structure

Flow documents use `sdl: "1.0"` and `kind: flow`.

```yaml
sdl: "1.0"
kind: flow

flow:
  id: process_payment
  version: "1.0.0"

  inputs:
    order_id: UUID
    amount: Decimal

  steps:
    - id: validate_order
      call: order_service::validate
      mapping:
        id: order_id
      output_map:
        status: result

    - id: charge_card
      call: payment_gateway::charge
      mapping:
        amount: amount
        token: status.payment_token
      condition: status.is_valid == true
      output_map:
        tx_id: result.transaction_id

  outputs:
    success: Boolean
    transaction_id: UUID

  output_mapping:
    success: status.success
    transaction_id: tx_id
```

### 2.2 Flow Components

#### 2.2.1 Inputs and Outputs
- `inputs` and `outputs` are mappings where keys are variable names in the **Flow State**, and values are type expression strings (from 0.2).
- `output_mapping` is a mandatory mapping for any flow with defined `outputs`. It defines how the final outputs are populated from the Flow State at the end of execution.
  - Example: `success: status.success` means the final output `success` receives the value of `status.success` from the state.
- Flow State is a temporary data container that lives during the flow execution.

#### 2.2.2 Step
Every step in the `steps` list MUST define:
- `id`: A unique identifier for the step within the flow (snake_case).
- `call`: A reference to a function or method (qualified name from 0.2).

Optional fields:
- `mapping`: Maps values from Flow State to function/method input parameters.
- `output_map`: Maps output parameters of the function/method back into Flow State.
- `condition`: A logical expression determining whether the step will be executed.
- `on_error`: Error handling strategy for the step.

### 2.3 Data-flow and Mapping

Data-flow in SDL is **explicit mapping**. There is no implicit glue logic.

#### 2.3.1 Input Mapping
In the `mapping` field, the key is the function parameter name, and the value is the path to the data in Flow State.
- `amount: amount` $\rightarrow$ parameter `amount` receives the value of variable `amount` from state.
- `token: status.payment_token` $\rightarrow$ parameter `token` receives the value of field `payment_token` from the `status` object in state.

#### 2.3.2 Output Mapping
In the `output_map` field, the key is the variable name in Flow State, and the value is the path to the function output data.
- `status: result` $\rightarrow$ the entire function output is placed in the `status` variable.
- `tx_id: result.transaction_id` $\rightarrow$ only the `transaction_id` field from the output is placed in `tx_id`.

#### 2.3.3 Data-flow Validation Rules
1. **Type Compatibility**: The data type in Flow State MUST be assignable to the function parameter type (per 0.2 §6.7 rules).
2. **Existence**: Every variable used in `mapping` must be defined in `inputs` or previously created in an `output_map` of an earlier step.
3. **Non-contextuality**: A step cannot directly access the internal state of a function, only what is explicitly mapped.

## 3. Control Flow

### 3.1 Sequentiality
Steps are executed strictly in the order they are defined in the `steps` list.

### 3.2 Conditional Execution (Branching)

The `condition` field allows skipping steps based on the current state of the Flow State.

#### 3.2.1 Expression Grammar

Expressions in the `condition` field follow this grammar:

```ebnf
expr       := logical_or ;
logical_or := logical_and { "||" logical_and }
logical_and := unary { "&&" unary }
unary      := "!" unary | comparison
comparison := operand ( "==" | "!=" | ">" | "<" | ">=" | "<=" ) operand
operand    := variable | literal
variable   := path_to_state
literal    := string_lit | number_lit | bool_lit
```

- `path_to_state` follows the rules from §2.3 (e.g., `status.is_valid`).
- `string_lit` are quoted strings; `number_lit` are decimal numbers; `bool_lit` are `true` or `false`.

#### 3.2.2 Comparison Semantics

Every comparison operator requires both operands to be compatible types:
- **Equivalence (`==`, `!=`)**: Operands must be assignable to the same type per 0.2 §6.7.
- **Ordering (`>`, `<`, `>=`, `<=`)**: Permitted only for `Int`, `Float`, `Decimal`, `String`, `Date`, `DateTime`.
- **Logical Value**: The `unary` operator `!` applies only to expressions resulting in `Boolean`.

If types are not compatible, the validator emits error `SDL-E501` (Type mismatch in condition).

### 3.3 Errors in Flow

If a function called in a step returns `Result<T, E>` and the result is `E` (error), the flow is terminated by default and emits a final output with error status.

#### 3.3.1 Error Handling (`on_error`)

Every step MAY define an `on_error` strategy:

- `on_error: ignore` — The error is ignored, the step is considered completed without changing Flow State, and control passes to the next step.
- `on_error: retry` — The step is repeated according to a retry policy.
- `on_error: goto <step_id>` — The flow immediately jumps to the step with the specified ID.
- `on_error: fail` — (Default) The flow is terminated and returns an error.

#### 3.3.1.1 Retry Policy
When `on_error: retry` is used, the step configuration MUST include a `retry` block:
```yaml
retry:
  attempts: 3            # Total number of attempts including the initial one.
  backoff: exponential  # Strategies: fixed | linear | exponential.
  initial_interval: 1s   # Time between first and second attempt.
  max_interval: 30s      # Upper bound for exponential backoff.
```

#### 3.3.2 Final Output in case of error

When a flow terminates due to an error, the final `outputs` are populated as follows:
- All fields that are `Optional<T>` or `Result<T, E>` receive values reflecting the error.
- **Mandatory Output Check**: A flow is considered to have failed if any mandatory field in `outputs` cannot be populated via the `output_mapping` using the current Flow State. In this case, the flow returns a system-level execution error.

## 4. Constraints & Guardrails

SDL introduces the concept of explicit prohibitions to prevent architectural degradation and ensure LLMs do not propose solutions that violate fundamental system principles. A prohibition is normatively stronger than a rule; violating a prohibition MUST result in the immediate rejection of the specification.

### 4.1 Architectural Prohibitions (Layering Constraints)

At the project or module level, constraints can be defined on who may and may NOT import certain components. This prevents "spaghetti" architecture.

#### 4.1.1 Forbidden Imports

In the project document, a `constraints` section is introduced:

```yaml
constraints:
  forbidden_imports:
    - from: ui_layer
      deny: [database_layer, infrastructure_layer]
      reason: "UI layer must be decoupled from data access logic."
    - from: core_domain
      deny: [external_api_clients]
      reason: "Domain logic must not depend on external API implementation."
```

- `from`: ID of the restricted module.
- `deny`: List of module IDs forbidden for import.
- `reason`: Mandatory field explaining the prohibition.

**Validation**: If any module from the `from` list attempts to `import` a module from `deny`, the validator emits error `SDL-E601` (Layering Violation).

### 4.2 Semantic Invariants (State Invariants)

Invariants are rules that MUST be true at all times for a specific type or interface. They serve as "contractual prohibitions" for values.

#### 4.2.1 Defining Invariants

Invariants are added to the definition of a class or interface:

```yaml
interface:
  id: AccountService
  version: "1.0.0"
  invariants:
    - "balance >= 0"
    - "currency != null"
  methods:
    - id: withdraw
      # ...
```

- `invariants` is a list of logical expressions (using the grammar from §3.2).
- Every implementation of this interface MUST guarantee that these values never contradict the rules.

**Validation**: While runtime verification is done in the implementation, the 1.0 validator checks that invariants are syntactically correct and use available fields.

### 4.3 Procedural Prohibitions (Evolution Constraints)

These are rules that limit how the specification may be changed, especially when changes are proposed by an LLM.

#### 4.3.1 Proposal Policy

A `policy` is defined in the project document:

```yaml
policy:
  disallow_breaking_changes: true
  require_migration_for_type_change: true
  forbidden_id_changes: true
```

- `disallow_breaking_changes`: If `true`, any change that changes a signature of an existing function (removing a parameter, changing type) is forbidden without incrementing the interface version.
- `require_migration_for_type_change`: If a type definition is changed, the LLM MUST simultaneously propose a migration plan for all dependent modules.
- `forbidden_id_changes`: Forbids changing the `id`s of existing components (as this breaks all references in the system).

**Validation**: These prohibitions are checked during the "Diff" phase (comparison of old and new versions of the specification) before a proposal is accepted. Error: `SDL-E602` (Policy Violation).

## 5. Interface Compatibility

An interface **A** is compatible with interface **B** (notation: $A \preceq B$) if:
1. Every method defined in interface **B** exists and is also in interface **A**.
2. All method signatures in **A** are compatible with corresponding signatures in **B** per the rules in §5.2.

### 5.2 Method Signature Compatibility

Method $M_A$ (in implementation) is compatible with method $M_B$ (in contract/interface) if the following conditions are met:

1. **Identity**: Method names MUST be identical.
2. **Output Covariance**: The output type $T_{out\_A}$ MUST be assignable to $T_{out\_B}$ per 0.2 §6.7. 
   - *Intuition*: Implementation may return a more specific type (a consumer expecting `Payment` will be satisfied if they receive `StripePayment`).
3. **Input Contravariance**: For every parameter, the required input type $T_{in\_B}$ MUST be assignable to the type the implementation actually accepts $T_{in\_A}$.
   - *Intuition*: Implementation must be able to process everything the client can send. If the client sends `Decimal`, the implementation must not require `PositiveDecimal` (which is a narrower type), but must accept at least `Decimal` or some more general type (e.g., `Number`).

**Example:**
If interface **B** defines: `charge(amount: Decimal) -> Result<Payment, Error>`
Implementation **A** is compatible if it defines:
- `charge(amount: Decimal) -> Result<StripePayment, Error>` (Covariance: `StripePayment` $\preceq$ `Payment`).
- `charge(amount: Number) -> Result<Payment, Error>` (Contravariance: `Decimal` $\preceq$ `Number`).

### 5.3 Implementation Rules (`implements`)

When a class or module uses the keyword `implements` for a specific interface, the validator MUST check:

1. **Completeness**: All methods defined in the interface MUST be defined in the implementation.
2. **Signature Correctness**: Every implemented method MUST be compatible with the original per §5.2.
3. **Additions**: Implementation MAY define additional methods that do not exist in the interface; this does not affect compatibility, but these methods are not available to a client using an interface reference.

### 5.4 Version Compatibility

Compatibility is checked in combination with semver ranges from 0.2 §4.5:

- Implementation version $V_{impl}$ is compatible with requirement $R_{req}$ if:
  - $V_{impl}$ falls within range $R_{req}$.
  - All methods of the implementation are compatible with the methods of the interface in that version.
- **Breaking Changes**: Any change that violates the rules in §5.2 (e.g., changing the output type to an incompatible one) MUST result in incrementing the **MAJOR** version of the interface.

## 6. Implementations and Bindings

While an interface defines "what" the system must do, an implementation defines "how" it is done in a specific programming language. A binding is the process of final connection between the contract and the realization.

### 6.1 Implementation

An implementation is a concrete realization of one or more interfaces. It represents the "bridge" between the SDL abstraction and the source code.

#### 6.1.1 Implementation Structure

An implementation is defined within a module or as a separate `kind: implementation` document.

```yaml
sdl: "1.0"
kind: implementation

implementation:
  id: stripe_payment_provider
  version: "1.2.0"
  
  implements:
    - interface: PaymentProvider
      version: "1.0.0"
      
  language: python
  
  source:
    file: src/infrastructure/payments/stripe.py
    symbol: StripeProvider # Class or function that realizes the interface
```

**Rules:**
1. **Identity**: `id` MUST be unique in the scope.
2. **Contract**: `implements` MUST be a list of references to interfaces. Every interface on the list MUST be compatible with the implementation per the rules in §5.
3. **Language**: `language` MUST be a valid language identifier (e.g., `python`, `rust`, `typescript`).
4. **Source**: `source` MUST define `file` (path relative to the root) and `symbol` (name of the class/function).

### 6.2 Binding System

Binding is a configuration layer found exclusively in the **project document**. It allows replacing implementations without changing the code of modules that use the interfaces (Dependency Inversion).

#### 6.2.1 Defining Bindings

In the `kind: project` document, a `bindings` section is introduced:

```yaml
sdl: "1.0"
kind: project

project:
  id: shop_system
  version: "1.0.0"
  
  # ... other fields ...

  bindings:
    - interface: PaymentProvider
      version: "1.0.0"
      implementation: stripe_payment_provider
      
    - interface: StorageService
      version: "2.1.0"
      implementation: aws_s3_storage
```

**Rules:**
1. **Exclusivity**: For one interface in one version, there can be only one active binding per project.
2. **Validation**: The validator MUST check that the specified `implementation` actually implements the requested `interface` and that the version is compatible.
3. **Resolution**: When a module calls a method of an interface, the runtime/codegen uses the `bindings` table to determine which concrete code to execute.

### 6.3 Replacement Lifecycle (Hot-swapping)

One of the main advantages of SDL is the ability to replace implementation without changing business logic:
1. developer creates a new implementation `paypal_payment_provider`.
2. developer checks compatibility with the `PaymentProvider` interface.
3. developer changes only one line in the `bindings` section of the project document.
4. The system is recompiled/restarted with the new provider.

## 7. Backend and Build Configuration

The backend defines how the SDL specification is transformed into an executable system.

### 7.1 Backend Targets

The project document MAY define `backend` configuration:

```yaml
backend:
  target: python
  mode: codegen
  options:
    optimize: true
    strict_typing: true
```

**Permitted modes (`mode`):**
- `codegen`: The SDL generator creates complete source files in the target language.
- `execute`: The SDL runtime directly executes flows and calls implementations via dynamic binding (interpreter).

### 7.2 Build Profiles

Projects may have multiple builds for different environments (e.g., `dev`, `prod`).

```yaml
builds:
  - id: development
    target: python
    mode: execute # Faster iterations without generating code
    bindings_override:
      - interface: PaymentProvider
        implementation: mock_payment_provider
        
  - id: production
    target: python
    mode: codegen # Maximum performance
    bindings_override:
      - interface: PaymentProvider
        implementation: stripe_payment_provider
```

**Rules:**
- `bindings_override` allows defining different implementations for different environments.
- `target` must be compatible with the languages of all used implementations in that build.
In SDL, compatibility is not just name matching, but a semantic guarantee that the implementation can take over the role of the interface without breaking the system.

## 8. LLM Proposal Protocol

### 8.1 Purpose and Concept

LLMs must not directly change the specification. Instead, they generate a **Proposal** document that serves as a formal request for change. A proposal is treated as a "transaction" that must pass through strict validation before being merged into the main SDL.

### 8.2 Proposal Envelope

A proposal document uses `sdl: "1.0"` and `kind: proposal`.

```yaml
sdl: "1.0"
kind: proposal

proposal:
  id: prop_pay_v2_migration
  target_version: "1.0.0"
  author: "agent-gemma4"
  rationale: "Migration to PaymentProvider v2 for improved security and 3DS2 support."
  
  patches:
    - target: "project.bindings[PaymentProvider]"
      action: replace
      value:
        interface: PaymentProvider
        version: "2.0.0"
        implementation: stripe_v2_provider
        
    - target: "module.payment_logic.imports"
      action: add
      value: "payment_v2_types"
```

### 8.3 Patch Semantics

Patches use paths to specification elements to precisely define what is changed:
- `target`: Path to the element (syntax: `object.field` or `list[index]`).
- `action`:
    - `replace`: Replaces the existing value with a new one.
    - `add`: Adds a new element to a list or a new field to an object.
    - `remove`: Removes the specified element.
- `value`: The new value or object structure to be applied.

### 8.4 Proposal Validation Process

Every proposal MUST pass through four validation phases before application:

1. **Syntactic Validation**: Checks if the proposal document is valid YAML and follows the schema for `kind: proposal`.
2. **Referential Validation**: Checks if all new IDs and references in `value` fields exist in the current specification or are defined within the same proposal.
3. **Policy Check**: Checked against the `policy` section of the project document (§4.3).
    - If `disallow_breaking_changes: true`, and the patch changes the signature of an existing method $\rightarrow$ REJECTED.
    - If `forbidden_id_changes: true`, and the patch changes the `id` of an existing component $\rightarrow$ REJECTED.
4. **Semantic Simulation**: Generation of a "virtual" new version of the specification (Current + Proposal) and running the reference validator. If the virtual specification violates any rule from 0.2 or 1.0 $\rightarrow$ REJECTED.

### 8.5 Acceptance and Merge

A proposal is considered valid only if all validation phases pass without errors.

Final acceptance is performed by an administrator (human or supervisor agent) who confirms `approve: true`. After that, the patches are applied to the primary source, and the project version is incremented according to semver rules (e.g., MAJOR if the proposal introduced an explicitly permitted breaking change).

## 9. Canonical IR (Intermediate Representation)

### 9.1 IR Concept

The Canonical IR is a stable, immutable format into which an SDL specification is "lowered" before it is converted into concrete source code or executed in a runtime. The purpose of the IR is to eliminate all YAML specificities and create a strictly typed graph of dependencies and operations.

### 9.2 IR Structure

The IR is organized as a collection of **Symbols** and **Edges** (relations).

#### 9.2.1 Symbols

Every element in SDL becomes a Symbol in the IR:
- `S_Project`: Root of the system, contains global configurations and bindings.
- `S_Module`: Logical unit grouping a connected set of types and functions.
- `S_Interface`: Contract defining a set of methods and their invariants.
- `S_Method`: Function signature containing precise definitions of inputs, outputs, and effects.
- `S_Type`: Type definition (from base scalars to complex compound types).
- `S_Flow`: Execution graph of steps with explicit data-flow mapping.

#### 9.2.2 Edges (Relations)

Relations in the IR are explicit and strictly defined:
- `DEPENDS_ON`: Module $\rightarrow$ Module (marks import dependency).
- `IMPLEMENTS`: Implementation $\rightarrow$ Interface (marks contract realization).
- `CALLS`: Method/Flow-step $\rightarrow$ Method (marks call).
- `RETURNS`: Method $\rightarrow$ Type (marks return type).
- `HAS_PARAMETER`: Method $\rightarrow$ Type (marks input parameter).

### 9.3 Lowering Process (SDL $\rightarrow$ IR)

The process of lowering from YAML specification to IR is performed in three phases:
1. **Flattening**: All imports are resolved, and qualified names (FQN) are converted to unique pointers in the IR.
2. **Type Resolution**: All types are checked for consistency; aliases are replaced with their base types (transparency).
3. **Binding Injection**: Values from the `bindings` section of the project document are injected into the IR so that `S_Interface` is connected to a concrete `S_Implementation`.

### 9.4 IR as Source of Truth for Codegen

Codegen tools do not read YAML files directly, but operate exclusively over the IR. This ensures:
- **Determinism**: The same IR always generates an identical source code.
- **Neutrality**: The IR is independent of any specific programming language or LLM model.
- **Validation**: Checks for compatibility and prohibition violations are performed on the IR, which is formally safer than text analysis.
