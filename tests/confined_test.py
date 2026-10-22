"""wend._experimental.confined: pipelines over path families, planned once by
the analysis of families and run with its known checks elided.

Without interference, a confined run with the plan's elisions completes the
same steps and leaves the same tree as a plain run that checks everything.
With another writer acting between steps and between checks and use (links
to outside the root, bind mounts, deletions, files planted), a confined run
never reads, writes or deletes outside the root; plain runs, checked or
not, do."""

import ctypes
import errno
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest
from families_test import ENVS, FAMILIES, bound, cases, make_tree
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from knowledge_test import ROLES

from wend import P, Param, Step, T
from wend._experimental.confined import Confined, Plain, run
from wend._experimental.families import analyse_families
from wend.errors import ConditionError


pytestmark = pytest.mark.linux


SECRET = b"SECRET"


def bodies_for(reads: list):
    return {
        "read": lambda io, rel: reads.append(io.read_bytes(rel)),
        "create": lambda io, rel: io.create(rel, b"new"),
        "write": lambda io, rel: io.write_bytes(rel, b"more"),
        "delete": lambda io, rel: io.delete(rel),
        "list": lambda io, rel: io.listdir(rel),
        "mkdir": lambda io, rel: io.mkdir(rel),
    }


def build(pipeline, reads: list):
    io_bodies = bodies_for(reads)
    steps, bodies = [], []
    for i, ps in enumerate(pipeline):
        paths, b = {}, []
        for j, (role, fam) in enumerate(ps):
            pre, post, _ = ROLES[role]
            e = FAMILIES[fam].requires(*pre)
            if post:
                e = e.ensures(*post)
            paths[f"p{j}"] = e
            b.append((f"p{j}", io_bodies[role]))
        steps.append((f"s{i}", Step(paths)))
        bodies.append(b)
    return steps, bodies


def plan(steps) -> dict:
    return {(e.step, e.port): e.known for e in analyse_families(steps)}


def tree_of(d: Path) -> list:
    out = []
    for p in sorted(d.rglob("*")):
        kind = "link" if p.is_symlink() else "dir" if p.is_dir() else "file"
        data = p.read_bytes() if kind == "file" else b""
        out.append((str(p.relative_to(d)), kind, data))
    return out


# -- without interference ------------------------------------------------------

SETTINGS = settings(
    max_examples=200, deadline=None, suppress_health_check=list(HealthCheck)
)


@SETTINGS
@given(cases)
def test_a_confined_run_of_the_plan_is_a_checked_plain_run(case):
    pipeline, tree = case
    for env0 in ENVS:
        results = []
        for kind in ("plain", "confined"):
            with tempfile.TemporaryDirectory() as d:
                env = bound(env0, d)
                make_tree(Path(d), tree)
                reads: list = []
                steps, bodies = build(pipeline, reads)
                io = Plain(d) if kind == "plain" else Confined(d)
                try:
                    done = run(
                        steps,
                        bodies,
                        env,
                        io,
                        elide=plan(steps) if kind == "confined" else None,
                    )
                finally:
                    io.close()
                results.append((done, tree_of(Path(d)), reads))
        assert results[0] == results[1], env0


# -- another writer -------------------------------------------------------------

ACTIONS = [
    "link_file",
    "link_dir",
    "dangle",
    "delete",
    "plant",
    "mount",
    "hardlink",
    "fifo",
]


def _bind(src: Path, dst: Path) -> bool:
    return (
        subprocess.run(
            ["mount", "--bind", str(src), str(dst)], capture_output=True
        ).returncode
        == 0
    )


