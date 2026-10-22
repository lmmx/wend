"""Read leases as an exclusion of writers (`fresh.Leases`;
docs/journal/2026-10-22-leases.md): when one is refused, what breaks it,
what changes a file without breaking it, what happens when a process dies,
and which signals reach which process.

The leases are taken by a helper process that exits at once, so that no
signal announcing a break is ever this process's to handle. Tests whose
subject is signals run in a separate host process, whose dispositions they
set: a SIGIO delivered there at its default action ends the host, not
pytest."""

import errno
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from wend import Absent, Creatable, Exists, File, P, Param, Readable
from wend._experimental import fresh
from wend._experimental.events import Holds, Makes, Run, Spec
from wend._experimental.fresh import Busy, Leases, Unleasable
from wend._experimental.publish import Inconsistent


pytestmark = pytest.mark.linux  # read leases are Linux's F_SETLEASE

F_SETSIG, F_SETLEASE, F_GETLEASE = 10, 1024, 1025
PAGE, PAGES = 4096, 64


def lease_of(fd: int) -> str:
    return {fcntl.F_RDLCK: "read", fcntl.F_WRLCK: "write", fcntl.F_UNLCK: "none"}[
        fcntl.fcntl(fd, F_GETLEASE)
    ]


def leases_listed(path: Path) -> list[str]:
    """The kernel's own list of leases on ``path``'s object (/proc/locks),
    read without opening it (an open for writing would break them)."""
    st = os.stat(path)
    ident = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino} "
    with open("/proc/locks") as f:
        return [ln for ln in f if "LEASE" in ln and ident in ln]


def open_for_writing_now(path: Path) -> bool:
    """Whether a writer could open ``path`` without waiting. Asking, if a
    lease is held, breaks it."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
    except BlockingIOError:
        return False
    return True


def host(script: str, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    """Run ``script`` in a separate process with this interpreter."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture
def files(tmp_path):
    for n in ("a", "b"):
        (tmp_path / n).write_bytes(n.encode() * PAGE)
    fds = {n: os.open(tmp_path / n, os.O_RDONLY) for n in ("a", "b")}
    yield tmp_path, fds
    for fd in fds.values():
        os.close(fd)


# -- when a lease is refused ---------------------------------------------------


def test_a_writer_refuses_the_lease_until_it_is_gone(files):
    d, fds = files
    w = os.open(d / "a", os.O_WRONLY)
    with pytest.raises(Busy):
        Leases([fds["a"]])
    assert lease_of(fds["a"]) == "none"
    os.close(w)
    with Leases([fds["a"]]) as held:
        assert held.unbroken() and lease_of(fds["a"]) == "read"
    assert lease_of(fds["a"]) == "none"  # released on leaving


def test_a_writable_mapping_refuses_it_after_its_descriptor_is_closed(files):
    import mmap

    d, fds = files
    w = os.open(d / "a", os.O_RDWR)
    m = mmap.mmap(w, PAGE, mmap.MAP_SHARED, mmap.PROT_WRITE)
    os.close(w)  # the mapping keeps the description, and its write access
    with pytest.raises(Busy):
        Leases([fds["a"]])
    m.close()
    with Leases([fds["a"]]) as held:
        assert held.unbroken()


def test_this_process_holding_the_file_for_writing_refuses_it(files):
    # Not only another process: any description with write access, ours too.
    d, fds = files
    mine = os.open(d / "a", os.O_RDWR)
    try:
        with pytest.raises(Busy):
            Leases([fds["a"]])
    finally:
        os.close(mine)


def test_a_descriptor_open_for_writing_cannot_hold_one(tmp_path):
    (tmp_path / "a").write_bytes(b"a")
    fd = os.open(tmp_path / "a", os.O_RDWR)
    try:
        with pytest.raises(Busy):  # its own write access is a writer
            Leases([fd])
    finally:
        os.close(fd)


