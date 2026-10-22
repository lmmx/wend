"""One pipeline through the mechanisms of the research stack (#107-#114),
run honestly and then against one move of another writer at a time.

    uv run python experiments/synthesis/pipeline.py

A day's sales land as two files. `Validate` joins orders to prices into a
staged file; `Report` turns the staged file into a summary and a per-SKU
table, published together as one version of a store. A consumer pins the
version and checks that the two agree. On the way:

1. the declarations are analysed before anything runs (`plan`);
2. each input is checked (an event), held (which object) and sealed (the
   bytes used, which nothing can change);
3. each output is drafted where no reader can see it, and published whole
   (`Makes`) or as a set (`Commits`);
4. each publication records what it was made from (`Derivation`), and a
   change upstream puts everything downstream in doubt (`invalidated`);
5. a reader pins one version and verifies every member against the
   manifest its commit returned.

`SCENARIOS` are the interference, each scheduled at a named point of the
run, and `main` prints which guarantee held and on what it rests (see
docs/journal/2026-10-22-synthesis.md for the classification).
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from wend import Absent, Creatable, Dir, Exists, File, IsFile, P, Param, Readable, T
from wend._experimental import events, fresh
from wend._experimental.confined import Confined
from wend._experimental.events import Commits, Held, Holds, Makes, Run, Spec, seal
from wend._experimental.families import analyse_families
from wend._experimental.publish import (
    Conflict,
    Inconsistent,
    Modified,
    Store,
    Version,
    invalidated,
)


# -- declarations -------------------------------------------------------------

root, day = Param("root"), Param("day")
landing = P(root) / "landing" / T(t"{day}")
orders = (landing / "orders.csv").requires(File, Exists, Readable)
prices = (landing / "prices.csv").requires(File, Exists, Readable)
staging = P(root) / "staging" / T(t"{day}.csv")
staged_new = staging.requires(Absent, Creatable).ensures(File, Exists)
staged = staging.requires(File, Exists, Readable)
reports = (P(root) / "reports" / T(t"{day}")).requires(Dir).ensures(Dir, Exists)


class Validate(Spec):
    orders = Holds(orders)
    prices = Holds(prices)
    staged = Makes(staged_new)


class Report(Spec):
    staged = Holds(staged)
    report = Commits(reports)


PIPELINE = [("validate", Validate.step()), ("report", Report.step())]


def plan(steps=PIPELINE) -> dict[tuple[str, str], tuple[set[str], set[str]]]:
    """Before anything runs, for every day: what each port's check will find
    already known from an earlier step's postconditions, and what an
    earlier step's effects refute (that check will fail)."""
    return {
        (e.step, e.port): (set(e.known), set(e.refuted))
        for e in analyse_families(steps)
    }


# -- the steps ----------------------------------------------------------------


def table(h: Held[Literal["read"], IsFile]) -> list[list[str]]:
    copy = seal(h)  # the bytes used: a copy no writer can change
    try:
        lines = copy.read().decode().splitlines()[1:]
    finally:
        copy.close()
    return [line.split(",") for line in lines]


def validate(s: Validate) -> None:
    price = {sku: float(p) for sku, p in table(s.prices)}
    out = ["order,sku,amount"]
    for order, sku, qty in table(s.orders):
        if sku not in price:
            raise ValueError(f"order {order}: no price for {sku}")
        out.append(f"{order},{sku},{int(qty) * price[sku]:.2f}")
    s.staged.write(("\n".join(out) + "\n").encode())


def report(s: Report) -> None:
    rows = table(s.staged)
    by_sku: dict[str, float] = {}
    for _, sku, amount in rows:
        by_sku[sku] = by_sku.get(sku, 0.0) + float(amount)
    total = sum(by_sku.values())
    s.report.add("summary.csv", f"orders,total\n{len(rows)},{total:.2f}\n".encode())
    top = sorted(by_sku.items(), key=lambda kv: -kv[1])
    s.report.add(
        "by_sku.csv",
        ("sku,amount\n" + "".join(f"{k},{v:.2f}\n" for k, v in top)).encode(),
    )


Hook = Callable[[str], None]


