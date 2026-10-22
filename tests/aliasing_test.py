"""When two strings name one file: symlinks, bind mounts, ``..`` spellings,
hard links, and writers outside the program.

The string-keyed tracker (wend._experimental.knowledge) goes wrong on each
alias, and these tests show it on disk; the identity-keyed tracker
(wend._experimental.identity) keeps every known fact true, on targeted
cases and on random trees with aliases. A writer outside the program
breaks both, as the closed world says it must; an open file survives it."""

import errno
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import Absent, Creatable, Dir, Exists, File, P, Readable, Step, Writable
from wend._experimental.identity import Beneath, Held, IdentityTracker, resolve
from wend._experimental.knowledge import Fact, Tracker, holds
from wend.conditions import check_conditions
from wend.errors import ConditionError


def reads(p):
    return Step(x=P(str(p)).requires(File, Exists, Readable))


def deletes(p):
    return Step(x=P(str(p)).requires(Exists).ensures(Absent))


def stale(t) -> list:
    """Known facts that are false now."""
    if isinstance(t, IdentityTracker):
        return [
            f for f in t.knowledge.facts if holds(Fact(f.atom, f.trace.path)) is False
        ]
    return [f for f in t.knowledge.facts if holds(f) is False]


def drive(t, steps):
    for name, step, body in steps:
        with t.run(name, step, {}) as p:
            if body:
                body(p["x"])


def both(make_tree, steps):
    out = []
    for cls in (Tracker, IdentityTracker):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_tree(root)
            t = cls()
            drive(t, steps(root))
            out.append(stale(t))
    return out


def test_a_symlinked_directory_is_one_directory():
    def tree(r):
        (r / "d").mkdir()
        (r / "d" / "x").write_text("x")
        (r / "link").symlink_to(r / "d")

    def steps(r):
        return [
            ("read", reads(r / "link" / "x"), None),
            ("drop", deletes(r / "d" / "x"), Path.unlink),
        ]

    by_string, by_entry = both(tree, steps)
    assert by_string and not by_entry  # exists(link/x) known, and false


def test_a_dotdot_spelling_is_the_same_file():
    def tree(r):
        (r / "d").mkdir()
        (r / "a").write_text("a")

    def steps(r):
        return [
            ("read", reads(r / "d" / ".." / "a"), None),
            ("drop", deletes(r / "a"), Path.unlink),
        ]

    by_string, by_entry = both(tree, steps)
    assert by_string and not by_entry


def test_lexical_normalisation_is_not_the_answer():
    # d/../a is a, unless d is a symlink: then it is the link target's parent's a.
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "far" / "deep").mkdir(parents=True)
        (r / "far" / "a").write_text("far")
        (r / "a").write_text("near")
        (r / "d").symlink_to(r / "far" / "deep")
        assert (r / "d" / ".." / "a").read_text() == "far"
        assert os.path.normpath(r / "d" / ".." / "a") == str(r / "a")
        assert (
            resolve(str(r / "d" / ".." / "a")).final
            == resolve(str(r / "far" / "a")).final
        )


def _bind(src: Path, dst: Path, *opts: str) -> bool:
    dst.mkdir()
    o = ["-o", ",".join(opts)] if opts else []
    return (
        subprocess.run(
            ["mount", "--bind", *o, str(src), str(dst)], capture_output=True
        ).returncode
        == 0
    )


def test_a_bind_mount_is_one_directory():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "d").mkdir()
        (r / "d" / "x").write_text("x")
        if not _bind(r / "d", r / "m"):
            pytest.skip("cannot bind-mount here")
        try:
            results = []
            for cls in (Tracker, IdentityTracker):
                (r / "d" / "x").write_text("x")
                t = cls()
                drive(
                    t,
                    [
                        ("read", reads(r / "m" / "x"), None),
                        ("drop", deletes(r / "d" / "x"), Path.unlink),
                    ],
                )
                results.append(stale(t))
        finally:
            subprocess.run(["umount", "-l", str(r / "m")])
        by_string, by_entry = results
        assert by_string and not by_entry