def test_a_filesystem_whose_files_change_without_writers_is_refused(tmp_path):
    # The kernel grants a lease on /proc/uptime, which changes with no writer
    # at all, its size always 0: the lease would vouch for a copy no writer
    # disturbed, which is not one version. Leases refuses what it has not
    # shown to change only through its files.
    fd = os.open("/proc/uptime", os.O_RDONLY)
    try:
        assert fresh.filesystem(fd) not in fresh.LEASABLE
        with pytest.raises(Unleasable) as e:
            Leases([fd])
        assert e.value.errno == errno.EINVAL
        assert lease_of(fd) == "none"
    finally:
        os.close(fd)
    (tmp_path / "a").write_bytes(b"a")
    fd = os.open(tmp_path / "a", os.O_RDONLY)
    try:
        assert fresh.filesystem(fd) in fresh.LEASABLE  # where the tests run
    finally:
        os.close(fd)


KERNEL_LEASES_PROC = """
    import fcntl, json, os, signal, time
    signal.signal(signal.SIGIO, signal.SIG_IGN)
    # the process's own status: its own, so leasable without privilege; it
    # counts the context switches a sleep makes
    fd = os.open("/proc/self/status", os.O_RDONLY)
    fcntl.fcntl(fd, 1024, fcntl.F_RDLCK)
    a = os.pread(fd, 4096, 0)
    time.sleep(0.05)
    b = os.pread(fd, 4096, 0)
    print(json.dumps({"leased": fcntl.fcntl(fd, 1025) == fcntl.F_RDLCK,
                      "size": os.fstat(fd).st_size, "changed": a != b}))
"""


def test_the_kernel_leases_a_proc_file_that_changes_under_the_lease():
    r = host(KERNEL_LEASES_PROC)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"leased": True, "size": 0, "changed": True}


def test_leases_are_all_or_none(files):
    d, fds = files
    w = os.open(d / "b", os.O_WRONLY)
    try:
        with pytest.raises(Busy):
            Leases([fds["a"], fds["b"]])
    finally:
        os.close(w)
    # a's lease, taken before b's was refused, was given up: nothing listed,
    # and a writer to a need not wait
    assert leases_listed(d / "a") == [] and lease_of(fds["a"]) == "none"
    assert open_for_writing_now(d / "a")


def test_two_readers_may_lease_one_file(tmp_path):
    (tmp_path / "a").write_bytes(b"a")
    one, two = (os.open(tmp_path / "a", os.O_RDONLY) for _ in range(2))
    try:
        with Leases([one]) as x, Leases([two]) as y:
            assert x.unbroken() and y.unbroken()
            assert len(leases_listed(tmp_path / "a")) == 2
    finally:
        os.close(one)
        os.close(two)


def test_a_lease_belongs_to_the_open_file_description(files):
    # Not to a descriptor number: a duplicate (dup, fork, SCM_RIGHTS) shares
    # it. Released through any of them, it is gone from all; never released,
    # it lasts until the last of them is closed, with an owner that no
    # longer exists, and the first writer then waits lease-break-time.
    d, fds = files
    dup = os.dup(fds["a"])
    try:
        Leases([fds["a"]]).release()
        assert leases_listed(d / "a") == [] and lease_of(dup) == "none"
        Leases([fds["a"]])  # not released
        os.close(fds["a"])
        fds["a"] = os.open(d / "a", os.O_RDONLY)  # for the fixture to close
        assert lease_of(dup) == "read" and len(leases_listed(d / "a")) == 1
    finally:
        os.close(dup)
    assert leases_listed(d / "a") == []  # the last one closed


# -- what breaks a lease, and what does not -------------------------------------


def test_a_writer_that_arrives_is_held_off_and_breaks_the_lease(files):
    d, fds = files
    with Leases([fds["a"], fds["b"]]) as held:
        assert held.unbroken()
        assert not open_for_writing_now(d / "b")  # held off
        assert not held.unbroken()  # and it asked: the lease is breaking
        assert (d / "b").read_bytes() == b"b" * PAGE


