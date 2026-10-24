"""Operations the pipeline's types refuse before anything runs: each line
marked with an E comment is an error in both Pyright and ty (checked by
experiments/typed_core/check.py), and no other line is."""

from pipeline import Report, Validate, orders, reports, staged, staged_new

from wend._experimental.events import Commits, Holds, Makes, Run, Sealed, seal
from wend._experimental.publish import Pinned


def a_port_declares_what_it_may_do() -> None:
    Holds(staged_new)  # E: an output not yet made cannot be held
    Makes(orders)  # E: an existing input cannot be made
    Commits(staged)  # E: a file cannot hold versions
    Makes(reports)  # E: a directory of versions is not one new file


def uses(s: Sealed) -> bytes:
    return s.read()


def each_value_carries_one_guarantee(run: Run) -> None:
    env = {"root": "/data", "day": "mon"}
    with run.enter(Validate, env) as v:
        uses(v.orders)  # E: a held file's contents can still change
        seal(v.staged)  # E: a draft is not an input
        v.staged.read()  # E: a draft is written, never read
        v.orders.write(b"")  # E: an input is held for reading only
    with run.enter(Report, env) as r:
        r.report.write(b"")  # E: a version is filled by name, member by member
        seal(r.report)  # E: nor is a version an input


def a_pinned_version_is_read_only(p: Pinned) -> None:
    p.write("summary.csv", b"")  # E: no writer reaches a pinned version
