"""The same uses against option A: one expression type with two condition parameters
(see model_a.py). Lines marked E are errors in both checkers; E-ty in ty
only: its inference from an expected type (tygap.py)."""

from typing import Literal

from model_a import (
    Absent,
    Checked,
    Confirmed,
    Creatable,
    Exists,
    Expr,
    File,
    IsFile,
    P,
    Readable,
)


raw = P("raw").requires(File, Exists, Readable)
out = P("out").requires(Absent, Creatable).ensures(File, Exists)
two = P("a").requires(Exists, Readable)  # the ty gap: two conditions, no File


def wants_read(c: Checked[Literal["read"], IsFile]) -> None: ...
def wants_made(c: Confirmed[Literal["exists"], IsFile]) -> None: ...
def wants_exists_checked(c: Checked[Literal["exists"]]) -> None: ...
def wants_read_confirmed(c: Confirmed[Literal["read"]]) -> None: ...
def needs_two(e: Expr[Literal["exists", "read"]]) -> None: ...


# valid
wants_read(raw.checked())
wants_exists_checked(two.checked())
needs_two(P("a").requires(Exists, Readable))  # E-ty: context
two_atoms: Expr[Literal["exists", "read"]] = P("a").requires(Exists, Readable)  # E-ty:
path = raw.checked().path  # explicit: an ordinary path, no evidence
parent = path.parent
wants_made(out.confirmed())
# invalid
wants_exists_checked(out.checked())  # E: an output's entry check found it absent
wants_read(two.checked())  # E: not declared a File
raw.checked().parent  # E: evidence is not a path: no derived path inherits it
needs_two(P("a").requires(Exists))  # E: not declared Readable
wants_read_confirmed(raw.confirmed())  # E: nothing about an input is confirmed
wants_made(out.checked())  # E: an entry check is not a confirmation