def test_a_blocked_writer_goes_on_when_the_leases_are_released(files):
    d, fds = files
    held = Leases([fds["a"]])
    w = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; open(sys.argv[1], 'wb').write(b'new')",
            str(d / "a"),
        ]
    )
    try:
        time.sleep(0.5)
        assert w.poll() is None  # still waiting in open()
        assert (d / "a").read_bytes() == b"a" * PAGE
        assert not held.unbroken()
        t = time.monotonic()
        held.release()
        assert w.wait(timeout=10) == 0
        # promptly: not the kernel's lease-break-time (45 s by default)
        assert time.monotonic() - t < 5
        assert (d / "a").read_bytes() == b"new"
    finally:
        w.kill()
        w.wait()


def test_truncating_by_name_breaks_the_lease(files):
    d, fds = files
    held = Leases([fds["a"]])
    w = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os, sys; os.truncate(sys.argv[1], 0)",
            str(d / "a"),
        ]
    )
    try:
        time.sleep(0.5)
        assert w.poll() is None and (d / "a").stat().st_size == PAGE
        assert not held.unbroken()
        held.release()
        assert w.wait(timeout=10) == 0 and (d / "a").stat().st_size == 0
    finally:
        w.kill()
        w.wait()


def test_opening_read_only_with_O_TRUNC_empties_the_file_and_keeps_the_lease(files):
    # The kernel breaks leases on open by the access mode; O_RDONLY asks for
    # none, and the truncation that O_TRUNC then does (namei.c,
    # handle_truncate) does not break them. Write permission is enough.
    d, fds = files
    with Leases([fds["a"]]) as held:
        os.close(os.open(d / "a", os.O_RDONLY | os.O_TRUNC | os.O_NONBLOCK))
        assert os.fstat(fds["a"]).st_size == 0  # the leased file was emptied
        assert lease_of(fds["a"]) == "read"  # and the lease does not know
        assert len(leases_listed(d / "a")) == 1
        assert not held.unbroken()  # its size does: it can only fall, to zero


def test_the_name_may_change_and_the_object_does_not(files):
    d, fds = files
    with Leases([fds["a"], fds["b"]]) as held:
        (d / "c").write_bytes(b"c")
        os.rename(d / "c", d / "a")  # another object at the name
        os.unlink(d / "b")  # no name at all
        assert held.unbroken()  # names are not contents
        assert os.pread(fds["a"], PAGE, 0) == b"a" * PAGE
        assert os.pread(fds["b"], PAGE, 0) == b"b" * PAGE


def test_another_name_for_the_object_is_the_same_file(files):
    d, fds = files
    os.link(d / "a", d / "also-a")
    with Leases([fds["a"]]) as held:
        assert not open_for_writing_now(d / "also-a")
        assert not held.unbroken()


def test_metadata_changes_are_not_writes(files):
    d, fds = files
    with Leases([fds["a"]]) as held:
        os.utime(d / "a", (1, 1))
        os.chmod(d / "a", 0o600)
        assert held.unbroken()


def copy_file_range(src: int, dst: int) -> None:
    """One byte from ``src`` into ``dst``, through libc (this interpreter
    may be built without ``os.copy_file_range``)."""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.copy_file_range(src, None, dst, None, ctypes.c_size_t(1), 0) < 0:
        raise OSError(ctypes.get_errno(), "copy_file_range")


def test_every_other_way_to_change_the_bytes_needs_write_access(files):
    # The proposition's L3: besides truncation, contents change only through
    # a description with write access, which a lease excludes. These are the
    # system calls that change bytes in place; each refuses a read-only one.
    import mmap

    d, fds = files
    fd = fds["a"]
    src = os.open(d / "b", os.O_RDONLY)
    r, w = os.pipe()
    os.write(w, b"x")
    attempts = {
        "pwrite": lambda: os.pwrite(fd, b"x", 0),
        "ftruncate": lambda: os.ftruncate(fd, 0),
        "fallocate": lambda: os.posix_fallocate(fd, 0, 2 * PAGE),
        "copy_file_range": lambda: copy_file_range(src, fd),
        "splice": lambda: os.splice(r, fd, 1, offset_dst=0),
        "shared writable mapping": lambda: mmap.mmap(
            fd, PAGE, mmap.MAP_SHARED, mmap.PROT_WRITE
        ),
    }
    try:
        refused = {}
        for name, attempt in attempts.items():
            with pytest.raises(OSError) as e:
                attempt()
            refused[name] = errno.errorcode.get(e.value.errno or 0, "?")
    finally:
        for x in (src, r, w):
            os.close(x)
    assert refused == {
        "pwrite": "EBADF",
        "ftruncate": "EINVAL",
        "fallocate": "EBADF",
        "copy_file_range": "EBADF",
        "splice": "EBADF",
        "shared writable mapping": "EACCES",
    }
    assert (d / "a").read_bytes() == b"a" * PAGE


