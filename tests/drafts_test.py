"""Who can reach an unpublished output (docs/journal/2026-10-22-drafts.md).

A `Draft` has no name, but it is reachable as ``/proc/<pid>/fd/N`` by every
process that passes ``ptrace``'s read check on the writer: its own uid while
it is dumpable, and root. A `VersionDraft` has a name, a hidden directory,
which no such check guards. Each test has the writer and every other
process do what they can, and asserts what was done, not only what was
refused.

The writer and the other processes are forked, so that their uids and
dumpability can be set; as root, they act as unprivileged users. They are
forked from a fresh interpreter that imports only what they use, never from
pytest's, which other tests leave with native threads (polars starts a pool
on import), where a fork may deadlock. Tests that need another uid, or root
as the other process, skip without root."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from wend._experimental import publish as pub
from wend._experimental.confined import Confined
from wend._experimental.publish import Inconsistent, Store


ROOT = os.geteuid() == 0
WRITER, OTHER = (65534, 65533) if ROOT else (os.geteuid(), None)
needs_root = pytest.mark.skipif(not ROOT, reason="needs root to act as other users")

ACTORS = r"""
import ctypes, errno, json, os, re, sys
from wend._experimental.confined import Confined
from wend._experimental.publish import Draft

libc = ctypes.CDLL(None, use_errno=True)
PR_SET_DUMPABLE, SYS_pidfd_open, SYS_pidfd_getfd = 4, 434, 438
spec = json.loads(sys.argv[1])
threads = re.search(r"Threads:\s+(\d+)", open("/proc/self/status").read())[1]
assert threads == "1", f"{threads} threads: a fork here is not safe"


def become(uid, dumpable):
    if uid is not None and uid != os.geteuid():
        os.setgroups([])
        os.setresgid(uid, uid, uid)
        os.setresuid(uid, uid, uid)
    # a change of uid makes a process non-dumpable (fs.suid_dumpable = 0);
    # a process started as that user is dumpable: set it as the test needs
    libc.prctl(PR_SET_DUMPABLE, int(dumpable), 0, 0, 0)


def refusal(e):
    return errno.errorcode.get(e.errno or 0, str(e.errno))


def child(fn):
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(r)
            os.write(w, json.dumps(fn()).encode())
        finally:
            os._exit(0)
    os.close(w)
    with os.fdopen(r) as f:
        out = f.read()
    os.waitpid(pid, 0)
    return json.loads(out)