def test_deleting_a_directory_reached_through_a_bind_mount():
    # m/x is below d, through another entry: only d's identity connects them.
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "d").mkdir()
        (r / "d" / "x").write_text("x")
        if not _bind(r / "d", r / "m"):
            pytest.skip("cannot bind-mount here")
        try:
            t = IdentityTracker()
            drive(t, [("read", reads(r / "m" / "x"), None)])
            drive(t, [("drop", deletes(r / "d"), shutil.rmtree)])
            assert not stale(t)
            assert not t.knowledge.knows("exists", resolve(str(r / "m" / "x")))
        finally:
            subprocess.run(["umount", "-l", str(r / "m")])


def test_facts_about_a_missing_path_are_facts_about_its_first_missing_entry():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        t = IdentityTracker()
        drive(t, [("gone", Step(x=P(str(r / "e" / "w")).requires(Absent)), None)])
        assert t.knowledge.knows("absent", resolve(str(r / "e" / "z")))
        with t.run("may", Step(x=P(str(r / "e" / "w")).requires(Creatable)), {}):
            assert t.knowledge.knows("create", resolve(str(r / "e" / "z" / "deeper")))


def test_an_output_made_as_a_symlink_follows_its_target():
    # A step that ensures File may make a symlink to a file: File follows it.
    def tree(r):
        (r / "t").write_text("t")

    def make_link(p):
        p.symlink_to(p.parent / "t")

    def steps(r):
        made = Step(x=P(str(r / "o")).requires(Absent, Creatable).ensures(File, Exists))
        return [("make", made, make_link), ("drop", deletes(r / "t"), Path.unlink)]

    by_string, by_entry = both(tree, steps)
    assert by_string and not by_entry  # exists(o) known, and o now dangles


def test_hard_links_keep_the_atoms_and_break_content():
    # Two entries, one file: deleting one leaves the other, so no atom goes
    # stale; but writing through one changes what the other holds.
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "a").write_text("one")
        os.link(r / "a", r / "b")
        for cls in (Tracker, IdentityTracker):
            t = cls()
            drive(t, [("read", reads(r / "b"), None)])
            drive(
                t,
                [
                    (
                        "write",
                        Step(
                            x=P(str(r / "a"))
                            .requires(File, Exists, Writable)
                            .ensures(File, Exists)
                        ),
                        lambda p: p.write_text("two"),
                    )
                ],
            )
            assert not stale(t)
        assert (r / "b").read_text() == "two"


def test_two_names_of_one_object_are_forgotten_together():
    # A case-insensitive filesystem's Data and data are, like hard links, two
    # entries for one object; keyed by the object too, a mutation through
    # one forgets the other. (Case folding itself cannot be mounted here.)
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "a").write_text("one")
        os.link(r / "a", r / "b")
        t = IdentityTracker()
        drive(t, [("read", reads(r / "b"), None)])
        assert t.knowledge.knows("exists", resolve(str(r / "b")))
        drive(
            t,
            [
                (
                    "write",
                    Step(
                        x=P(str(r / "a"))
                        .requires(File, Exists, Writable)
                        .ensures(File, Exists)
                    ),
                    lambda p: p.write_text("two"),
                )
            ],
        )
        assert not t.knowledge.knows("read", resolve(str(r / "b")))


def test_a_writer_outside_the_program_breaks_any_knowledge_of_names():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "x").write_text("x")
        for cls in (Tracker, IdentityTracker):
            t = cls()
            drive(t, [("read", reads(r / "x"), None)])
            (r / "x").unlink()  # not a step: the closed world is broken
            assert stale(t)
            (r / "x").write_text("x")


def test_an_open_file_survives_a_swap_of_its_name():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "x").write_text("mine")
        (r / "evil").write_text("theirs")
        with Held(str(r / "x")) as h:
            assert h.is_file
            (r / "x").unlink()  # time of check ...
            (r / "x").symlink_to(r / "evil")  # ... and of use
            assert h.read() == b"mine"
            assert (r / "x").read_text() == "theirs"


# -- random trees with aliases ------------------------------------------------

