"""Layer 7: code generation and runtime backends.

The back end of a project names the language of the build, as specification
section 7.1 defines it. The toolchain implements one of them.
"""

#: The back ends the toolchain implements.
#:
#: A project may name any language, because the specification is independent
#: of the languages the toolchain happens to speak. The build refuses a
#: target it cannot produce, rather than producing something else.
IMPLEMENTED_TARGETS = ("python",)
