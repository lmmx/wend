"""The synthesis of the research stack (docs/journal/2026-10-22-synthesis.md):
the example pipeline under each scheduled interference, and the minimal
counterexamples that decided its design.

- Exchange-and-validate is not a compare-and-swap: with three writers it
  loses an update and reports the survivor as the failure.
- A store of versions claimed with RENAME_NOREPLACE is: one claim wins and
  no loser is ever visible.
- A pinned directory is not a snapshot; a pinned version, verified against
  its manifest, reads only what was committed, and with immutable members
  nothing can change it (root only).
- A version is reclaimed only once no reader holds it."""

import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from wend._experimental import publish as pub
from wend._experimental.confined import Confined
from wend._experimental.publish import (
    Conflict,
    Draft,
    Generation,
    InUse,
    Modified,
    Store,
    _set_immutable,
    hold_dir,
    read_in,
)


sys.path.insert(0, str(Path(__file__).parents[1] / "experiments" / "synthesis"))
import pipeline  # type: ignore[import-not-found]  # noqa: E402


pytestmark = pytest.mark.linux


# -- the pipeline -------------------------------------------------------------


@pytest.fixture
def base(tmp_path):
    b = tmp_path / "root"
    b.mkdir()
    pipeline.lay_out(b)
    return b


@pytest.mark.parametrize("scenario", pipeline.SCENARIOS, ids=lambda s: s.__name__)
def test_the_pipeline_under_interference(base, scenario):
    outcome = scenario(base)  # each scenario asserts what it shows
    assert outcome.rests_on


def test_the_plan_knows_what_the_first_step_ensures_and_refutes_a_second_make():
    plan = pipeline.plan()
    assert plan["report", "staged"] == ({"file", "exists"}, set())
    twice = pipeline.plan([*pipeline.PIPELINE, ("again", pipeline.Validate.step())])
    assert twice["again", "staged"][1] == {"absent"}


# -- exchange-and-validate is not compare-and-swap ----------------------------


def scheduled_exchanges(monkeypatch, order):
    """Let each writer thread's n-th renameat2 run only at its place in
    ``order``: a deterministic interleaving of the writers' system calls."""
    real, cond, pos, counts = pub.renameat2, threading.Condition(), [0], {}

    def renameat2(*args):
        me = threading.current_thread().name
        counts[me] = counts.get(me, 0) + 1
        key = (me, counts[me])
        with cond:
            if not cond.wait_for(
                lambda: pos[0] >= len(order) or order[pos[0]] == key, timeout=5
            ):
                raise TimeoutError(key)
            real(*args)
            pos[0] += 1
            cond.notify_all()

    monkeypatch.setattr(pub, "renameat2", renameat2)


def writers(root, names, act):
    beliefs = {}

    def run(name):
        io = Confined(str(root))
        try:
            beliefs[name] = act(io, name)
        finally:
            io.close()

    ts = [threading.Thread(target=run, args=(n,), name=n) for n in names]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return beliefs


def test_exchange_and_validate_loses_an_update_with_three_writers(
    tmp_path, monkeypatch
):
    (tmp_path / "out").mkdir()
    final = tmp_path / "out" / "final.csv"
    final.write_bytes(b"X0")
    x0 = (final.stat().st_dev, final.stat().st_ino)

    def publish(io, name):
        d = Draft(io, "out")
        d.write(name.encode())
        try:
            d.publish("final.csv", policy="exchange", expect=x0, durable=False)
            return "published"
        except Conflict:
            return "conflict"

    # A swaps in and validates; B and C each swap in after it, see the
    # wrong object, and undo with a second, unconditional exchange. Each
    # undo swaps out whatever is there now, and the cleanup unlinks it.
    scheduled_exchanges(monkeypatch, [("A", 1), ("B", 1), ("C", 1), ("B", 2), ("C", 2)])
    beliefs = writers(tmp_path, "ABC", publish)
    assert beliefs == {"A": "published", "B": "conflict", "C": "conflict"}
    assert final.read_bytes() == b"B"  # the writer told it failed
    assert os.listdir(tmp_path / "out") == ["final.csv"]  # A's version is gone


def exchange_and_validate(n: int):
    """Every interleaving of ``n`` writers of the exchange-and-validate
    protocol, each system call one atomic step: exchange the draft into
    the name; if what came out is not the expected object, exchange back;
    unlink the temporary name. Only writer i touches its temporary name, so
    reading what came out is part of its exchange. Yields, per schedule,
    each writer's belief, what the name holds, and every object a reader
    could have seen at the name."""
    from itertools import permutations

    def run(order):
        names = {"final": "X0", **{f"t{i}": f"W{i}" for i in range(n)}}
        belief, seen, pc = {}, {"X0"}, [0] * n
        for i in order:
            t = f"t{i}"
            if pc[i] == 0:  # exchange in, and look at what came out
                names[t], names["final"] = names["final"], names[t]
                seen.add(names["final"])
                pc[i] = 1 if names[t] == "X0" else 2
            elif pc[i] == 1:  # it was the expected object: discard it
                del names[t]
                belief[i], pc[i] = "published", 9
            elif pc[i] == 2:  # it was not: exchange back
                names[t], names["final"] = names["final"], names[t]
                seen.add(names["final"])
                pc[i] = 3
            elif pc[i] == 3:  # and discard what came out this time
                del names[t]
                belief[i], pc[i] = "conflict", 9
            else:
                return None  # this writer had already finished
        return (belief, names["final"], seen) if all(c == 9 for c in pc) else None

    # a writer takes two steps if it publishes, three if it conflicts
    steps = [i for i in range(n) for _ in range(3)]
    done = set()
    for order in permutations(steps):
        key = tuple(i for i in order)
        if key in done:
            continue
        done.add(key)
        for cut in range(2 * n, 3 * n + 1):  # drop unused trailing steps
            out = run(order[:cut])
            if out is not None:
                yield order[:cut], out
                break