# Spellings in classes that can name one entry, or one below another.
CLASSES = [
    ["d/x", "link/x", "lx", "lx/q"], ["a", "d/../a", "link/../a", "a/q"],
    ["d/s/z", "ls/z"], ["e/z", "e/w"], ["d/y", "link/y"], ["b"],
]  # fmt: skip
SPELLINGS = [s for c in CLASSES for s in c]
ROLES = {
    "read": ((File, Exists, Readable), (), lambda p: p.read_bytes()),
    "create": (
        (Absent, Creatable),
        (File, Exists),
        lambda p: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text("n")),
    ),
    "write": ((File, Exists, Writable), (File, Exists), lambda p: p.write_text("w")),
    "delete": (
        (Exists,),
        (Absent,),
        lambda p: shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink(),
    ),
    "mkdir": ((Absent, Creatable), (Dir, Exists), lambda p: p.mkdir(parents=True)),
    "probe": ((File,), (), lambda p: None),  # if it exists, it is a file
}
trees = st.fixed_dictionaries(
    {"a": st.booleans(), "x": st.booleans(), "sub": st.booleans(), "lx": st.booleans()}
)


@st.composite
def pipelines(draw):
    """Steps whose spellings often alias an earlier step's: half are drawn
    from the class of a spelling already used."""
    out: list[tuple[str, str]] = []
    for _ in range(draw(st.integers(2, 8))):
        role = draw(st.sampled_from(sorted(ROLES)))
        if out and draw(st.booleans()):
            prev = draw(st.sampled_from([sp for _, sp in out]))
            spelling = draw(st.sampled_from(next(c for c in CLASSES if prev in c)))
        else:
            spelling = draw(st.sampled_from(SPELLINGS))
        out.append((role, spelling))
    return out


def alias_tree(r: Path, t: dict) -> None:
    (r / "d").mkdir()
    (r / "link").symlink_to(r / "d")
    (r / "ls").symlink_to("d/s")  # dangles unless d/s is made
    if t["a"]:
        (r / "a").write_text("a")
    if t["x"]:
        (r / "d" / "x").write_text("x")
    if t["sub"]:
        (r / "d" / "s").mkdir()
    if t["lx"]:
        (r / "lx").symlink_to("d/x")


def run_alias(cls, r: Path, pipeline, *, elide: bool = False):
    """Run the pipeline; at each entry count the known facts that are false,
    and the atoms reported known (so elidable) that are false of the path
    being checked. Returns those counts, which steps completed, the tracker."""
    t = cls(elide=elide)
    stale_at, wrong_at, completed = [], [], []
    for i, (role, spelling) in enumerate(pipeline):
        stale_at.append(len(stale(t)))
        pre, post, body = ROLES[role]
        e = P(str(r / spelling)).requires(*pre)
        if post:
            e = e.ensures(*post)
        n = len(t.entries)
        try:
            with t.run(f"s{i}", Step(x=e), {}) as p:
                wrong_at.append(
                    sum(
                        holds(Fact(a, x.path)) is False
                        for x in t.entries[n:]
                        for a in x.known
                    )
                )
                body(p["x"])
        except Exception:  # noqa: BLE001 - a failed step is an outcome here
            completed.append(False)
            continue
        completed.append(True)
    stale_at.append(len(stale(t)))
    return stale_at, wrong_at, completed, t


SETTINGS = settings(
    max_examples=400, deadline=None, suppress_health_check=list(HealthCheck)
)


@SETTINGS
@given(trees, pipelines())
def test_keyed_by_what_checks_read_every_known_atom_holds(tree, pipeline):
    # With elision, so that a step whose known atoms are false still runs
    # and they are seen.
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        alias_tree(r, tree)
        stale_at, wrong_at, _, _ = run_alias(IdentityTracker, r, pipeline, elide=True)
        assert set(stale_at) == {0}
        assert set(wrong_at) <= {0}


@SETTINGS
@given(trees, pipelines())
def test_with_aliases_eliding_known_checks_changes_nothing(tree, pipeline):
    results = []
    for elide in (False, True):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            alias_tree(r, tree)
            _, _, completed, _ = run_alias(IdentityTracker, r, pipeline, elide=elide)
            results.append(
                (completed, sorted(str(p.relative_to(r)) for p in r.rglob("*")))
            )
    assert results[0] == results[1]


