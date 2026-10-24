"""Declarations shared by positive.py and negative.py: the pipeline step of
docs/site/guides/pipelines.md and the static server of
docs/site/guides/untrusted-input.md, written against the typed view."""

from typing import Final, Literal

from wend._experimental.typed import (
    Absent,
    AnyPath,
    Checked,
    Creatable,
    Dir,
    Exists,
    File,
    Listable,
    P,
    Param,
    PathExpr,
    Readable,
    Resolved,
    StepSpec,
    T,
    Under,
    Uses,
)


root, name = Param("root"), Param("name")
raw = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
out = (P(root) / "out" / T(t"{name}.parquet")).requires(Absent, Creatable)
out = out.ensures(File, Exists)
data = (P(root) / "data").requires(Dir, Exists, Listable)

type Input = Checked[Literal["read", "exists", "file"]]
type Output = Checked[Literal["create", "absent", "post_file"]]
type Listing = Checked[Literal["list", "dir"]]


def read(p: Input) -> bytes:
    return p.read_bytes()


def write(content: bytes, p: Output) -> None:
    p.write_bytes(content)


def listing(p: Listing) -> list[str]:
    return sorted(c.name for c in p.iterdir())


def wants_readable(p: PathExpr[Literal["read"]]) -> str:
    return p.pattern


def any_path(p: PathExpr) -> str:
    return p.pattern


class Convert(StepSpec):
    src = Uses(raw)
    dst = Uses(out)


class Survey(StepSpec):
    tree = Uses(data)


STATIC: Final = "/srv/static"
asset = (P(STATIC) / AnyPath("rel")).requires(Under(STATIC), Readable)


def serve(p: Resolved[Literal["read"] | Under[Literal["/srv/static"]]]) -> str:
    return str(p)