class Writer:
    """Another writer: acts on the tree below ``root`` at scheduled points,
    by the same rules whichever executor runs, pointing what it makes at
    ``outside``."""

    def __init__(self, root: Path, outside: Path, schedule, names):
        self.root, self.outside, self.schedule, self.names = (
            root,
            outside,
            schedule,
            names,
        )
        self.mounts: list[Path] = []
        self.n = 0

    def _near_mount(self, p: Path) -> bool:
        """Whether acting on ``p`` would act through one of its own mounts
        (and so change what lies outside the root itself)."""
        return any(m == p or m in p.parents or p in m.parents for m in self.mounts)

    def _existing(self, want):
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_symlink() or self._near_mount(p):
                continue
            if want(p):
                out.append(p)
        return out

    def _missing(self):
        out = []
        for n in self.names:
            p = self.root / n
            if os.path.lexists(p) or self._near_mount(p):
                continue
            out.append(p)
        return out

    def __call__(self, point: str, i: int) -> None:
        for at, step, action, k in self.schedule:
            if (at, step) == (point, i):
                try:
                    self._act(action, k)
                except OSError:
                    pass  # a move that does not apply to this tree

    def _act(self, action: str, k: int) -> None:
        self.n += 1
        if action == "link_file":
            files = self._existing(Path.is_file)
            if files:
                p = files[k % len(files)]
                p.unlink()
                p.symlink_to(self.outside / "secret")
        elif action == "link_dir":
            dirs = self._existing(Path.is_dir)
            if dirs:
                p = dirs[k % len(dirs)]
                shutil.rmtree(p)
                p.symlink_to(self.outside / "sdir")
        elif action == "dangle":
            missing = [
                p
                for p in self._missing()
                if p.parent.is_dir() and not p.parent.is_symlink()
            ]
            if missing:
                missing[k % len(missing)].symlink_to(self.outside / f"made{self.n}")
        elif action == "delete":
            paths = self._existing(lambda p: True)
            if paths:
                p = paths[k % len(paths)]
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        elif action == "plant":
            missing = [
                p for p in self._missing() if not any(q.is_symlink() for q in p.parents)
            ]
            if missing:
                p = missing[k % len(missing)]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"planted")
        elif action == "hardlink":
            # another name for a file outside: no symlink, no mount
            files = self._existing(Path.is_file)
            if files:
                p = files[k % len(files)]
                p.unlink()
                os.link(self.outside / "secret", p)
        elif action == "fifo":
            missing = [
                p
                for p in self._missing()
                if p.parent.is_dir() and not p.parent.is_symlink()
            ]
            if missing:
                os.mkfifo(missing[k % len(missing)])
        elif action == "mount":
            dirs = self._existing(Path.is_dir)
            if dirs and len(self.mounts) < 2:
                p = dirs[k % len(dirs)]
                if _bind(self.outside / "sdir", p):
                    self.mounts.append(p)

    def unmount(self) -> None:
        for m in reversed(self.mounts):
            subprocess.run(["umount", "-l", str(m)], capture_output=True)


def make_outside(o: Path) -> None:
    (o / "sdir").mkdir(parents=True)
    (o / "secret").write_bytes(SECRET)
    for n in ("mon.csv", "tue.csv", "mon.parquet", "a"):
        (o / "sdir" / n).write_bytes(SECRET)


def names_of(pipeline, env) -> list[str]:
    out = set()
    for ps in pipeline:
        for _, fam in ps:
            try:
                path = FAMILIES[fam].render(env)
            except Exception:  # noqa: BLE001 - an unbindable family names nothing
                continue
            rel = os.path.relpath(path, env["root"])
            if not rel.startswith(".."):
                out.add(rel)
    return sorted(out)


def executor(kind: str, root: Path):
    """``checked``: plain, every check made; ``plain``: plain, the plan's
    checks elided; ``-w``: creating as ``open(p, "w")`` does, not
    exclusively; ``confined``: the plan's checks elided, everything beneath
    the root."""
    if kind == "confined":
        return Confined(str(root))
    return Plain(str(root), exclusive=not kind.endswith("-w"))