@pytest.mark.parametrize("n", [2, 3])
def test_exchange_and_validate_over_every_schedule(n):
    bad, withdrawn_seen = set(), set()
    for order, (belief, final, seen) in exchange_and_validate(n):
        winners = [i for i, b in belief.items() if b == "published"]
        right = winners == [int(final[1:])] if final != "X0" else not winners
        if not right:
            bad.add(order)
        if seen - {"X0", final}:
            withdrawn_seen.add(order)  # a reader could see a version not kept
    if n == 2:
        # Two writers always end right, but a reader can meet the loser.
        assert not bad and withdrawn_seen
    else:
        # Three can end wrong: a writer told "published" whose version is
        # gone, or a version kept whose writer was told "conflict".
        assert bad


def test_a_claimed_version_has_one_winner_and_no_visible_loser(tmp_path):
    (tmp_path / "reports").mkdir()
    ready = threading.Barrier(3)
    seen: list[list[str]] = []

    def claim(io, name):
        v = Store(io, "reports").begin(None)  # each read "no version yet"
        v.add("summary.csv", name.encode())
        v.add("by_sku.csv", name.encode())
        ready.wait()
        try:
            v.commit()
            return "published"
        except Conflict:
            seen.append(sorted(os.listdir(tmp_path / "reports")))
            return "conflict"

    beliefs = writers(tmp_path, "ABC", claim)
    (winner,) = [n for n, b in beliefs.items() if b == "published"]
    assert sorted(beliefs.values()) == ["conflict", "conflict", "published"]
    io = Confined(str(tmp_path))
    try:
        with Store(io, "reports").pin(1) as p:
            pair = (p.read("summary.csv"), p.read("by_sku.csv"))
    finally:
        io.close()
    assert pair == (winner.encode(), winner.encode())  # beliefs match the state
    assert os.listdir(tmp_path / "reports") == ["v000001"]  # no loser left


# -- what pins a generation ---------------------------------------------------


def test_a_pinned_directory_is_not_a_snapshot(tmp_path):
    io = Confined(str(tmp_path))
    try:
        g = Generation(io, "", "current")
        g.add("a.csv", b"A1")
        g.add("b.csv", b"B1")
        g.commit()
        held = hold_dir(io, "current")
        assert read_in(held, "a.csv") == b"A1"
        # another writer, in place, through any name for the same object
        fd = os.open(tmp_path / "current" / "b.csv", os.O_WRONLY | os.O_TRUNC)
        os.write(fd, b"B9")
        os.close(fd)
        assert read_in(held, "b.csv") == b"B9"  # the pin held the directory only
        os.close(held)
    finally:
        io.close()


@pytest.fixture
def store(tmp_path):
    (tmp_path / "reports").mkdir()
    io = Confined(str(tmp_path))
    yield io, Store(io, "reports")
    io.close()


def commit(store, summary, by_sku, **kw):
    v = store.begin(store.latest())
    v.add("summary.csv", summary)
    v.add("by_sku.csv", by_sku)
    return v.commit(**kw)


def test_a_pinned_version_refuses_a_member_changed_since_its_commit(store, tmp_path):
    io, s = store
    v = commit(s, b"total 3", b"apple 3")
    (tmp_path / "reports" / "v000001" / "by_sku.csv").write_bytes(b"apple 9")
    with s.pin(v.n) as p:
        assert p.read("summary.csv") == b"total 3"
        with pytest.raises(Modified):
            p.read("by_sku.csv")
    assert not v.current(io)


def test_a_rewritten_manifest_is_caught_only_by_the_digest_the_commit_returned(
    store, tmp_path
):
    io, s = store
    v = commit(s, b"total 3", b"apple 3")
    d = tmp_path / "reports" / "v000001"
    (d / "by_sku.csv").write_bytes(b"apple 9")
    lines = (d / "MANIFEST").read_text().splitlines()
    forged = [
        f"by_sku.csv {pub._digest(b'apple 9')}" if ln.startswith("by_sku") else ln
        for ln in lines
    ]
    (d / "MANIFEST").write_text("\n".join(forged) + "\n")
    with s.pin(v.n) as p:  # trusting the directory: the forgery reads
        assert p.read("by_sku.csv") == b"apple 9"
    with pytest.raises(Modified):  # trusting the commit's record: refused
        s.pin(v.n, manifest=v.manifest)


