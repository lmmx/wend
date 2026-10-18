"""Unions and queries: one pattern for variants, fallbacks, and filtered discovery.

Rotated logs come in four shapes; a configuration file may live in one of
three places; a source tree has modules and their tests side by side. Each
is one declaration.
"""

import os
import tempfile
import time
from pathlib import Path

from wend import Alt, File, NoAlternativeError, P, Param, SubPath, T, U
from wend.query import larger_than, modified_after


d, k = Param("d"), Param("k", type=int)
logs = U(t"{d}/app.log{Alt('', t'.{k}')}{Alt('', '.gz')}")
print("log shapes:", logs.pattern)

home, app = Param("home"), Param("app")
config = (
    P(home) / ".config" / T(t"{app}.toml")
    | P(home) / ".local/etc" / T(t"{app}.toml")
    | P(home) / "defaults.toml"
).requires(File)

stem, rel = Param("stem"), SubPath("rel")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    for name in ["app.log", "app.log.1", "app.log.2.gz", "app.log.3.gz", "cron.log"]:
        (root / name).write_text("")

    print("\nrotated logs, one glob:")
    for m in logs.glob(d=root):
        shape = logs.alternatives[m.alternative].pattern.removeprefix("{d}/")
        print(f"  {os.path.basename(m.path):14} k={m.get('k')!s:5} shape {shape}")

    # A fallback is an effect: it looks at the filesystem, unlike render.
    (root / "defaults.toml").write_text("")
    print("\nconfig:", config.first(home=root, app="tool").relative_to(root))
    (root / ".config").mkdir()
    (root / ".config" / "tool.toml").write_text("")
    print("config:", config.first(home=root, app="tool").relative_to(root))
    try:
        config.first(home=root / "elsewhere", app="tool")
    except NoAlternativeError as e:
        print("no config:", len(e.tried), "places tried")

    src = root / "src"
    for name, size in [("io.py", 10), ("io_test.py", 10), ("core/model.py", 5000)]:
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text("#" * size)

    modules = P(src) / rel / T(t"{stem}.py")
    tests = P(src) / rel / T(t"{stem}_test.py")
    hour_ago = time.time() - 3600
    query = (modules - tests).where(File, modified_after(hour_ago))
    print("\nmodules, not tests, changed this hour:", [m["stem"] for m in query.glob()])
    print("large modules:", [m["stem"] for m in query.where(larger_than(1000)).glob()])
