"""Misuses of the typed core: each line marked with an E comment is an error
in both checkers, and no other line is. Most are a guarantee asked of a value
that carries another."""

from typing import Literal

from common import (
    Convert,
    out,
    raw,
    reads_object,
    stayed_readable,
    trusts,
    was_made,
    was_present,
    was_readable,
)

from wend import Checked, Confirmed, Exists, File, IsFile, P, PathExpr, Readable
from wend._experimental.events import Held, Holds, Run, seal


def an_event_is_not_an_object(run: Run) -> None:
    with run.enter(Convert, {"root": "/data", "name": "a"}) as s:
        reads_object(s.dst)  # E: a checked path is an event, not a held file
        seal(s.dst)  # E: nor can an event be sealed


def an_object_is_not_sealed(run: Run) -> None:
    with run.enter(Convert, {"root": "/data", "name": "a"}) as s:
        trusts(s.src)  # E: a held file's contents can still change


def an_entry_is_not_an_exit() -> None:
    entry, exit_ = out.checked(root="/d", name="a"), raw.confirmed(root="/d", name="a")
    was_made(entry)  # E: checked at entry, not confirmed at exit
    was_readable(exit_)  # E: confirmed, not checked


def an_output_is_not_readable() -> None:
    made = out.checked(root="/data", name="a")
    was_readable(made)  # E: an output is not declared readable


def an_entry_check_certifies_no_postcondition() -> None:
    was_present(out.checked(root="/d", name="a"))  # E: it was found absent


def an_exit_check_certifies_no_precondition() -> None:
    stayed_readable(raw.confirmed(root="/d", name="a"))  # E: nothing confirmed


def evidence_is_not_a_path() -> None:
    raw.checked(root="/d", name="a").parent  # E: no derived path inherits it


def a_path_is_not_evidence() -> None:
    was_readable(raw.checked(root="/d", name="a").path)  # E: evidence was dropped


def a_plain_check_gives_no_evidence() -> None:
    was_readable(raw.check(root="/d", name="a"))  # E: check gives a path


def ensuring_is_not_requiring() -> None:
    Holds(P("a").ensures(File, Exists, Readable))  # E: ensured, not required


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


def confirmed_is_not_checked(p: Confirmed[Literal["exists"], IsFile]) -> None:
    c: Checked[Literal["exists"], IsFile] = p  # E: two kinds of evidence
    del c