def test_a_leased_collect_is_not_fooled_by_two_truncations(tmp_path):
    # Without the size check, the leases end unbroken and the copies are a's
    # old contents and b emptied: a was emptied before b, so the two never
    # coexisted.
    from wend._experimental.confined import Confined
    from wend._experimental.fresh import collect

    for n in ("a", "b"):
        (tmp_path / n).write_bytes(n.encode() * PAGE)

    def between(phase, i):
        if (phase, i) == ("first", 0):  # a copied; b not yet
            for n in ("a", "b"):
                os.close(os.open(tmp_path / n, os.O_RDONLY | os.O_TRUNC))

    io = Confined(str(tmp_path))
    try:
        copies, coherent = collect(io, ["a", "b"], observer="lease", between=between)
    finally:
        io.close()
    assert (copies["a"].read(), copies["b"].read()) == (b"a" * PAGE, b"")
    assert coherent is False


# -- signals --------------------------------------------------------------------

HOST = """
    import json, os, signal, subprocess, sys, time
    from wend._experimental.fresh import Leases

    path, sigio = sys.argv[1], sys.argv[2]
    calls = []
    watched = [signal.SIGURG, signal.SIGWINCH, signal.SIGRTMIN, signal.SIGRTMAX,
               signal.SIGCHLD]
    if sigio == "handled":
        watched.append(signal.SIGIO)
    for s in watched:
        signal.signal(s, lambda n, f: calls.append(signal.Signals(n).name))
    before = {int(s): signal.getsignal(s) for s in signal.valid_signals()}

    fd = os.open(path, os.O_RDONLY)
    held = Leases([fd])
    report = {"taken": held.unbroken()}
    try:  # a writer that does not wait: refused, and the lease breaks
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
        report["held_off"] = False
    except BlockingIOError:
        report["held_off"] = True
    w = subprocess.Popen([sys.executable, "-c",
                          "import sys; open(sys.argv[1], 'ab').write(b'x')", path])
    time.sleep(0.3)  # a writer that waits
    report["broken"] = not held.unbroken()
    held.release()
    w.wait(10)
    time.sleep(0.3)  # for any signal still on its way
    report["calls"] = calls
    report["dispositions_unchanged"] = before == {
        int(s): signal.getsignal(s) for s in signal.valid_signals()
    }
    print(json.dumps(report), flush=True)
"""


@pytest.mark.parametrize("sigio", ["default", "handled"])
def test_no_signal_of_a_break_reaches_the_host(tmp_path, sigio):
    # "default": SIGIO left at its default action, which ends the process:
    # had one arrived, the host would not have reported. "handled": every
    # signal a break could be announced by has a handler; none runs.
    (tmp_path / "a").write_bytes(b"a")
    r = host(HOST, str(tmp_path / "a"), sigio)
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report["taken"] and report["held_off"] and report["broken"]
    assert set(report["calls"]) <= {"SIGCHLD"}  # the helper's and the writer's
    assert report["dispositions_unchanged"]


IN_PROCESS = """
    import fcntl, json, os, signal, sys
    path, mode = sys.argv[1], sys.argv[2]
    calls = []
    signal.signal(signal.SIGURG, lambda n, f: calls.append("SIGURG"))
    fd = os.open(path, os.O_RDONLY)
    if mode == "redirected":
        fcntl.fcntl(fd, 10, signal.SIGURG)  # F_SETSIG: announce by SIGURG
    fcntl.fcntl(fd, fcntl.F_SETOWN, 0)  # no owner, before the lease
    fcntl.fcntl(fd, 1024, fcntl.F_RDLCK)  # F_SETLEASE
    owner = fcntl.fcntl(fd, fcntl.F_GETOWN)
    try:  # a writer, before the owner can be cleared again
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
    except BlockingIOError:
        pass
    fcntl.fcntl(fd, fcntl.F_SETOWN, 0)
    print(json.dumps({"owner_is_this_process": owner == os.getpid(),
                      "calls": calls}), flush=True)
"""


