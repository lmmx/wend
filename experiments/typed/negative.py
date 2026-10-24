"""Misuses of the typed view: each line marked with an E comment is an error in both
checkers, and no other line is."""

from typing import Literal

from common import (
    STATIC,
    Convert,
    raw,
    read,
    serve,
    wants_readable,
    write,
)

from wend._experimental.typed import (
    AnyPath,
    Checked,
    Exists,
    File,
    P,
    PathExpr,
    Readable,
    Under,
)


def misuse_step() -> None:
    with Convert(root="/data", name="a") as s:
        read(s.dst)  # E: an output is not declared readable
        write(b"", s.src)  # E: an input is not declared creatable


def lists(p: Checked[Literal["read", "dir"]]) -> None: ...


def misuse_kind() -> None:
    with Convert(root="/data", name="a") as s:
        lists(s.src)  # E: a File is not a Dir


read(raw.resolve(root="/d", name="a"))  # E: rendered is not checked
wants_readable(raw.parent)  # E: a derived path declares nothing
wants_readable(raw.with_suffix(".tsv"))  # E: a derived path declares nothing
wants_readable(P("x"))  # E: an undeclared path
wants_readable(P("x").requires(File))  # E: File alone declares no access
no_base = (P(STATIC) / AnyPath("r")).requires(Readable)
tmp_base = (P("/tmp") / AnyPath("r")).requires(Under("/tmp"), Readable)
any_base = (P(STATIC) / AnyPath("r")).requires(Under(P(STATIC)), Readable)
serve(no_base.resolve(r="x"))  # E: no containment
serve(tmp_base.resolve(r="x"))  # E: wrong base
serve(any_base.resolve(r="x"))  # E: a base without identity
(raw / "child").render()  # E: nothing joins below a File


# Inline, where call-site inference could solve a type variable from the
# expected type and so invent or widen a declaration.
def wants_rw(p: PathExpr[Literal["read", "write"]]) -> None: ...


wants_readable(P("x").requires())  # E: nothing declared
wants_readable(P("x").requires(Exists))  # E: not widened to include read
wants_rw(P("x").requires(Readable))  # E: not widened to include write
wants_rw(P("x").requires(Readable, Exists))  # E: no write
wants_readable(P("x").ensures(Readable))  # E: a postcondition is not a precondition