def escapes(kind: str, pipeline, tree, env0, schedule) -> tuple[bool, list[bool]]:
    """Run under the writer; whether anything outside the root was read,
    written or deleted, and which steps completed."""
    with tempfile.TemporaryDirectory() as d:
        root, outside = Path(d) / "root", Path(d) / "outside"
        root.mkdir()
        make_outside(outside)
        before = tree_of(outside)
        env = bound(env0, str(root))
        make_tree(root, tree)
        reads: list = []
        steps, bodies = build(pipeline, reads)
        w = Writer(root, outside, schedule, names_of(pipeline, env))
        io = executor(kind, root)
        try:
            elide = None if kind.startswith("checked") else plan(steps)
            done = run(steps, bodies, env, io, elide=elide, between=w)
        finally:
            io.close()
            w.unmount()
        escaped = any(SECRET in r for r in reads) or tree_of(outside) != before
        return escaped, done


schedules = st.lists(
    st.tuples(
        st.sampled_from(["step", "use"]),
        st.integers(0, 5),
        st.sampled_from(ACTIONS),
        st.integers(0, 50),
    ),
    min_size=1,
    max_size=4,
)


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(cases, st.sampled_from(range(len(ENVS))), schedules)
def test_a_confined_run_never_reaches_outside_the_root(case, e, schedule):
    pipeline, tree = case
    escaped, _ = escapes("confined", pipeline, tree, ENVS[e], schedule)
    assert not escaped


# -- each move, against each executor ------------------------------------------

root_p, day = Param("root"), Param("day")
raw = P(root_p) / "raw" / T(t"{day}.csv")
out = P(root_p) / "out" / T(t"{day}.csv")


def _pipeline():
    pre_r, _, _ = ROLES["read"]
    pre_c, post_c, _ = ROLES["create"]
    pre_d, post_d, _ = ROLES["delete"]
    return [
        ("make", Step(x=raw.requires(*pre_c).ensures(*post_c))),
        ("read", Step(x=raw.requires(*pre_r))),
        (
            "copy",
            Step(src=raw.requires(*pre_r), dst=out.requires(*pre_c).ensures(*post_c)),
        ),
        ("drop", Step(x=out.requires(*pre_d).ensures(*post_d))),
        ("remake", Step(x=out.requires(*pre_c).ensures(*post_c))),  # absent: known
    ]


def _bodies(reads):
    b = bodies_for(reads)
    return [
        [("x", b["create"])],
        [("x", b["read"])],
        [("src", b["read"]), ("dst", b["create"])],
        [("x", b["delete"])],
        [("x", b["create"])],
    ]


PLAIN = {"checked", "checked-w", "plain", "plain-w"}


@pytest.mark.parametrize(
    ("move", "escaped_by"),
    [
        # Before "read": its checks follow the link, so checking them is no
        # defence (only Under's realpath would be, and only when checked).
        (("step", 1, "raw/mon.csv", "link_file"), PLAIN),
        # The same file, by another name: no symlink and no mount to refuse.
        (("step", 1, "raw/mon.csv", "hardlink"), PLAIN),
        # Between the checks of "copy" and its bodies, a time-of-check race:
        # exclusive creation refuses a link at the name, not one above it.
        (("use", 2, "out/mon.csv", "dangle"), {"checked-w", "plain-w"}),
        (("use", 2, "out", "link_dir"), PLAIN),
        (("use", 3, "out", "mount"), PLAIN),  # drop deletes through it
        # Before "remake", whose Absent the plan knows (drop ensured it): a
        # check would refuse the link (lstat sees it); elided, it is written
        # through. The identity model's first counterexample, in a pipeline.
        (("step", 4, "out/mon.csv", "dangle"), {"plain-w"}),
    ],
)
@pytest.mark.privileged
def test_each_move_escapes_a_plain_run_and_is_refused_by_a_confined_one(
    move, escaped_by
):
    at, i, target, action = move
    outcome = {}
    for kind in (*sorted(PLAIN), "confined"):
        with tempfile.TemporaryDirectory() as d:
            root, outside = Path(d) / "root", Path(d) / "outside"
            (root / "out").mkdir(parents=True)
            make_outside(outside)
            before = tree_of(outside)
            mounted = []

            def between(point, j):
                if (point, j) != (at, i):
                    return
                p = root / target
                if action == "link_file":
                    p.unlink()
                    p.symlink_to(outside / "secret")
                elif action == "hardlink":
                    p.unlink()
                    os.link(outside / "secret", p)
                elif action == "dangle":
                    p.symlink_to(outside / "planted")
                elif action == "link_dir":
                    shutil.rmtree(p)
                    p.symlink_to(outside / "sdir")
                elif action == "mount":
                    if not _bind(outside / "sdir", p):
                        pytest.skip("cannot bind-mount here")
                    mounted.append(p)

            reads: list = []
            steps = _pipeline()
            io = executor(kind, root)
            try:
                done = run(
                    steps,
                    _bodies(reads),
                    {"root": str(root), "day": "mon"},
                    io,
                    elide=None if kind.startswith("checked") else plan(steps),
                    between=between,
                )
            finally:
                io.close()
                for m in mounted:
                    subprocess.run(["umount", "-l", str(m)])
            outcome[kind] = (
                any(SECRET in r for r in reads) or tree_of(outside) != before,
                done,
            )
    assert {k for k, (esc, _) in outcome.items() if esc} == escaped_by, outcome
    assert not all(outcome["confined"][1])  # the confined run failed instead


