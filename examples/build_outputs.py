"""Source-to-build mappings as a lens: forward, backward, and staleness checks.

The two layouts share the parameters ``rel`` and ``stem``, so one Lens maps
sources to outputs and outputs back to their sources.
"""

import os
import tempfile
import time
from pathlib import Path

from wend import Lens, Param, SubPath, T


root = Param("root")
rel, stem = SubPath("rel"), Param("stem")
source = root / "src" / rel / T(t"{stem}.md")
output = root / "site" / rel / T(t"{stem}.html")

with tempfile.TemporaryDirectory() as tmp:
    build = Lens(source, output).bind(root=tmp)
    for name in ["index.md", "guide/install.md", "guide/usage.md", "notes/todo.txt"]:
        p = Path(tmp, "src", name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(name)

    # Build guide/install only, so the others are stale.
    out = build(Path(tmp, "src/guide/install.md"))
    out.parent.mkdir(parents=True, exist_ok=True)
    time.sleep(0.01)
    out.write_text("<html/>")

    stale = []
    for m in source.glob(root=tmp):
        target = build(m.path)
        if not target.exists() or target.stat().st_mtime < os.stat(m.path).st_mtime:
            stale.append(str(Path(m.path).relative_to(tmp)))
    print("stale:", stale)  # notes/todo.txt is not a source: it does not match

    # Backward: which source produced this page?
    print("source of", out.relative_to(tmp), "->", build.backward(out).relative_to(tmp))
