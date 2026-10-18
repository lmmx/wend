"""Pipeline conditions: one declaration of what a step needs and promises.

A step converts a day's raw CSV into an uppercase copy. Its input must be an
existing readable file; its output must not exist yet and must be creatable,
and once the step has run it must exist. Untrusted relative paths from a
config file are kept under the data root.
"""

import tempfile
from pathlib import Path

from wend import (
    Absent,
    AnyPath,
    ConditionError,
    ContainmentError,
    Creatable,
    Exists,
    File,
    P,
    Param,
    PathExistsError,
    Readable,
    Step,
    T,
    Under,
)


root = Param("root")
day = Param("day")

src = (P(root) / "raw" / T(t"{day}.csv")).requires(File, Exists, Readable)
dst = (P(root) / "clean" / T(t"{day}.csv")).requires(Absent, Creatable)
convert = Step(src=src, dst=dst.ensures(File, Exists))

print("declared effects:")
for effect in convert.effects():
    print(" ", effect)

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "raw").mkdir()
    (Path(tmp) / "raw" / "2026-10-18.csv").write_text("a,b\n1,2\n")

    with convert(root=tmp, day="2026-10-18") as p:
        p["dst"].parent.mkdir(parents=True, exist_ok=True)
        p["dst"].write_text(p["src"].read_text().upper())
    print("\nconverted:", (Path(tmp) / "clean" / "2026-10-18.csv").read_text().split())

    # Running it again would overwrite the output: the precondition says no.
    try:
        with convert(root=tmp, day="2026-10-18"):
            pass
    except PathExistsError as e:
        print("refused:", type(e).__name__, "for", Path(e.path).relative_to(tmp))

    # A day with no input fails before the step body runs.
    try:
        convert.check(root=tmp, day="2026-10-19")
    except ConditionError as e:
        print("refused:", type(e).__name__, "for", Path(e.path).relative_to(tmp))

# Paths from configuration stay under the root, whatever they contain.
extra = (P(root) / AnyPath("rel")).requires(Under(P(root)))
print("\nallowed:", extra.render(root="/data", rel="lookups/zones.csv"))
for rel in ("../etc/passwd", "/etc/passwd"):
    try:
        extra.render(root="/data", rel=rel)
    except ContainmentError as e:
        print("refused:", e.path)
