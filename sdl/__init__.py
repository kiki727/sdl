"""SDL — Specification Description Language.

SDL is a formal language for specifying software architecture and execution.
A document is validated, lowered into the Canonical IR (a typed symbol graph),
checked by the Semantic Firewall, and either executed or compiled to source
code by a backend.

The pipeline is layered. Each layer may only depend on the layers above it::

    document (.sdl.yaml)
      -> sdl.yaml        layer 0  YAML subset (SDL-E100 - SDL-E103)
      -> sdl.schema      layer 1  envelope + JSON Schema (SDL-E200 - SDL-E220)
      -> sdl.semantics   layer 2  scope, imports, type resolution (SDL-E300+)
      -> sdl.parser      layer 3  AST
      -> sdl.lowering    layer 4  Canonical IR
      -> sdl.validation  layer 5  Semantic Firewall (IR level)
      -> sdl.proposal    layer 6  LLM proposal governance
      -> sdl.backends    layer 7  code generation and runtime

``sdl.compiler`` orchestrates the whole chain.
"""

__version__ = "1.0"

__all__ = ["__version__"]
