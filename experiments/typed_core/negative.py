"""Misuses of the typed core: each line marked with an E comment is an error
in both checkers, and no other line is. Most are a guarantee asked of a value
that carries another."""

from typing import Literal

from common import (
    Convert,
    Produce,
    drafts,
    out,
    raw,
    reads_object,
    trusts,
    was_made,
    was_readable,
)

from wend import Checked, Confirmed, Exists, IsFile, P, PathExpr, Readable
from wend._experimental.events import Held, Holds, Makes, Run, seal


def an_event_is_not_an_object(run: Run) -> None:
    with run.enter(Convert, {"root": "/data", "name": "a"}) as s:
        reads_object(s.dst)  # E: a checked path is an event, not a held file
        seal(s.dst)  # E: nor can an event be sealed


def an_object_is_not_sealed(run: Run) -> None:
    with run.enter(Convert, {"root": "/data", "name": "a"}) as s:
        trusts(s.src)  # E: a held file's contents can still change


def an_entry_is_not_an_exit() -> None:
    entry, exit_ = out.check(root="/d", name="a"), raw.confirm(root="/d", name="a")
    was_made(entry)  # E: checked at entry, not confirmed at exit
    was_readable(exit_)  # E: confirmed, not checked


def an_output_is_not_readable() -> None:
    made = out.check(root="/data", name="a")
    was_readable(made)  # E: an output is not declared readable


def held_for_reading_is_not_held_for_writing(h: Held[Literal["read"], IsFile]) -> None:
    w: Held[Literal["write"], IsFile] = h  # E: read access is not write access
    del w


def only_a_readable_file_can_be_held() -> None:
    Holds(P("a").requires(Exists, Readable))  # E: not declared a File
    Holds(P("a").requires(Exists))  # E: not declared Readable


def nothing_joins_below_a_file() -> None:
    e: PathExpr = raw / "below"  # E: joining below a File is not a path
    del e


def a_name_fact_is_not_an_object_fact(h: Held[Literal["read"], IsFile]) -> None:
    gone: Held[Literal["absent"], IsFile] = h  # E: absence is a fact about a name
    del gone


def an_event_does_not_widen(p: Checked[Literal["exists"], IsFile]) -> None:
    more: Checked[Literal["exists", "read"], IsFile] = p  # E: fewer atoms were checked
    del more


def confirmed_is_not_checked(p: Confirmed[Literal["post_exists"], IsFile]) -> None:
    c: Checked[Literal["post_exists"], IsFile] = p  # E: two kinds of event
    del c


def a_draft_is_not_an_input(run: Run) -> None:
    with run.enter(Produce, {"root": "/data", "name": "a"}) as s:
        reads_object(s.dst)  # E: a draft is written, not held for reading
        seal(s.dst)  # E: nor sealed: it has no contents yet that anyone saw
        drafts(s.src)  # E: and a held input is not a draft


def only_a_new_file_can_be_made() -> None:
    Makes(raw)  # E: an existing input is not a new file
