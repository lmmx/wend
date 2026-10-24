"""Capabilities as phantom type parameters: one parameter per capability,
Yes or No, so a function can demand one capability and ignore the others.

Type-check only (docs/journal/2026-10-21-future-paths-stock.md, Measured):

    uvx pyright@1.1.407 --pythonversion 3.14 2026-10-21-capability-probe.py
    uvx ty@0.0.90 check --python-version 3.14 2026-10-21-capability-probe.py

Both report exactly the two calls marked "expected error"."""

from typing import Any, overload, reveal_type


class Yes: ...


class No: ...


class Readable: ...


class Writable: ...


class PathExpr[R, W]:
    @overload
    def requires(self, c: type[Readable]) -> PathExpr[Yes, W]: ...
    @overload
    def requires(self, c: type[Writable]) -> PathExpr[R, Yes]: ...
    def requires(self, c: Any) -> Any:
        return self


def P(s: str) -> PathExpr[No, No]:
    return PathExpr()


def load[W](p: PathExpr[Yes, W]) -> None: ...  # needs Readable, any W
def save[R](p: PathExpr[R, Yes]) -> None: ...  # needs Writable, any R


src = P("raw.csv").requires(Readable)
dst = P("out.parquet").requires(Writable)
both = P("cache").requires(Readable).requires(Writable)

load(src)
save(dst)
load(both)
save(both)
load(dst)  # expected error: not Readable
save(src)  # expected error: not Writable
reveal_type(both)  # PathExpr[Yes, Yes]