def test_under_resolving_inside_the_root_is_a_fact_of_the_moment(tmp_path):
    # Under has two halves: the rendered string lies below the base (render
    # enforces it, and it never changes), and its realpath does too (checked,
    # true then, and changed by any swap of a name on the way).
    from wend import Exists, File, Readable, Under

    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "raw").mkdir(parents=True)
    make_outside(outside)
    x = root / "raw" / "x"
    x.write_text("mine")
    e = (P(str(root)) / "raw" / "x").requires(
        Under(P(str(root))), File, Exists, Readable
    )
    e.check()  # time of check ...
    x.unlink()
    x.symlink_to(outside / "secret")
    assert x.read_bytes() == SECRET  # ... and of use
    with pytest.raises(ValueError, match="resolves outside"):
        e.check()  # a check now would have refused it
    io = Confined(str(root))
    try:
        with pytest.raises(OSError):
            io.read_bytes("raw/x")
    finally:
        io.close()


@pytest.mark.parametrize("kind", ["checked", "confined"])
def test_an_alias_inside_the_root_is_refused_not_only_escapes(kind):
    # RESOLVE_BENEATH alone stops every escape. An alias between two stages
    # of one root escapes nothing, yet breaks the plan's string identity:
    # with out/ made a link to raw/ after drop's checks, deleting
    # out/mon.csv deletes the source, raw/mon.csv, of which the plan still
    # knows that it exists.
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "out").mkdir()

        def between(point, j):
            if (point, j) == ("use", 3):
                shutil.rmtree(root / "out")
                (root / "out").symlink_to("raw")

        steps = _pipeline()[:4]
        io = executor(kind, root)
        try:
            done = run(
                steps,
                _bodies([])[:4],
                {"root": str(root), "day": "mon"},
                io,
                elide=plan(steps),
                between=between,
            )
        finally:
            io.close()
        source = (root / "raw" / "mon.csv").exists()
        assert (done, source) == (
            ([True, True, True, False], True)
            if kind == "confined"
            else ([True] * 4, False)
        )