def attempt(pid, fd, uid, tag, out_dir):
    become(uid, True)
    path = f"/proc/{pid}/fd/{fd}"

    def read():
        with open(path, "rb") as f:
            assert f.read() == b"partial"

    def write():
        g = os.open(path, os.O_WRONLY)
        os.pwrite(g, b"P", 0)  # into the draft, before it is published
        os.close(g)

    def name():
        d = os.open(out_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:  # linkat(..., AT_SYMLINK_FOLLOW): os.link with no dir_fd calls
            # link(2), which links the magic link itself and fails, EXDEV
            os.link(path, f"taken-{tag}", dst_dir_fd=d, follow_symlinks=True)
        finally:
            os.close(d)

    def take():
        pfd = libc.syscall(SYS_pidfd_open, pid, 0)
        if pfd < 0:
            raise OSError(ctypes.get_errno(), "pidfd_open")
        g = libc.syscall(SYS_pidfd_getfd, pfd, fd, 0)
        os.close(pfd)
        if g < 0:
            raise OSError(ctypes.get_errno(), "pidfd_getfd")
        os.close(g)

    out = {}
    for what, act in (("read", read), ("write", write), ("name", name), ("take", take)):
        try:
            act()
            out[what] = "done"
        except OSError as e:
            out[what] = refusal(e)
    return out


def look(uid, store, name):
    become(uid, True)
    out = {"listed": sorted(os.listdir(store))}
    try:
        with open(os.path.join(store, name, "a.csv")) as f:
            out["read"] = f.read()
    except OSError as e:
        out["read"] = refusal(e)
    return out


if spec["do"] == "draft":
    base = spec["base"]
    ready_r, ready_w = os.pipe()
    go_r, go_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            become(spec["writer"], spec["dumpable"])
            d = Draft(Confined(base), "out")
            d.write(b"partial")
            os.write(ready_w, f"{d.fd}\n".encode())
            os.read(go_r, 1)
            d.abandon()
        finally:
            os._exit(0)
    fd = int(os.read(ready_r, 64))
    out = [
        child(lambda: attempt(pid, fd, uid, tag, os.path.join(base, "out")))
        for uid, tag in spec["others"]
    ]
    os.write(go_w, b"x")
    os.waitpid(pid, 0)
elif spec["do"] == "commit-immutable":
    from wend._experimental.publish import Store

    def commit():
        become(spec["uid"], True)
        v = Store(Confined(spec["base"]), "reports").begin(None)
        v.add("a.csv", b"a")
        try:
            v.commit(immutable=True)
            raised = None
        except Exception as e:
            raised = [type(e).__name__, refusal(e) if isinstance(e, OSError) else ""]
        return {"raised": raised, "left": sorted(os.listdir(spec["store"]))}

    out = child(commit)
elif spec["do"] == "rename":

    def rename():
        become(spec["uid"], True)
        try:
            os.rename(spec["src"], spec["dst"])
            return "done"
        except OSError as e:
            return refusal(e)

    out = child(rename)
else:
    out = child(lambda: look(spec["uid"], spec["store"], spec["name"]))
print(json.dumps(out))
"""


def actors(**spec: object) -> object:
    """Run ``ACTORS`` in a fresh interpreter, and return what it reports."""
    r = subprocess.run(
        [sys.executable, "-c", ACTORS, json.dumps(spec)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture
def shared(tmp_path):
    """A directory every test user can reach and write in."""
    d = Path(tempfile.mkdtemp(dir="/tmp")) if ROOT else tmp_path
    os.chmod(d, 0o1777)
    (d / "out").mkdir()
    os.chmod(d / "out", 0o1777)
    try:
        yield d
    finally:
        if ROOT:
            shutil.rmtree(d)


def draft(base: Path, dumpable: bool, *others: tuple[int | None, str]) -> list:
    """A writer, as ``WRITER``, holds a draft in ``base/out``; each other
    process, as its uid (``None``: root), tries everything on it."""
    out = actors(
        do="draft", base=str(base), writer=WRITER, dumpable=dumpable, others=others
    )
    assert isinstance(out, list)
    return out


ALL = {"read": "done", "write": "done", "name": "done", "take": "done"}
NONE = {"read": "EACCES", "write": "EACCES", "name": "EACCES", "take": "EPERM"}


def test_a_draft_is_open_to_processes_of_its_own_uid(shared):
    assert draft(shared, True, (WRITER, "same")) == [ALL]
    # named, partial, and changed by the other process before publication;
    # it outlives the writer, which abandoned its draft
    assert (shared / "out" / "taken-same").read_bytes() == b"Partial"


def test_a_non_dumpable_writer_s_draft_is_closed_to_its_own_uid(shared):
    assert draft(shared, False, (WRITER, "same")) == [NONE]
    assert os.listdir(shared / "out") == []


@needs_root
def test_a_draft_is_closed_to_other_users(shared):
    # with the control: the same draft, open to its own uid
    assert draft(shared, True, (OTHER, "other"), (WRITER, "same")) == [NONE, ALL]


@needs_root
def test_root_reaches_every_draft(shared):
    assert draft(shared, False, (None, "root")) == [ALL]
    assert (shared / "out" / "taken-root").read_bytes() == b"Partial"


# -- a version's hidden directory -----------------------------------------------


@pytest.fixture
def store(tmp_path):
    (tmp_path / "reports").mkdir()
    io = Confined(str(tmp_path))
    yield Store(io, "reports"), tmp_path / "reports"
    io.close()


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_a_hidden_version_is_private_while_it_is_filled(store):
    s, d = store
    v = s.begin(None)
    v.add("a.csv", b"a")
    assert mode(d / v.hidden) == 0o700
    v.commit()
    assert mode(d / "v000001") == 0o755  # readable once claimed


@needs_root
def test_other_users_see_a_hidden_version_s_name_but_not_its_contents(tmp_path):
    base = Path(tempfile.mkdtemp(dir="/tmp"))
    try:
        os.chmod(base, 0o755)
        (base / "reports").mkdir(mode=0o755)
        io = Confined(str(base))
        v = Store(io, "reports").begin(None)
        v.add("a.csv", b"secret")

        def look(name: str) -> object:
            return actors(do="look", uid=OTHER, store=str(base / "reports"), name=name)

        hidden = v.hidden
        assert look(hidden) == {"listed": [hidden], "read": "EACCES"}
        v.commit()
        assert look("v000001") == {"listed": ["v000001"], "read": "secret"}
        io.close()
    finally:
        shutil.rmtree(base)


def test_a_draft_claimed_by_another_process_is_detected_and_left(store):
    s, d = store
    v = s.begin(None)
    v.add("a.csv", b"a")
    os.rename(d / v.hidden, d / "v000001")  # another process claims it, early
    with pytest.raises(FileNotFoundError):
        s.pin(1)  # meanwhile readers find no manifest: they fail, not mix
    v.add("b.csv", b"b")  # still into the held directory, now a version
    with pytest.raises(Inconsistent, match="claimed by another process"):
        v.commit()
    # not this writer's to remove: a version, complete as it happens
    assert sorted(os.listdir(d / "v000001")) == ["MANIFEST", "a.csv", "b.csv"]
    assert s.versions() == [1]


def test_a_replaced_hidden_directory_is_neither_filled_nor_claimed(store):
    s, d = store
    v = s.begin(None)
    v.add("a.csv", b"a")
    os.rename(d / v.hidden, d / "aside")  # another process moves it away
    (d / v.hidden).mkdir()  # and puts its own in its place
    (d / v.hidden / "a.csv").write_bytes(b"theirs")
    v.add("b.csv", b"b")  # into the draft's own directory, not theirs
    assert sorted(os.listdir(d / v.hidden)) == ["a.csv"]
    with pytest.raises(Inconsistent, match="moved or replaced"):
        v.commit()
    assert s.versions() == []  # theirs was not claimed
    assert (d / v.hidden / "a.csv").read_bytes() == b"theirs"  # nor touched
    assert os.listdir(d / "aside") == []  # this draft's members, removed


def test_a_directory_put_in_place_as_the_claim_is_made_is_detected(store, monkeypatch):
    s, d = store
    v = s.begin(None)
    v.add("a.csv", b"a")
    real = pub.renameat2

    def renameat2(*args):  # between the check and the claim
        os.rename(d / v.hidden, d / "aside")
        (d / v.hidden).mkdir()
        (d / v.hidden / "a.csv").write_bytes(b"theirs")
        return real(*args)

    monkeypatch.setattr(pub, "renameat2", renameat2)
    with pytest.raises(Inconsistent, match="not this version"):
        v.commit()
    # the claim is made, of theirs: detected, not prevented
    assert (d / "v000001" / "a.csv").read_bytes() == b"theirs"
    assert os.listdir(d / "aside") == []


def test_a_draft_claimed_as_its_claim_is_made_is_left(store, monkeypatch):
    s, d = store
    v = s.begin(None)
    v.add("a.csv", b"a")
    real = pub.renameat2

    def renameat2(*args):
        os.rename(d / v.hidden, d / "v000001")  # another process, first
        return real(*args)

    monkeypatch.setattr(pub, "renameat2", renameat2)
    with pytest.raises(Inconsistent, match="claimed by another process"):
        v.commit()
    assert sorted(os.listdir(d / "v000001")) == ["MANIFEST", "a.csv"]


@needs_root
@pytest.mark.parametrize("sticky", [False, True])
def test_another_user_who_may_write_the_store_can_claim_a_draft(sticky):
    # Mode 0700 keeps a hidden version's contents from other users; renaming
    # it within its parent needs only write permission on the parent, unless
    # the parent is sticky. The claim is exclusive against other users only
    # as far as the store's own directory keeps them out.
    base = Path(tempfile.mkdtemp(dir="/tmp"))
    try:
        os.chmod(base, 0o755)
        (base / "reports").mkdir()
        os.chmod(base / "reports", 0o1777 if sticky else 0o777)
        io = Confined(str(base))
        v = Store(io, "reports").begin(None)
        v.add("a.csv", b"a")
        hidden = str(base / "reports" / v.hidden)
        took = actors(
            do="rename", uid=OTHER, src=hidden, dst=str(base / "reports" / "v000001")
        )
        if sticky:
            assert took == "EPERM"
            assert v.commit().n == 1  # the writer's own claim
        else:
            assert took == "done"
            with pytest.raises(Inconsistent, match="claimed by another process"):
                v.commit()
        assert sorted(os.listdir(base / "reports" / "v000001")) == ["MANIFEST", "a.csv"]
        io.close()
    finally:
        shutil.rmtree(base)


@needs_root
def test_an_ordinary_user_cannot_make_a_version_immutable(shared):
    # FS_IMMUTABLE_FL needs CAP_LINUX_IMMUTABLE. Without it the commit is
    # refused before the claim, and the hidden draft is removed: what an
    # ordinary user has instead is the manifest, which detects a change.
    (shared / "reports").mkdir()
    os.chown(shared / "reports", WRITER, WRITER)
    out = actors(
        do="commit-immutable",
        uid=WRITER,
        base=str(shared),
        store=str(shared / "reports"),
    )
    assert out == {"raised": ["PermissionError", "EPERM"], "left": []}