@SETTINGS
@given(trees, pipelines())
def test_on_an_alias_free_run_string_keyed_knowledge_is_exact(tree, pipeline):
    # The analysis of families keys facts by strings; this is the condition,
    # checkable at run time, under which that is sound.
    out = []
    for cls in (Tracker, IdentityTracker):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            alias_tree(r, tree)
            out.append((run_alias(cls, r, pipeline), str(r)))
    ((stale_at, wrong_at, _, _), _), ((_, _, _, ti), root) = out
    if ti.alias_free(root):
        assert set(stale_at) == {0} and set(wrong_at) <= {0}


# -- what each check reads -----------------------------------------------------


def test_absent_does_not_follow_a_final_symlink():
    # lx dangles once d/x is deleted: d/x is absent, lx is not (lstat sees the
    # link). Keyed by the followed entry, creating lx would skip its Absent
    # check and write d/x through the link.
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "d").mkdir()
        (r / "d" / "x").write_text("x")
        (r / "lx").symlink_to("d/x")
        t = IdentityTracker(elide=True)
        drive(t, [("drop", deletes(r / "d" / "x"), Path.unlink)])
        assert t.knowledge.knows("absent", resolve(str(r / "d" / "x")))
        assert not t.knowledge.knows("absent", resolve(str(r / "lx")))
        make = Step(
            x=P(str(r / "lx")).requires(Absent, Creatable).ensures(File, Exists)
        )
        with pytest.raises(ConditionError):
            drive(t, [("make", make, lambda p: p.write_text("through"))])
        assert not (r / "d" / "x").exists()


def test_below_a_file_is_not_the_file():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "f").write_text("f")
        t = IdentityTracker()
        drive(t, [("read", reads(r / "f"), None)])
        assert t.knowledge.knows("exists", resolve(str(r / "f")))
        assert not t.knowledge.knows("exists", resolve(str(r / "f" / "x")))


def _creatable_below_a_dangling_link(path: Path) -> bool:
    """Whether `Creatable` passes for ``path``, below a dangling link, by
    judging the link's parent (master), or refuses it, as #111 makes it do."""
    try:
        P(str(path)).requires(Creatable).check()
    except ConditionError as e:
        if "broken symlink" not in str(e):
            raise
        return False
    return True


def test_a_missing_paths_creation_is_judged_where_the_check_looks():
    # With a dangling symlink on the way, the nearest existing ancestor that
    # Creatable consults is not the parent of the first missing entry: lnk/x
    # and far/missing/y end at one missing entry, but are checked in r and in
    # far. With far read-only (a bind mount: root ignores permission bits),
    # the first check passes and the second fails.
    #
    # #111 makes Creatable refuse a path below a dangling link (aliasing
    # addendum A.2). The check then always looks in the physical parent of
    # the first missing entry, and the mutant this test kills, "creation
    # keyed by the first missing entry", is equivalent. So the test asks
    # which Creatable it has, and holds whichever of #110 and #111 is merged
    # first.
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "src").mkdir()
        (r / "lnk").symlink_to(r / "far" / "missing")
        if not _bind(r / "src", r / "far", "ro"):
            pytest.skip("cannot bind-mount here")
        try:
            a, b = (
                resolve(str(r / "lnk" / "x")),
                resolve(str(r / "far" / "missing" / "y")),
            )
            assert a.final == b.final  # resolution ends at one missing entry
            # Creation facts outlive a step only as postconditions: a port that
            # requires one declares a mutation, which forgets it at exit.
            t = IdentityTracker(elide=True)
            ready = [
                ("ready", Step(x=P(str(r / "lnk" / "x")).ensures(Creatable)), None)
            ]
            if _creatable_below_a_dangling_link(r / "lnk" / "x"):
                drive(t, ready)
                assert t.knowledge.knows("create", a)
            else:  # with #111: refused at the dangling name, and nothing learned
                with pytest.raises(ConditionError, match="broken symlink"):
                    drive(t, ready)
                assert not t.knowledge.knows("create", a)
            with pytest.raises(ConditionError):
                drive(t, [("make", Step(x=P(str(b.path)).requires(Creatable)), None)])
        finally:
            subprocess.run(["umount", "-l", str(r / "far")])


