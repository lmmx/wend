"""Uses of the typed core that both checkers accept."""

from typing import Literal

from common import Convert, out, raw, reads_object, trusts, was_made, was_readable

from wend import Checked, Exists, File, IsFile, P, PathExpr, Readable, Under
from wend._experimental.events import Run, seal


def a_declaration_is_a_type() -> None:
    e: PathExpr[Literal["read", "exists"], IsFile] = raw  # at least these atoms
    any_path: PathExpr = raw  # a bare annotation accepts every expression
    del e, any_path


def deriving_drops_declarations() -> None:
    plain: PathExpr = raw.parent / "other.csv"  # a derived expression declares nothing
    del plain


def check_gives_an_event() -> None:
    p = raw.check(root="/data", name="a")
    was_readable(p)  # an entry event of an expression declaring Readable
    c: Checked[Literal["exists"], IsFile] = p  # fewer atoms: still assignable
    del c


def confirm_gives_an_exit_event() -> None:
    was_made(out.confirm(root="/data", name="a"))


def a_step_holds_its_input_and_checks_its_output(run: Run) -> None:
    with run.enter(Convert, {"root": "/data", "name": "a"}) as s:
        data = reads_object(s.src)  # which object: held for reading
        sealed = seal(s.src)  # it remains true: a sealed copy
        trusts(sealed)
        run.known(s.dst)  # an event can be asked whether it is still known
        del data


def the_class_attribute_is_the_declaration() -> None:
    e = Convert.dst  # the expression, for effects and graphs
    del e


def a_literal_base_is_its_own_atom() -> None:
    srv = (P("/srv") / "x").requires(Under("/srv"))
    lit: PathExpr[Under[Literal["/srv"]]] = srv
    any_base: PathExpr[Under[str]] = srv
    del lit, any_base


type ReadableFile = PathExpr[Literal["file", "exists", "read"], IsFile]


def file_then_more() -> None:
    plain = P("a").requires(File, Exists, Readable)
    e: PathExpr[Literal["file", "exists", "read"], IsFile] = plain
    # ty 0.0.90 takes the File-first overload with two more conditions only
    # without an expected type: here, it falls back to the general overload.
    f: ReadableFile = P("a").requires(File, Exists, Readable)  # E-ty: a known gap
    del e, f