def run(
    base: str, date: str, between: Hook = lambda point: None, *, lease: bool = False
) -> Run:
    """Both steps, with ``between`` called at each named point: where the
    scenarios put another writer. With ``lease``, no process can open an
    input for writing while a step holds it (`fresh.Leases`)."""
    r = Run(base, lease=lease)
    env = {"root": base, "day": date}
    with r.enter(Validate, env) as s:
        between("validate: entered")
        validate(s)
        between("validate: body done")
    between("between the steps")
    with r.enter(Report, env) as s:
        between("report: entered")
        report(s)
        between("report: body done")
    return r


def committed(r: Run, date: str = "mon") -> Version:
    v = r.published[f"reports/{date}"]
    assert isinstance(v, Version)
    return v


def consume(base: str, date: str, version: Version) -> tuple[int, float, float]:
    """A downstream reader: pin the version, read both members through it,
    each verified against the manifest the commit returned."""
    io = Confined(base)
    try:
        with Store(io, f"reports/{date}").pin(
            version.n, manifest=version.manifest
        ) as p:
            summary, by_sku = p.read("summary.csv"), p.read("by_sku.csv")
    finally:
        io.close()
    count, total = summary.decode().splitlines()[1].split(",")
    amounts = [float(r.split(",")[1]) for r in by_sku.decode().splitlines()[1:]]
    return int(count), float(total), round(sum(amounts), 2)


# -- a day's data, and another writer -----------------------------------------

ORDERS = b"order,sku,qty\n1,apple,3\n2,pear,1\n3,apple,2\n"
PRICES = b"sku,price\napple,0.50\npear,0.80\n"
ORDERS_1 = b"order,sku,qty\n1,apple,30\n2,pear,10\n3,apple,20\n"
PRICES_1 = b"sku,price\napple,0.55\npear,0.85\n"


def lay_out(base: Path, date: str = "mon") -> None:
    (base / "landing" / date).mkdir(parents=True)
    (base / "landing" / date / "orders.csv").write_bytes(ORDERS)
    (base / "landing" / date / "prices.csv").write_bytes(PRICES)


def overwrite(p: Path, data: bytes) -> None:
    """Another writer, in place: same object, new contents."""
    fd = os.open(p, os.O_WRONLY | os.O_TRUNC)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


@contextmanager
def at_observations(hook: Callable[[str, int], None]) -> Generator[None]:
    """Call ``hook(kind, n)`` after the run's n-th entry observation
    (``"observed"``) and n-th read of a held input (``"read"``): a
    deterministic schedule for another writer inside a step."""
    real_fp, real_read = fresh.fingerprint, events.Held.read
    count = {"observed": 0, "read": 0}

    def fingerprint(fd: int, *, content: bool) -> fresh.Fingerprint:
        out = real_fp(fd, content=content)
        count["observed"] += 1
        hook("observed", count["observed"])
        return out

    def read(self: Held[Any, Any]) -> bytes:
        out = real_read(self)
        count["read"] += 1
        hook("read", count["read"])
        return out

    setattr(fresh, "fingerprint", fingerprint)
    setattr(events.Held, "read", read)
    try:
        yield
    finally:
        setattr(fresh, "fingerprint", real_fp)
        setattr(events.Held, "read", real_read)


def refused(act: Callable[[], object]) -> BaseException:
    """The exception ``act`` raised; it must raise one."""
    try:
        act()
    except Exception as e:
        return e
    raise AssertionError("the interference was not refused")


@dataclass
class Outcome:
    scenario: str
    what_happened: str
    rests_on: str  # "construction", "assumption: ...", or "nothing"


def honest(base: Path) -> Outcome:
    r = run(str(base), "mon")
    v = committed(r)
    count, total, summed = consume(str(base), "mon", v)
    assert (count, total, summed) == (3, 3.3, 3.3)
    assert invalidated(r.derivations, r.io) == {}
    return Outcome(
        "honest run",
        f"staged and v{v.n} published; reader pinned v{v.n}: total {total} "
        f"= sum by SKU {summed}; nothing in doubt",
        "construction",
    )


def input_rewritten_after(base: Path) -> Outcome:
    r = run(str(base), "mon")
    overwrite(base / "landing/mon/prices.csv", PRICES_1)
    doubt = invalidated(r.derivations, r.io)
    known = r.known(r.confirmed["staging/mon.csv"])
    assert known and doubt == {
        "staging/mon.csv": {"landing/mon/prices.csv"},
        "reports/mon/v000001": {"staging/mon.csv"},
    }
    return Outcome(
        "an input rewritten after the run",
        f"known() still {known}; invalidated: {sorted(doubt)}",
        "assumption: knowledge assumes no other writer; doubt is what an observer saw",
    )


