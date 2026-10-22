"""Declarations shared by positive.py and negative.py: a step whose input is
held and whose output is checked, and functions that each demand one of the
three guarantees."""

from typing import Literal

from wend import (
    Absent,
    Checked,
    Confirmed,
    Creatable,
    Exists,
    File,
    IsFile,
    P,
    Param,
    Readable,
    T,
)
from wend._experimental.events import Held, Holds, Sealed, Spec, Uses


root, name = Param("root"), Param("name")
raw = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
out = (
    (P(root) / "out" / T(t"{name}.parquet"))
    .requires(Absent, Creatable)
    .ensures(File, Exists)
)


class Convert(Spec):
    src = Holds(raw)
    dst = Uses(out)


# It was true: an event at a step's entry, or at its exit.
def was_readable(p: Checked[Literal["read"], IsFile]) -> None: ...
def was_made(p: Confirmed[Literal["post_exists"], IsFile]) -> None: ...


# Which object: an open file, held for reading.
def reads_object(h: Held[Literal["read"], IsFile]) -> bytes:
    return h.read()


# It remains true: contents no holder can change.
def trusts(s: Sealed) -> bytes:
    return s.read()