@pytest.mark.privileged
@pytest.mark.parametrize("kind", ["checked", "confined"])
def test_deleting_a_tree_does_not_descend_into_a_mount_below_it(kind):
    with tempfile.TemporaryDirectory() as d:
        root, outside = Path(d) / "root", Path(d) / "outside"
        (root / "out" / "sub").mkdir(parents=True)
        make_outside(outside)
        before = tree_of(outside)
        if not _bind(outside / "sdir", root / "out" / "sub"):
            pytest.skip("cannot bind-mount here")
        io = executor(kind, root)
        try:
            pre, post, _ = ROLES["delete"]
            steps = [
                ("drop", Step(x=(P(str(root)) / "out").requires(*pre).ensures(*post)))
            ]
            done = run(steps, [[("x", bodies_for([])["delete"])]], {}, io)
        finally:
            io.close()
            subprocess.run(["umount", "-l", str(root / "out" / "sub")])
        reached = tree_of(outside) != before
        # a plain rmtree empties the mount, then fails to remove it (EBUSY)
        assert reached is (kind != "confined")
        assert done == [False]


@pytest.mark.parametrize("kind", ["checked", "confined"])
def test_making_parents_does_not_follow_a_link_on_the_way(kind):
    # out/ becomes a link out of the root after the checks; creating
    # out/new/x.csv makes new/ (and the file) wherever the link points,
    # unless every directory on the way is made and opened beneath the root.
    with tempfile.TemporaryDirectory() as d:
        root, outside = Path(d) / "root", Path(d) / "outside"
        (root / "out").mkdir(parents=True)
        make_outside(outside)
        before = tree_of(outside)

        def between(point, j):
            if point == "use":
                (root / "out").rmdir()
                (root / "out").symlink_to(outside / "sdir")

        x = P(str(root)) / "out" / "new" / "x.csv"
        pre, post, _ = ROLES["create"]
        io = executor(kind, root)
        try:
            steps = [("make", Step(x=x.requires(*pre).ensures(*post)))]
            done = run(
                steps, [[("x", bodies_for([])["create"])]], {}, io, between=between
            )
        finally:
            io.close()
        reached = tree_of(outside) != before
        assert (done, reached) == (
            ([False], False) if kind == "confined" else ([True], True)
        )


def test_writing_a_hard_linked_file_refuses_before_truncating(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    make_outside(outside)
    os.link(outside / "secret", root / "x")
    io = Confined(str(root))
    try:
        with pytest.raises(ConditionError, match="hard links"):
            io.write_bytes("x", b"over")
    finally:
        io.close()
    assert (outside / "secret").read_bytes() == SECRET  # O_TRUNC would have emptied it


def test_a_planted_fifo_is_refused_at_once_and_blocks_a_plain_read(tmp_path):
    os.mkfifo(tmp_path / "x")
    io = Confined(str(tmp_path))
    try:
        with pytest.raises(ConditionError, match="neither a regular file"):
            io.read_bytes("x")
    finally:
        io.close()
    t = threading.Thread(
        target=lambda: Plain(str(tmp_path)).read_bytes("x"), daemon=True
    )
    t.start()
    t.join(0.5)
    assert t.is_alive()  # waiting for a writer that never comes
    with open(tmp_path / "x", "wb"):  # release it
        pass


def test_no_fallback_where_openat2_is_unavailable(tmp_path, monkeypatch):
    # Elsewhere the system call number means something else: refuse before
    # calling it. Where the kernel or a seccomp filter lacks it, refuse at
    # construction, not at the first access.
    from wend._experimental import identity

    monkeypatch.setattr(identity.sys, "platform", "darwin")
    with pytest.raises(identity.UnsupportedPlatformError):
        Confined(str(tmp_path))
    monkeypatch.undo()

    def no_openat2(*args):
        ctypes.set_errno(errno.ENOSYS)
        return -1

    identity.openat2(os.open(tmp_path, os.O_PATH), ".", os.O_PATH, 0)  # loads _syscall
    monkeypatch.setattr(identity, "_syscall", no_openat2)
    with pytest.raises(identity.UnsupportedPlatformError):
        Confined(str(tmp_path))

    def filtered(*args):
        ctypes.set_errno(errno.EPERM)
        return -1

    monkeypatch.setattr(identity, "_syscall", filtered)
    with pytest.raises(identity.UnsupportedPlatformError):
        Confined(str(tmp_path))
