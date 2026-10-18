"""Connected paths: relations that survive composition and move together.

A pipeline step reads an input, writes a cleaned copy beside it, keeps a
schema next to the input and a report in a sibling directory. Each path is
defined relative to the input, so pointing the step at a test fixture moves
all of them at once.
"""

import tempfile
from pathlib import Path

from wend import P, Param, T


root = Param("root")
day = Param("day")

raw = P(root) / "raw" / T(t"{day}.csv")
paths = {
    "input": raw,
    "clean": raw.with_suffix(".clean.parquet"),
    "schema": raw.sibling("schema.json"),
    "report": raw.cousin("../reports", T(t"{day}.md")),
}
for k, e in paths.items():
    print(f"{k:7} {e.pattern}")

# The report is derived from the input, so it knows where it came from.
print("\nreport derived from input:", paths["report"].derived_from(raw))

# A test points the step at a fixture directory: rebase the input, and every
# path derived from it follows, while the relations stay as declared.
with tempfile.TemporaryDirectory() as tmp:
    fixture = P(tmp) / "fixture" / T(t"{day}.csv")
    moved = {k: e.rebase(raw, fixture) for k, e in paths.items()}
    for k, e in moved.items():
        print(f"{k:7} {Path(e.render(day='2026-10-18')).relative_to(tmp)}")

# One relative fragment, placed under several bases.
cache = P(".cache") / "models" / "v1"
print(
    "\n" + "\n".join(str(cache.under(home).pattern) for home in ("/home/a", "/home/b"))
)