def test_a_lease_taken_in_process_makes_its_breaks_this_process_s_signals(tmp_path):
    # Why the helper: F_SETLEASE makes the caller the owner (fs/locks.c,
    # lease_setup), whatever F_SETOWN said before, so between taking a lease
    # and clearing its owner a break signals this process. Redirected to
    # SIGURG, the host's own SIGURG handler runs; left as SIGIO, the host
    # ends. No order of calls closes the window.
    (tmp_path / "a").write_bytes(b"a")
    r = host(IN_PROCESS, str(tmp_path / "a"), "redirected")
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report == {"owner_is_this_process": True, "calls": ["SIGURG"]}
    r = host(IN_PROCESS, str(tmp_path / "a"), "default")
    assert r.returncode == -signal.SIGIO and r.stdout == ""


WORST_MOMENT = """
    import fcntl, json, os, signal, sys
    from wend._experimental.fresh import Leases

    path = sys.argv[1]
    calls, took = [], []
    for s in (signal.SIGIO, signal.SIGURG, signal.SIGWINCH, signal.SIGRTMIN):
        signal.signal(s, lambda n, f: calls.append(signal.Signals(n).name))
    real = fcntl.fcntl

    def fcntl_(fd, cmd, arg=0):
        out = real(fd, cmd, arg)
        if cmd == 1024 and arg == fcntl.F_RDLCK:  # a lease taken here
            took.append(fd)
            try:  # and a writer arrives at once, before anything else runs
                os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
            except BlockingIOError:
                pass
        return out

    fcntl.fcntl = fcntl_
    fd = os.open(path, os.O_RDONLY)
    with Leases([fd]) as held:
        try:  # a writer, after
            os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
        except BlockingIOError:
            pass
        broken = not held.unbroken()
    print(json.dumps({"took_here": took, "calls": calls, "broken": broken}))
"""


def test_no_moment_of_taking_the_leases_lets_a_break_signal_the_host(tmp_path):
    # A lease taken in this process signals it if a writer arrives between
    # F_SETLEASE and whatever follows; the window is short, so the test
    # puts a writer in it, wherever this process takes a lease. This
    # process takes none: the window is in the helper.
    (tmp_path / "a").write_bytes(b"a")
    r = host(WORST_MOMENT, str(tmp_path / "a"))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"took_here": [], "calls": [], "broken": True}


REAPING = """
    import os, signal, sys
    from wend._experimental.fresh import Leases
    if sys.argv[2] == "ignore":
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # children reaped unseen
    else:
        def reap(n, f):
            try:
                while os.waitpid(-1, os.WNOHANG)[0]:
                    pass
            except ChildProcessError:
                pass
        signal.signal(signal.SIGCHLD, reap)  # every child, ours or not
    fd = os.open(sys.argv[1], os.O_RDONLY)
    for _ in range(5):
        with Leases([fd]) as held:
            assert held.unbroken()
    print("ok", flush=True)
"""


@pytest.mark.parametrize("sigchld", ["ignore", "reap"])
def test_a_host_that_reaps_every_child_still_gets_its_leases(tmp_path, sigchld):
    # The helper's report is read from its output, not its exit status,
    # which such a host may have taken.
    (tmp_path / "a").write_bytes(b"a")
    r = host(REAPING, str(tmp_path / "a"), sigchld)
    assert (r.returncode, r.stdout) == (0, "ok\n"), r.stderr


# -- abnormal exits -------------------------------------------------------------


