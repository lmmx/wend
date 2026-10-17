"""Joining untrusted input safely.

With pathlib, joining a user-supplied name can escape the intended directory.
In wend, a parameter after the head of an expression is a single segment
unless declared otherwise, so traversal is rejected by construction.
"""

from pathlib import Path

from wend import InvalidBindingError, P, Param


STATIC = Path("/srv/static")
asset = P(STATIC) / Param("name")

for name in ["logo.png", "../../etc/passwd", "/etc/passwd", "a/b.css", ".."]:
    eager = STATIC / name
    try:
        safe = asset.resolve(name=name)
    except InvalidBindingError:
        safe = "rejected"
    print(f"{name!r:22} pathlib: {str(eager):20} wend: {safe}")