def input_rewritten_during(base: Path) -> Outcome:
    def between(point: str) -> None:
        if point == "validate: entered":
            overwrite(base / "landing/mon/orders.csv", ORDERS_1)

    e = refused(lambda: run(str(base), "mon", between))
    why = str(e)
    staged_left = os.listdir(base / "staging")
    assert isinstance(e, Inconsistent) and staged_left == []
    assert "changed while the step read it" in why
    return Outcome(
        "an input rewritten between entry and read",
        f"refused at exit ({why.split(':')[0]}); nothing published",
        "construction",
    )


def pair_updated_mid_entry(base: Path) -> Outcome:
    # The double-collect schedule, against a writer that only ever writes
    # orders and prices as a pair: the old pair, the new pair, the old pair.
    # Entry observes orders, then prices; the body reads prices, then orders.
    lo, lp = base / "landing/mon/orders.csv", base / "landing/mon/prices.csv"

    def hook(kind: str, n: int) -> None:
        if (kind, n) == ("observed", 1):  # orders observed: old
            overwrite(lo, ORDERS_1)
            overwrite(lp, PRICES_1)  # the new pair
        if (kind, n) == ("read", 1):  # prices read: new, as observed
            overwrite(lo, ORDERS)
            overwrite(lp, PRICES)  # the old pair again
        # orders are then read: old, as observed

    with at_observations(hook):
        r = run(str(base), "mon")
    v = committed(r)
    _, total, _ = consume(str(base), "mon", v)
    assert total == round(3 * 0.55 + 0.85 + 2 * 0.55, 2)  # old orders, new prices
    after = invalidated(r.derivations, r.io)
    assert "staging/mon.csv" in after  # only because the prices moved on
    return Outcome(
        "two inputs another writer updates as a pair, observed one at a time",
        f"run succeeded on old orders and new prices (total {total}), a pair "
        "that never existed; every check passed. Afterwards invalidated() "
        "flags it, only because the prices moved on",
        "nothing, for any observer: a coherent snapshot of files others write "
        "in place needs their cooperation (inputs landed as versions of a "
        "store) or their exclusion (leases, next)",
    )


def pair_updated_mid_entry_leased(base: Path) -> Outcome:
    # The same schedule against a run that leases its inputs: the writer's
    # first open for writing must wait (here, not waiting, it is refused),
    # and the run, seeing its lease broken, publishes nothing.
    lo, lp = base / "landing/mon/orders.csv", base / "landing/mon/prices.csv"
    held_off = []

    def try_overwrite(p: Path, data: bytes) -> None:
        try:
            fd = os.open(p, os.O_WRONLY | os.O_TRUNC | os.O_NONBLOCK)
        except BlockingIOError:
            held_off.append(p.name)
            return
        try:
            os.write(fd, data)
        finally:
            os.close(fd)

    def hook(kind: str, n: int) -> None:
        if (kind, n) == ("observed", 1):
            try_overwrite(lo, ORDERS_1)
            try_overwrite(lp, PRICES_1)
        if (kind, n) == ("read", 1):
            try_overwrite(lo, ORDERS)
            try_overwrite(lp, PRICES)

    with at_observations(hook):
        e = refused(lambda: run(str(base), "mon", lease=True))
    assert isinstance(e, Inconsistent) and os.listdir(base / "staging") == []
    assert held_off[0] == "orders.csv"  # leased already, so it had to wait
    return Outcome(
        "the same pair update, against a run that leases its inputs",
        f"{len(held_off)} of the writer's 4 opens for writing were held off; "
        "the run saw its lease broken and published nothing",
        "construction, by excluding writers rather than asking them to "
        "cooperate (proposition L of the leases journal): needs the inputs' "
        "owner or CAP_LEASE and a filesystem in fresh.LEASABLE; a truncation "
        "by O_RDONLY|O_TRUNC is not excluded but seen; a writer is delayed, "
        "at most lease-break-time",
    )


