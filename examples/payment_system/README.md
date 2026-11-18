# The payment system example

A complete SDL project with a type, an interface, an implementation, a module
function, a flow, a project and a binding.

```
project.sdl.yaml
  -> validate -> compile -> canonical IR -> execute the flow
```

## The files

| File | What it is |
| :--- | :--- |
| `project.sdl.yaml` | the root: imports, binding, backend, constraints |
| `types.sdl.yaml` | `PaymentRequest`, `PaymentResponse` and `Error` |
| `interfaces.sdl.yaml` | the `PaymentProvider` contract and its `charge` method |
| `implementations.sdl.yaml` | the realization, and where its code lives |
| `payment_helper.sdl.yaml` | the `build_request` function of the `payment_helper` module |
| `flow.sdl.yaml` | builds a request, charges it, reports success and transaction id |
| `payment_helper.py` | the code of `payment_helper::build_request` |
| `src/payments/stripe_api.py` | the code of `stripe_provider_impl` |

## Try it

```powershell
python -m sdl validate examples/payment_system/project.sdl.yaml

python -m sdl build examples/payment_system/project.sdl.yaml --out generated/payment_system

python -m sdl run examples/payment_system/project.sdl.yaml `
  --flow process_customer_payment `
  --input order_id=42 --input amount=10.5 --input token=tok_demo
```

The flow returns the outputs the documents declare:

```
The flow process_customer_payment returned:
  success = True
  tx_id = UUID('...')
```

## The binding

The flow names the interface, not the implementation:

```yaml
steps:
  - id: execute_payment
    call: PaymentProvider::charge
```

The project resolves that name through its bindings table:

```yaml
bindings:
  - interface: PaymentProvider
    version: "1.0.0"
    implementation: stripe_provider_impl
```

Replacing `stripe_provider_impl` with another implementation is a change of
one line in `project.sdl.yaml`, and the flow does not move.