def immutable_supported(tmp_path: Path) -> bool:
    if os.geteuid() != 0:
        return False
    p = tmp_path / ".probe"
    p.write_bytes(b"")
    fd = os.open(p, os.O_RDONLY)
    try:
        _set_immutable(fd)
        _set_immutable(fd, False)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)
        p.unlink()


# A writer holding a shared mapping made before the flag: the page faulted in
# (clean), or written with the byte already there (dirty). It writes once told
# the flag is set.
MAPPED = r"""
import mmap, sys
fd, dirty = int(sys.argv[1]), sys.argv[2] == "dirty"
m = mmap.mmap(fd, 4096)
b = m[0:1]
if dirty:
    m[0:1] = b
print("mapped", flush=True)
sys.stdin.readline()
m[0:1] = b"X"
"""


@pytest.mark.privileged
def test_immutable_members_refuse_every_writer_tried(store, tmp_path):
    if not immutable_supported(tmp_path):
        pytest.skip("needs CAP_LINUX_IMMUTABLE on a filesystem with FS_IMMUTABLE_FL")
    io, s = store
    d = tmp_path / "reports" / "v000001"
    # writers that got in before the flag: a descriptor, and shared mappings
    early: dict[str, object] = {}
    mapped: dict[str, subprocess.Popen[str]] = {}

    def before_flag(*a, **k):
        if "fd" not in early:  # just before the first flag is set
            hidden = next(d.parent.glob(".v*"))
            fd = early["fd"] = os.open(hidden / "by_sku.csv", os.O_RDWR)
            for page in ("clean", "dirty"):
                c = mapped[page] = subprocess.Popen(
                    [sys.executable, "-c", MAPPED, str(fd), page],
                    pass_fds=(fd,),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                )
                assert c.stdout is not None and c.stdout.readline() == "mapped\n"
        return real(*a, **k)

    real = pub._set_immutable
    pub._set_immutable = before_flag
    try:
        v = commit(s, b"total 3", b"apple 3" * 1000, immutable=True)
    finally:
        pub._set_immutable = real
    fd = early["fd"]
    assert isinstance(fd, int)
    try:
        member = d / "by_sku.csv"
        moves = {
            "open for writing": lambda: os.open(member, os.O_WRONLY),
            "write through a descriptor opened before": lambda: os.pwrite(fd, b"X", 0),
            "truncate": lambda: os.ftruncate(fd, 0),
            "rename": lambda: os.rename(member, d / "other"),
            "unlink": lambda: os.unlink(member),
            "link": lambda: os.link(member, tmp_path / "alias"),
            "add a file to the version": lambda: (d / "extra").write_bytes(b""),
            "rename the version": lambda: os.rename(d, d.parent / "v000009"),
        }
        for move, act in moves.items():
            with pytest.raises(PermissionError):
                act()
            assert move
        # through a shared mapping made before the flag, its page clean or
        # dirty: SIGBUS
        for page, c in mapped.items():
            c.communicate("go\n", timeout=30)
            assert (page, c.returncode) == (page, -signal.SIGBUS)
        # and through one made after it with the early descriptor: SIGBUS
        child = subprocess.run(
            [sys.executable, "-c", f"import mmap; mmap.mmap({fd}, 4096)[0:1] = b'X'"],
            pass_fds=(fd,),
            capture_output=True,
        )
        assert child.returncode == -signal.SIGBUS
        assert v.current(io)  # every member reads as committed
    finally:
        os.close(fd)
        commit(s, b"total 4", b"apple 4")  # so v1 is not the latest
        s.reclaim(1)  # clears the flags, so the tree can be removed
    assert s.versions() == [2]


@pytest.mark.privileged
def test_a_claim_that_fails_after_flagging_its_members_leaves_nothing(
    store, tmp_path, monkeypatch
):
    if not immutable_supported(tmp_path):
        pytest.skip("needs CAP_LINUX_IMMUTABLE on a filesystem with FS_IMMUTABLE_FL")
    io, s = store

    def failing(*args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pub, "renameat2", failing)
    with pytest.raises(OSError, match="No space"):
        commit(s, b"total 3", b"apple 3", immutable=True)
    # Found by an earlier version of commit, which left the flagged draft
    # behind: a directory nothing without the capability could remove.
    assert os.listdir(tmp_path / "reports") == []


def test_a_version_is_reclaimed_only_once_no_reader_holds_it(store, tmp_path):
    io, s = store
    commit(s, b"total 3", b"apple 3")
    with pytest.raises(ValueError, match="latest"):
        s.reclaim(1)
    commit(s, b"total 4", b"apple 4")
    with s.pin(1) as p:
        with pytest.raises(InUse):
            s.reclaim(1)
        assert p.read("summary.csv") == b"total 3"  # still whole
    # A reader that opened the version just before it was reclaimed waits
    # for the lease, then finds no manifest: it fails, rather than mixing.
    late = io._dir("reports/v000001")
    s.reclaim(1)
    with pytest.raises(FileNotFoundError):
        read_in(late, "MANIFEST")
    os.close(late)
    assert s.versions() == [2]
    shutil.rmtree(tmp_path / "reports")
