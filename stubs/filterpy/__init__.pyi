"""Local type stubs for FilterPy.

FilterPy ships no ``py.typed`` marker and no stubs, and this project runs mypy
in strict mode with ``disallow_any_unimported``. Rather than relax either
setting for the whole codebase, the exact surface L2 depends on is declared
here.

That has a second benefit worth more than the typing. FilterPy is an
unmaintained dependency inside a safety path, and ISO 26262 8-12 asks for
software components in such a position to be qualified. A qualification argument
begins with an enumeration of precisely what is used -- which is this file. Every
symbol below is a symbol the estimation layer relies on; anything not listed is
not depended upon and does not need to be argued for.
"""
