"""Bindings in application code: defaults, settings objects, counters, anchors.

The Future Paths essays sketch these as one-liners:
- part 1's ``PathVar``: paths declared once, bound later from a settings object;
- part 3's sized and unsized counter filenames;
- part 1's readymade anchors: ``fragment.under(XDG.CACHE_HOME / "myapp")``.
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from wend import P, Param, anchors, bindings, counter
from wend.anchors import XDG


# Part 1: symbolic paths, bound later. A dataclass (or attrs or Pydantic
# model) supplies the bindings by field name.
ROOT = Param("root")
CONFIG, DATA, OUTPUT = ROOT / "config.yaml", ROOT / "data", ROOT / "output"


@dataclass
class Settings:
    root: Path
    name: str = "demo"


settings = Settings(Path("/actual/root"))
print("config:", CONFIG.resolve(settings))
print("output:", OUTPUT.resolve(settings))
print("binds:", bindings(settings))

# Part 3: sized and unsized counters, with a default total.
total = Param("total", type=int, default=10)
chunk_file = (
    ROOT
    / "chunks"
    / counter("chunk", width=3, of_total=True, total=total, suffix=".parquet")
)
log_file = ROOT / "logs" / counter("log", width=5, suffix=".parquet")
print("\n" + chunk_file.pattern, "requires", sorted(chunk_file.required_params()))
print(chunk_file.resolve(root="/data", idx=1))  # total takes its default
print(chunk_file.resolve(root="/data", idx=1, total=12))
print(log_file.resolve(root="/data", idx=123))
# Matching reads every part from the path; the default is not assumed.
print(chunk_file.match("/data/chunks/chunk_004-of-012.parquet"))
print(chunk_file.match("/data/chunks/chunk_004.parquet"))

# Anchors: the expression stays symbolic until the environment is read.
models = (P("models") / Param("model")).under(XDG.CACHE_HOME / "myapp")
print("\n" + models.pattern)
here = anchors.bindings({"HOME": "/home/ada"})  # an explicit environment
print(models.render(here, model="bert"))
print(models.render(anchors.bindings(), model="bert").endswith("/myapp/models/bert"))

# Pydantic, when installed: validate a given path against the layout, or
# render one from bindings at validation time.
try:
    from typing import Annotated

    from pydantic import BaseModel, ValidationError

    from wend import Exists, File, Match
    from wend.pydantic import PathOf

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "chunks").mkdir()
        Path(tmp, "chunks", "chunk_001-of-010.parquet").touch()

        class Job(BaseModel):
            src: Annotated[Match, PathOf(chunk_file.requires(File, Exists))]
            dst: Annotated[Path, PathOf(log_file)]

        job = Job(
            src=f"{tmp}/chunks/chunk_001-of-010.parquet", dst={"root": tmp, "idx": 1}
        )
        print("\nsrc bindings:", {k: v for k, v in job.src.items() if k != "root"})
        print("dst:", job.dst.relative_to(tmp))
        try:
            Job(src=f"{tmp}/chunks/chunk_002-of-010.parquet", dst=job.dst)
        except ValidationError as e:
            print("rejected:", e.errors()[0]["type"])
except ImportError:
    pass
