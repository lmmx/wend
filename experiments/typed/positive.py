"""Correct uses of the typed view: neither checker reports anything."""

from typing import Literal

from common import (
    STATIC,
    Convert,
    Survey,
    any_path,
    asset,
    data,
    listing,
    out,
    raw,
    read,
    root,
    serve,
    wants_readable,
    write,
)

from wend._experimental.typed import Exists, P, PathExpr


def run_step() -> None:
    with Convert(root="/data", name="a") as s:
        write(read(s.src), s.dst)
    with Survey(root="/data") as v:
        listing(v.tree)


# a declaration survives bind and rebase
wants_readable(raw)
wants_readable(raw.bind(root="/data"))
wants_readable(raw.rebase(P(root), P("/archive")))
wants_readable(Convert.src)

# a bare annotation accepts any expression, declared or derived
any_path(raw)
any_path(out)
any_path(raw.parent)
any_path(raw.with_suffix(".tsv"))

# containment under a literal base, carried by the rendered path
serve(asset.resolve(rel="logo.png"))
serve(asset.bind(rel="logo.png").resolve())

# a directory can be joined below
child = data / "x"
any_path(child)
any_path(P(STATIC) / "a")


# The boundary: a requirement names atoms that must be declared, never ones
# that must be absent, so only upward-closed properties are expressible. A
# path that requires exists and ensures exists creates nothing, yet meets a
# demand for post_exists; whether a step creates is the effect graph's to say.
def ensures_existence(p: PathExpr[Literal["post_exists"]]) -> None: ...


ensures_existence(raw.ensures(Exists))