def test_a_helper_killed_part_way_leaves_no_lease(files, monkeypatch):
    d, fds = files
    # takes the first lease, then dies before reporting
    monkeypatch.setattr(
        fresh,
        "_TAKE",
        "import fcntl, os, signal, sys\n"
        "fcntl.fcntl(int(sys.argv[1]), 1024, fcntl.F_RDLCK)\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n",
    )
    with pytest.raises(Unleasable) as e:
        Leases([fds["a"], fds["b"]])
    assert e.value.errno == errno.ECHILD
    assert leases_listed(d / "a") == [] and leases_listed(d / "b") == []
    assert open_for_writing_now(d / "a") and open_for_writing_now(d / "b")


def test_a_helper_that_cannot_start_leaves_no_lease(files, monkeypatch):
    d, fds = files
    monkeypatch.setattr(sys, "executable", str(d / "no-such-interpreter"))
    with pytest.raises(Unleasable):
        Leases([fds["a"]])
    assert leases_listed(d / "a") == []


DIES = """
    import os, sys, time
    from wend._experimental.fresh import Leases
    fd = os.open(sys.argv[1], os.O_RDONLY)
    held = Leases([fd])
    print("held", flush=True)
    sys.stdin.readline()  # until it is seen held
    if sys.argv[2] == "exit":
        os._exit(0)  # without releasing, without closing
    time.sleep(60)
"""


@pytest.mark.parametrize("how", ["exit", "kill"])
def test_the_leases_end_with_the_process_that_holds_them(tmp_path, how):
    (tmp_path / "a").write_bytes(b"a")
    h = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(DIES), str(tmp_path / "a"), how],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert h.stdin is not None and h.stdout is not None
    try:
        assert h.stdout.readline() == "held\n"
        assert len(leases_listed(tmp_path / "a")) == 1  # held, by the host
        if how == "kill":
            h.kill()
        else:
            h.stdin.write("go\n")
            h.stdin.flush()
        h.wait(timeout=10)
        assert leases_listed(tmp_path / "a") == []
        t = time.monotonic()
        with open(tmp_path / "a", "wb") as f:  # a writer that would wait
            f.write(b"new")
        assert time.monotonic() - t < 1
    finally:
        h.kill()
        h.wait()


# -- ownership ------------------------------------------------------------------


def as_nobody(monkeypatch):
    """Run the helper as an unprivileged user, with the system interpreter
    (this one may be where that user cannot reach)."""
    real = subprocess.run

    def run(argv, **kw):
        return real(
            [
                "setpriv",
                "--reuid=65534",
                "--regid=65534",
                "--clear-groups",
                "/usr/bin/python3",
                *argv[1:],
            ],
            **kw,
        )

    monkeypatch.setattr(fresh.subprocess, "run", run)


def needs_root(test):
    return pytest.mark.privileged(
        pytest.mark.skipif(
            os.geteuid() != 0
            or not shutil.which("setpriv")
            or not Path("/usr/bin/python3").exists(),
            reason="needs root, setpriv and /usr/bin/python3 to act as another user",
        )(test)
    )


@needs_root
def test_only_the_owner_or_CAP_LEASE_may_lease(files, monkeypatch):
    d, fds = files
    as_nobody(monkeypatch)
    with pytest.raises(Unleasable) as e:  # root's file: not nobody's to lease
        Leases([fds["a"]])
    assert e.value.errno == errno.EACCES
    os.chown(d / "b", 65534, 65534)
    with Leases([fds["b"]]) as held:  # its own: no privilege needed
        assert held.unbroken()


# -- what a leased copy is ------------------------------------------------------

WRITER = """
    import os, random, sys, time
    path, seconds, pause = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    end, v, held_off, versions = time.monotonic() + seconds, 0, 0, 0
    random.seed(0)
    while time.monotonic() < end:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except BlockingIOError:
            held_off += 1
            time.sleep(0.001)
            continue
        page = bytes([v % 251 + 1]) * 4096
        for i in range(64):
            os.pwrite(fd, page, i * 4096)
        os.close(fd)
        v, versions = v + 1, versions + 1
        time.sleep(random.uniform(0, pause))
    print(held_off, versions, flush=True)
"""