def staged_replaced_between(base: Path) -> Outcome:
    def between(point: str) -> None:
        if point == "between the steps":
            tmp = base / "staging" / ".theirs"
            tmp.write_bytes(b"order,sku,amount\n9,plum,99.00\n")
            tmp.rename(base / "staging" / "mon.csv")

    e = refused(lambda: run(str(base), "mon", between))
    assert isinstance(e, Inconsistent) and "not the file this run published" in str(e)
    assert not (base / "reports" / "mon").exists() or not os.listdir(
        base / "reports" / "mon"
    )
    return Outcome(
        "the staged file renamed over between the steps",
        "Report refused at entry: not the object Validate published",
        "construction",
    )


def output_name_taken(base: Path) -> Outcome:
    def between(point: str) -> None:
        if point == "validate: body done":
            (base / "staging" / "mon.csv").write_bytes(b"theirs")

    e = refused(lambda: run(str(base), "mon", between))
    assert isinstance(e, FileExistsError)
    assert (base / "staging" / "mon.csv").read_bytes() == b"theirs"
    return Outcome(
        "another writer creates the output's name during the step",
        "publication refused (create never replaces); their file kept",
        "construction",
    )


def landing_swapped_for_a_symlink(base: Path) -> Outcome:
    outside = base.parent / f"{base.name}-outside"
    outside.mkdir()
    (outside / "orders.csv").write_bytes(b"order,sku,qty\n1,secret,1\n")
    (outside / "prices.csv").write_bytes(b"sku,price\nsecret,1\n")
    (base / "landing" / "mon").rename(base / "landing" / "old")
    (base / "landing" / "mon").symlink_to(outside)
    why = type(refused(lambda: run(str(base), "mon"))).__name__
    assert not (base / "staging").exists()
    return Outcome(
        "a landing directory swapped for a symlink out of the root",
        f"refused at the check ({why}); nothing read from outside",
        "construction (openat2 RESOLVE_BENEATH, on Linux >= 5.6)",
    )


def concurrent_producers(base: Path) -> Outcome:
    # Another producer claims the version this run would claim, while its
    # Report step is running: one claim of v1 wins.
    def between(point: str) -> None:
        if point == "report: body done":
            io = Run(str(base)).io
            try:
                theirs = Store(io, "reports/mon").begin(None)
                theirs.add("summary.csv", b"orders,total\n0,0.00\n")
                theirs.add("by_sku.csv", b"sku,amount\n")
                theirs.commit()
            finally:
                io.close()

    e = refused(lambda: run(str(base), "mon", between))
    left = sorted(os.listdir(base / "reports" / "mon"))
    assert isinstance(e, Conflict) and left == ["v000001"]
    return Outcome(
        "a second producer claims the same version first",
        "this run's claim refused, its version never visible; theirs is v1",
        "construction, given the store protocol (claim latest + 1)",
    )


def member_tampered(base: Path) -> Outcome:
    r = run(str(base), "mon")
    v = committed(r)
    member = base / "reports/mon/v000001/by_sku.csv"
    overwrite(member, b"sku,amount\napple,1000.00\n")
    e = refused(lambda: consume(str(base), "mon", v))
    stale = invalidated(r.derivations, r.io)
    assert isinstance(e, Modified)
    assert stale == {"reports/mon/v000001": {"reports/mon/v000001"}}
    return Outcome(
        "a member of the committed version rewritten in place",
        "pinned read refused (Modified); the derivation reports the version modified",
        "construction, given the manifest digest from the commit (immutable "
        "members, with CAP_LINUX_IMMUTABLE, refuse the write itself)",
    )


SCENARIOS: list[Callable[[Path], Outcome]] = [
    honest,
    input_rewritten_after,
    input_rewritten_during,
    pair_updated_mid_entry,
    pair_updated_mid_entry_leased,
    staged_replaced_between,
    output_name_taken,
    landing_swapped_for_a_symlink,
    concurrent_producers,
    member_tampered,
]


def main() -> int:
    p = plan()
    print("before anything runs, for every day:")
    for (step, port), (known, refuted) in p.items():
        print(f"  {step}.{port}: known {sorted(known)}, refuted {sorted(refuted)}")
    twice = plan([*PIPELINE, ("validate again", Validate.step())])
    print(
        "  a pipeline validating twice: validate again.staged refuted",
        sorted(twice["validate again", "staged"][1]),
    )
    print()
    for scenario in SCENARIOS:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "root"
            base.mkdir()
            lay_out(base)
            o = scenario(base)
        print(f"{o.scenario}\n  {o.what_happened}\n  rests on: {o.rests_on}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
