"""Layer 7: code generation and runtime backends.

The back end of a project names the language of the build, as specification
section 7.1 defines it. The toolchain implements the ones listed in
``IMPLEMENTED_TARGETS``, and each is selected by its target.
"""

#: The back ends the toolchain implements.
#:
#: A project may name any language, because the specification is independent
#: of the languages the toolchain happens to speak. The build refuses a
#: target it cannot produce, rather than producing something else.
IMPLEMENTED_TARGETS = ("python", "nodejs")

#: The code generator of each implemented target.
#:
#: A back end is selected by the ``backend.target`` of the project, so the
#: build produces the language the document asked for.
CODEGEN = {
    "python": ("sdl.backends.codegen.python_gen", "PythonCodegen"),
    "nodejs": ("sdl.backends.codegen.typescript_gen", "TypeScriptCodegen"),
}


def codegen_for(target: str | None):
    """The code generator of a target, or the Python one when none is named."""
    import importlib

    module_name, class_name = CODEGEN.get(target or "python", CODEGEN["python"])
    module = importlib.import_module(module_name)
    return getattr(module, class_name)