def test_a_symlinked_stage_directory_is_flagged():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "store").mkdir()
        (r / "raw").symlink_to(r / "store")
        t = IdentityTracker()
        drive(
            t,
            [
                (
                    "make",
                    Step(
                        x=P(str(r / "raw" / "a"))
                        .requires(Absent, Creatable)
                        .ensures(Exists)
                    ),
                    lambda p: p.write_text("a"),
                )
            ],
        )
        assert not t.alias_free(str(r))
        t2 = IdentityTracker()
        drive(
            t2,
            [
                (
                    "make",
                    Step(
                        x=P(str(r / "store" / "b"))
                        .requires(Absent, Creatable)
                        .ensures(Exists)
                    ),
                    lambda p: p.write_text("b"),
                )
            ],
        )
        assert t2.alias_free(str(r))


def test_alias_freedom_is_judged_below_the_root_however_it_is_spelled():
    # A root reached through a symlink (macOS's /tmp is one) is shared by
    # every path below it; a symlink below it is still an alias.
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "real" / "d").mkdir(parents=True)
        (r / "via").symlink_to(r / "real")
        (r / "real" / "link").symlink_to("d")
        root = str(r / "via")
        assert resolve(root + "/d/x").alias_free(root)
        assert not resolve(root + "/link/x").alias_free(root)


# -- resolution the kernel holds to the string ----------------------------------


@SETTINGS
@given(trees, st.sampled_from(SPELLINGS))
def test_the_kernel_agrees_with_the_model_on_what_is_alias_free(tree, spelling):
    # openat2 under Beneath's flags succeeds exactly where the trace says the
    # path exists and was read as written: the model's alias_free, checked
    # against the kernel's resolver.
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        alias_tree(r, tree)
        t = resolve(str(r / spelling))
        with Beneath(str(r)) as b:
            try:
                b.stat(spelling)
                opened = True
            except OSError, ValueError:
                opened = False
        assert opened == (t.obj is not None and t.alias_free(str(r)))


def test_beneath_refuses_a_symlink_swapped_in_after_the_check(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "secret").write_text("secret")
    x = tmp_path / "root" / "x"
    x.write_text("mine")
    check_conditions(str(x), (File, Exists, Readable), {}, None)  # time of check
    x.unlink()
    x.symlink_to("../secret")  # ... someone else ...
    assert x.read_text() == "secret"  # ... and the use reads elsewhere
    with Beneath(str(tmp_path / "root")) as b, pytest.raises(OSError) as e:
        b.open("x")
    assert e.value.errno == errno.ELOOP


def test_beneath_creation_does_not_write_through_a_dangling_symlink(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "report").symlink_to("../pwned")
    with Beneath(str(tmp_path / "root")) as b, pytest.raises(OSError):
        b.create("report")
    assert not (tmp_path / "pwned").exists()
    open(tmp_path / "root" / "report", "w").close()  # a plain open follows it
    assert (tmp_path / "pwned").exists()


def test_beneath_refuses_a_mount_crossing_and_dotdot(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "x").write_text("x")
    with Beneath(str(tmp_path)) as b:
        with pytest.raises(ValueError):
            b.open("d/../d/x")
        with pytest.raises(ValueError):
            b.open(str(tmp_path / "d" / "x"))
        if not _bind(tmp_path / "d", tmp_path / "m"):
            pytest.skip("cannot bind-mount here")
        try:
            with pytest.raises(OSError) as e:
                b.open("m/x")
            assert e.value.errno == errno.EXDEV
            assert not resolve(str(tmp_path / "m" / "x")).alias_free(str(tmp_path))
            os.close(b.open("d/x"))
        finally:
            subprocess.run(["umount", "-l", str(tmp_path / "m")])


def test_a_held_file_is_checked_and_used_as_one(tmp_path):
    (tmp_path / "x").write_text("mine")
    with Beneath(str(tmp_path)) as b, b.hold("x") as h:
        assert h.is_file
        (tmp_path / "x").unlink()
        (tmp_path / "x").write_text("theirs")
        assert h.read() == b"mine"