def copies_against_a_writer(path: Path, seconds: float, pause: float, lease: bool):
    """Copy ``path`` page by page while another process rewrites it, one
    version at a time: each copy, whether it mixes versions, and whether
    the leases were unbroken after it."""
    w = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(WRITER),
            str(path),
            str(seconds),
            str(pause),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    copies = []
    while w.poll() is None:
        fd = os.open(path, os.O_RDONLY)
        try:
            held = None
            if lease:
                try:
                    held = Leases([fd])
                except Busy:
                    continue
            pages = [os.pread(fd, PAGE, i * PAGE) for i in range(PAGES)]
            unbroken = held.unbroken() if held else None
            if held:
                held.release()
        finally:
            os.close(fd)
        copies.append((len({p[:1] for p in pages}) > 1, unbroken))
    out, _ = w.communicate()
    held_off, versions = map(int, out.split())
    return copies, held_off, versions


def test_a_leased_copy_is_one_version_and_an_unleased_one_need_not_be(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"\0" * PAGE * PAGES)
    # control: no lease, and copies mix the writer's versions
    copies, _, versions = copies_against_a_writer(path, 1.0, 0.002, lease=False)
    assert versions > 0 and sum(torn for torn, _ in copies) > 0
    # leased: the writer is held off while a lease is held, so no copy mixes
    # versions, whether or not its lease was broken by the end
    copies, held_off, versions = copies_against_a_writer(path, 3.0, 0.01, lease=True)
    assert held_off > 0 and versions > 0  # both sides were exercised
    assert sum(1 for _, unbroken in copies if unbroken) >= 5
    assert not any(torn for torn, _ in copies)


# -- a run that leases its inputs -----------------------------------------------

root = Param("root")
# bound before use: ty infers an inline declaration from the parameter's
# type first, and loses its kind (docs/journal/2026-10-22-evidence.md §3)
source = (P(root) / "in.csv").requires(File, Exists, Readable)
target = (P(root) / "out.csv").requires(Absent, Creatable).ensures(File, Exists)


class Copy(Spec):
    src = Holds(source)
    dst = Makes(target)


def copy_while_emptied(base: Path, lease: bool) -> None:
    r = Run(str(base), lease=lease)
    with r.enter(Copy, {"root": str(base)}) as s:
        data = s.src.read()  # all of it, as observed at entry
        os.close(os.open(base / "in.csv", os.O_RDONLY | os.O_TRUNC))  # another
        s.dst.write(data)


def test_a_run_sees_its_input_emptied_only_through_the_lease(tmp_path):
    (tmp_path / "in.csv").write_bytes(b"a,b\n1,2\n")
    # Without the lease nothing sees it: the step read everything before
    # the input was emptied, so what it used is what was observed.
    copy_while_emptied(tmp_path, lease=False)
    assert (tmp_path / "out.csv").read_bytes() == b"a,b\n1,2\n"
    (tmp_path / "out.csv").unlink()
    (tmp_path / "in.csv").write_bytes(b"a,b\n1,2\n")
    # With it, the size the lease recorded has fallen: nothing is published.
    with pytest.raises(Inconsistent, match="emptied"):
        copy_while_emptied(tmp_path, lease=True)
    assert not (tmp_path / "out.csv").exists()


def test_a_run_whose_input_is_asked_for_writing_publishes_nothing(tmp_path):
    (tmp_path / "in.csv").write_bytes(b"a,b\n1,2\n")
    r = Run(str(tmp_path), lease=True)
    with pytest.raises(Inconsistent):
        with r.enter(Copy, {"root": str(tmp_path)}) as s:
            assert not open_for_writing_now(tmp_path / "in.csv")
            s.dst.write(s.src.read())
    assert not (tmp_path / "out.csv").exists()
    assert leases_listed(tmp_path / "in.csv") == []  # given up on the way out


def test_a_run_whose_input_has_a_writer_does_not_start(tmp_path):
    (tmp_path / "in.csv").write_bytes(b"a,b\n1,2\n")
    w = os.open(tmp_path / "in.csv", os.O_WRONLY)
    entered = []
    try:
        with pytest.raises(Busy):
            with Run(str(tmp_path), lease=True).enter(Copy, {"root": str(tmp_path)}):
                entered.append(True)
    finally:
        os.close(w)
    assert entered == [] and not (tmp_path / "out.csv").exists()
