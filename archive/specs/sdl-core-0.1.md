# SDL Core 0.1 – Formal Specification

Status: Working Draft. Formal YAML schema, parser, and validator are not yet completed (see §17).

Architecture decisions established Draft specification

Based on the chosen decisions, SDL is defined as a hybrid, declarative-structural language for software specification, construction, and execution.

This is a critical decision: SDL will not be just a format for passing instructions to an LLM. It will be a standalone software specification, allowing different tools to operate on the same program model.

The following rules are established:

| Area | Decision |
| --- | --- |
| Modes | Project and Modular levels |
| Source Code | Inline and external files |
| Types | Explicit + proposed inference |
| Backend | Code generation and runtime |
| Syntax | YAML as the initial syntax |
| Internal Model | Independent of YAML |
| Validation | No mandatory LLM |

## 1. Formal SDL Model

An SDL program has the following hierarchy:

```text
SDL Project
│
├── Project Configuration
│
├── Imports
│
├── Types
│
├── Interfaces
│
├── Modules
│   ├── Module Configuration (mode, intent, requires, provides)
│   ├── Imports
│   ├── Interfaces
│   ├── Types
│   ├── Classes
│   ├── Functions
│   ├── Flows
│   ├── Requirements
│   ├── Constraints
│   └── Expected Behavior
│
├── Bindings
│
├── Requirements
│
├── Constraints
│
└── Backend Configuration
```

I propose a distinction between three concepts:

- Declaration: What exists in the program.
- Definition: What a specific element represents and how it is defined.
- Implementation: How the element is realized.

For example, a function declaration does not need to contain its body. The definition determines its inputs, outputs, and behavior, while the implementation could be Python code, Rust code, or SDL runtime logic.

## 2. Operating Modes

A mode can be defined at the project level, module level, and eventually for individual elements.

Two basic modes are defined:

```yaml
mode: structural
```

and

```yaml
mode: declarative
```

### Inheritance Rules

1. If the project defines a mode, modules inherit it.
2. A module can explicitly override the inherited mode.
3. An element can have its own mode if allowed by its type.
4. If no mode is defined, `structural` is the default mode.

Example:

```yaml
sdl: "0.1"
kind: project

project:
  id: shop
  mode: structural

  imports:
    - path: modules/catalog.sdl.yaml
    - path: modules/recommendations.sdl.yaml
```

The `catalog` module inherits `structural`, while the `recommendations` module explicitly sets `mode: declarative` in its document.

Important rule: the mode determines how the specification is interpreted, not whether the LLM is allowed to change already defined contracts.

In declarative mode, the LLM can propose architecture, types, and implementations, but proposals must be marked and approved before they become accepted parts of the specification.

## 3. Project Structure and Documents

Every SDL document must have a language version and a defined document type.

The proposed standard layout:

```text
project/
│
├── sdl.yaml
│
├── modules/
│나 ├── catalog.sdl.yaml
│   ├── users.sdl.yaml
│   └── orders.sdl.yaml
│
├── interfaces/
│   ├── storage.sdl.yaml
│   └── payment.sdl.yaml
│
├── types/
│   └── common.sdl.yaml
│
├── implementations/
│   ├── catalog.py
│   └── payment.rs
│
└── builds/
    └── production.sdl.yaml
```

Main document:

```yaml
sdl: "0.1"
kind: project

project:
  id: shop
  name: Shop Application
  version: "1.0.0"
  mode: structural

  language:
    primary: python

  imports:
    - path: modules/catalog.sdl.yaml
    - path: modules/users.sdl.yaml
    - path: modules/orders.sdl.yaml

  backend:
    target: python
    mode: codegen
```

`kind` defines the type of SDL document. For Core 0.1, I propose:

- `project`
- `module`
- `interface`
- `types`
- `implementation`
- `build`

This allows each document to be self-contained while remaining connected to others.

## 4. Import and Dependency System

Imports and dependencies should not be synonyms.

- Import provides access to definitions from another document or package.
- Dependency indicates that a component relies on the functionality of another component.

At the project level, `imports` uses `path` to import SDL documents; at the module level, it uses `module` for other SDL modules and `package` for external libraries.

Example:

```yaml
sdl: "0.1"
kind: module

module:
  id: orders
  mode: structural

  imports:
    - module: common.types

    - package: sqlalchemy
      version: ">=2.0,<3.0"

  requires:
    - interface: PaymentProvider
      version: "1.0"

  provides:
    - interface: OrderService
      version: "1.0"
```

SDL must distinguish between:

| Type | Example | Meaning |
| --- | --- | --- |
| SDL module | `module` | Another SDL document |
| External package | `package` | Library from the language ecosystem |
| Interface | `interface` | Contract being used |
| Resource | `resource` | External system or resource |

Additionally, the dependency resolver must check:

- Existence of the module.
- Versions.
- Availability of libraries.
- Interface compatibility.
- Circular dependencies.

## 5. Interface and Binding System

This should be one of the most strictly defined parts of the language.

An interface defines the public behavior of a component.

Example:

```yaml
sdl: "0.1"
kind: interface

interface:
  id: PaymentProvider
  version: "1.0"

  methods:
    - id: charge

      input:
        amount: Decimal
        currency: String

      output:
        type: Result<Payment, PaymentError>

      execution:
        async: true
```

Implementation:

```yaml
sdl: "0.1"
kind: module

module:
  id: stripe_adapter

  provides:
    - interface: PaymentProvider
      version: "1.0"

  classes:
    - id: StripePaymentProvider

      implements:
        - PaymentProvider

      implementation:
        language: python
        source:
          file: implementations/stripe.py
```

Binding in the project document:

```yaml
bindings:
  - interface: PaymentProvider
    version: "1.0"
    implementation: stripe_adapter.StripePaymentProvider
```

This achieves the separation of three things:

1. What the system expects.
2. Which component provides it.
3. How that component is implemented.

Compatibility rule: the implementation must satisfy all mandatory methods, types, conditions, and effects of the interface. Name matching alone is not sufficient.

## 6. Function Implementation

Since both approaches were chosen, SDL must support two types of implementation.

### A. Inline implementation

```yaml
function:
  id: calculate_total

  input:
    prices: List<Decimal>

  output:
    type: Decimal

  implementation:
    language: python
    inline: |
      return sum(prices)
```

### B. External implementation

```yaml
function:
  id: calculate_total

  input:
    prices: List<Decimal>

  output:
    type: Decimal

  implementation:
    language: python
    source:
      file: src/calculations.py
      symbol: calculate_total
```

The following rule should be defined:

- `inline` contains the source code directly in the SDL document.
- `source` references an external implementation.
- One implementation is active for a specific backend and build configuration.
- If multiple implementations exist, the choice must be explicit.

Inline code is not SDL syntax, but content intended for a specific programming language. Therefore, the parser treats it as an uninterpreted block of source code, while the corresponding backend processes it.

## 7. Type System and Inference

I propose three categories of types:

**Explicit** – explicitly defined type

Defined directly by the programmer. It has the highest authority.

```yaml
input:
  user_id: UUID
```

**Inferred** – proposed type

The LLM or an analyzer concluded which type should be used.

```yaml
input:
  user_id:
    type: UUID
    origin: inferred
    confidence: 0.95
```

**Unresolved** – undefined type

The type is not yet known and requires a decision or further analysis.

```yaml
input:
  user_id:
    type: unresolved
```

I propose that SDL has an information origin system:

```yaml
metadata:
  origin: llm
  status: proposed
```

An LLM can propose a type, but cannot unilaterally change an explicit type.

Also, `confidence` is informative data, not proof of type correctness.

For Core 0.1, types must be statically verifiable before code generation. Dynamic inference during execution can be a separate feature of a future runtime.

## 8. Requirements and Constraints

I distinguish between two concepts.

Requirement describes what the system must achieve.

Constraint describes the limitation within which the system must operate.

Example:

```yaml
requirements:
  - id: REQ-001
    description: Users can create orders.
    priority: high

  - id: REQ-002
    description: Orders must be stored permanently.

constraints:
  - id: CON-001
    rule: Database access only through repository interfaces.

  - id: CON-002
    rule: Payment operations must be asynchronous.
```

Unlike plain text, I would later support formal conditions:

```yaml
constraints:
  - id: CON-003
    expression: order.total >= 0
    scope: Order
    enforcement: runtime
```

Thus, the LLM can understand the intent, while the validator can check formalized conditions.

It is important that free text is not automatically treated as an executable rule.

## 9. Flow and Execution Model

I propose that Flow in SDL be independent of the programming language.

Basic elements:

| Element | Function |
| --- | --- |
| `call` | Call a function |
| `condition` | Branching |
| `loop` | Repetition |
| `parallel` | Parallel execution |
| `await` | Wait for result |
| `return` | Return value |
| `raise` | Error |
| `handle` | Error handling |

Example:

```yaml
flow:
  id: create_order

  input:
    user_id: UUID
    items: List<OrderItem>

  steps:
    - id: validate
      call: OrderService.validate

    - id: calculate
      call: PricingService.calculate
      after: validate

    - id: payment
      call: PaymentProvider.charge
      after: calculate

    - id: save
      call: OrderRepository.save
      after: payment

  output:
    type: Order

  on_error:
    action: propagate
```

For Core 0.1, the meaning of `after`, dependencies between steps, execution order, and error propagation must be formally defined.

The order of YAML elements must not accidentally determine the semantics of the program.

## 10. Backend Architecture

Since SDL should support both source code generation and its own runtime, I propose a common backend interface.

```yaml
backend:
  target: python
  mode: codegen
```

Or:

```yaml
backend:
  target: sdl-runtime
  mode: execute
```

Two primary backend types are defined:

### Code Generation Backend

Converts SDL IR into source code of the target language.

```text
SDL YAML
   ↓
SDL Parser
   ↓
SDL IR
   ↓
Python Backend
   ↓
Python Source Code
```

### SDL Runtime Backend

Executes the program via the SDL runtime, without mandatory generation of complete source code.

```text
SDL YAML
   ↓
SDL Parser
   ↓
SDL IR
   ↓
SDL Runtime
   ↓
Program Execution
```

The runtime could execute SDL Flows, call function implementations, manage modules, and handle interfaces.

In Core 0.1, I would not attempt to define a complete runtime. I would only define its contract and expected behavior.

## 11. LLM Interpretation Protocol

This is perhaps the most interesting part of the whole project.

I propose that the LLM does not work directly on arbitrary YAML text when precise interpretation is required.

Instead:

1. The Parser converts YAML to SDL IR.
2. The Validator checks formal correctness.
3. The LLM receives a normalized specification.
4. The LLM returns a structured proposal.
5. The Validator checks the proposal.
6. The programmer accepts or rejects changes.

Four statuses are defined:

| Status | Meaning |
| --- | --- |
| `specified` | Defined by the programmer |
| `derived` | Deterministically derived |
| `proposed` | Proposed by the LLM |
| `approved` | Accepted and included in the specification |

Example LLM proposal:

```yaml
proposal:
  id: proposal_001

  target: modules/recommendations

  status: proposed

  changes:
    - operation: add
      element: interface
      id: RecommendationProvider

    - operation: add
      element: function
      id: recommend_products

  rationale: |
    The module requires a stable interface
    for product recommendation operations.
```

Every `add` operation must also contain a `value` with the complete definition of the element; it is omitted in the example for readability.

The LLM should not directly change the original specification. It generates a change proposal, i.e., a patch, which can be reviewed, validated, and accepted.

This provides something very useful: the ability to track all changes proposed by the AI.

## 12. Formal Validation Process

I propose that SDL has five phases of validation:

1. Syntax Validation
   Is the YAML correct and does the document follow the SDL structure?
2. Schema Validation
   Are all elements permitted and correctly defined?
3. Semantic Validation
   Do the types, interfaces, and dependencies referred to in the document exist?
4. Consistency Validation
   Are requirements, constraints, implementations, and bindings mutually compatible?
5. Backend Validation
   Is the specification feasible on the selected backend?

Each phase should return structured results:

```yaml
validation:
  status: failed

  errors:
    - code: SDL-E301
      element: PaymentProvider
      message: Interface implementation missing.

  warnings:
    - code: SDL-W102
      element: calculate_total
      message: Type inference proposal not approved.
```

I distinguish between:

- `error` – specification is not valid.
- `warning` – there is a potential problem.
- `info` – additional information.
- `proposal` – suggestion for improvement.

## 13. Extensions and Future Compatibility

SDL must be extensible, but must not become unpredictable.

I propose a namespace system:

```yaml
extensions:
  security:
    version: "1.0"
    schema: extensions/security.schema.json
    authentication: required
    authorization: role_based

  performance:
    version: "1.0"
    schema: extensions/performance.schema.json
    caching: enabled

  llm:
    version: "1.0"
    schema: extensions/llm.schema.json
    generation:
      strategy: conservative
```

Every extension must have:

- A unique namespace.
- A defined version.
- A schema.
- Semantic rules.
- An optional validator or backend adapter.

An unknown extension must not be silently ignored if it affects the correctness or security of the program.

## 14. First Linked SDL Example

We can now combine the previous concepts into one project.

Reference example:

```yaml
sdl: "0.1"
kind: project

project:
  id: task_manager
  name: Task Manager
  version: "1.0.0"
  mode: structural

  language:
    primary: python

  imports:
    - path: modules/users.sdl.yaml
    - path: modules/tasks.sdl.yaml
    - path: modules/notifications.sdl.yaml

  backend:
    mode: codegen
    target: python

  constraints:
    - id: C001
      rule: No circular module dependencies.

  # Binding for NotificationProvider is intentionally omitted until the
  # interface and implementation are proposed and approved (see §16).
```

`tasks` module:

```yaml
sdl: "0.1"
kind: module

module:
  id: tasks
  mode: structural

  imports:
    - module: users

  requires:
    - interface: UserRepository
      version: "1.0"

  provides:
    - interface: TaskService
      version: "1.0"

  types:
    - id: TaskId
      type: UUID

  classes:
    - id: Task

      properties:
        id: TaskId
        title: String
        completed: Boolean
        user_id: UUID

  functions:

    - id: create_task

      input:
        title: String
        user_id: UUID

      output:
        type: Task

      implementation:
        language: python
        source:
          file: implementations/tasks.py
          symbol: create_task
```

`notifications` module:

```yaml
sdl: "0.1"
kind: module

module:
  id: notifications
  mode: declarative

  intent: |
    Provide notification services
    for task-related events.

  requirements:
    - id: REQ-NOTIF-001
      description: Send a notification when a task is created.

    - id: REQ-NOTIF-002
      description: Support email delivery.

    - id: REQ-NOTIF-003
      description: Retry failed deliveries.

  constraints:
    - id: CON-NOTIF-001
      rule: Delivery must be asynchronous.

    - id: CON-NOTIF-002
      rule: Duplicate notifications must be prevented.

  expected_behavior:
    - event: task_created
      result: notification_scheduled

    - event: delivery_failed
      result: retry_scheduled
```

This is an example of how one program can contain both fully defined modules and modules whose architecture is only being proposed.

## 15. Normative Language Rules

For SDL to be a real language, and not just a convention, the obligatoriness of rules must be defined.

Three levels are used:

- MUST – mandatory rule. Violation means invalid specification.
- SHOULD – recommended rule. Deviation must be justified.
- MAY – optional functionality.

Example:

| Rule | Level |
| --- | --- |
| Every module must have a unique ID | MUST |
| Every public method must have a defined output type | MUST |
| Every dependency should be explicit | SHOULD |
| A module may have multiple implementations | MAY |
| LLM may propose types | MAY |
| Unapproved proposals must not change the specification | MUST |

This provides a stable basis for the parser, validator, and LLM integration.

## 16. One Correction to the Reference Example

In the previous example, the binding for `NotificationProvider` was intentionally omitted because its concrete implementation was not yet defined. Interfaces `UserRepository` and `TaskService`, along with their implementations, are defined in separate documents and are not shown here.

Adding a binding before the implementation exists should be treated as a validation error, and the LLM should not be allowed to assume the implementation exists.

The correct procedure is:

1. LLM proposes `NotificationProvider`.
2. LLM proposes `NotificationService`.
3. Validator checks the implementation.
4. Programmer approves the proposal.
5. Only then is the binding added.

Such consistency is key to the reliability of SDL.

## 17. What is defined, and what is not?

Architectural foundation
Defined
Two modes, project structure, modularity and backend concept; IR is for now defined only conceptually.

Basic ontology
Defined
Project, Module, Interface, Class, Function, Type, Flow, Binding, Requirement, Constraint, Implementation, Build, Proposal, Validation, Extension.

Semantic rules
Partial
Type system, inheritance, compatibility, and execution semantics need to be specified.

Formal YAML schema
Not finished
JSON Schema or equivalent formal rules are needed for each element.

Parser and validator
Planned
Implementation has not yet started.

## 18. Next Phase: SDL Core 0.2

My proposal is that we now do not add new major functionalities, but formalize existing ones.

I propose the following order:

1. SDL Grammar – precise YAML structure and permitted fields.
2. SDL Type System – complete rules for types, generics, and inference.
3. Interface Specification – formal contracts, methods, effects, and compatibility.
4. Module System – import, dependency, scope, and visibility.
5. Flow Semantics – precise program execution.
6. LLM Protocol – standardized format for proposals and changes.
7. SDL IR – formal internal model.

I especially insist that the SDL IR be independent of the LLM. This is what will allow the same SDL document to be used by different LLMs, parsers, compilers, and runtime systems.

My recommendation: next we should define the SDL Type System and Interface Specification together. They are the foundation of the whole language. If we design them well, module connection, code generation, and automatic validation become much simpler.

In this way, we will gradually reach a real language specification, and not just a conceptual design.
