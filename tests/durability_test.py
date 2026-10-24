"""What a crash just after publication leaves, for each way of writing an
output (needs root and loop devices; skipped otherwise).

The crash model: an ext4 image mounted through a loop device, with the
journal committing only every 60 s. Straight after the write, the image is
copied without any sync: what reached the device survives, what was still
in memory is lost. The copy is then mounted (replaying the journal) and the
output inspected. A device that reorders its own writes, or loses its
volatile cache, is not modelled."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from wend._experimental.confined import Confined
from wend._experimental.publish import Draft


OLD, NEW = b"old version\n" * 100, b"new version\n" * 100


def _ok(*cmd: str) -> bool:
    return subprocess.run(cmd, capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    os.geteuid() != 0
    or not shutil.which("mkfs.ext4")
    or not Path("/dev/loop-control").exists(),
    reason="needs root, mkfs.ext4 and loop devices",
)


def direct(mnt: Path) -> None:
    with open(mnt / "out" / "final.csv", "wb") as f:
        f.write(NEW)


def rename_unsynced(mnt: Path) -> None:
    tmp = mnt / "out" / ".final.tmp"
    tmp.write_bytes(NEW)
    os.rename(tmp, mnt / "out" / "final.csv")


def rename_file_synced(mnt: Path) -> None:
    tmp = mnt / "out" / ".final.tmp"
    with open(tmp, "wb") as f:
        f.write(NEW)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, mnt / "out" / "final.csv")  # the directory is not synced


def draft(durable: bool):
    def publish(mnt: Path) -> None:
        io = Confined(str(mnt))
        try:
            d = Draft(io, "out")
            d.write(NEW)
            d.publish("final.csv", policy="replace", durable=durable)
        finally:
            io.close()

    return publish


def draft_directory_synced_only(policy: str):
    # publication made durable without the file's own sync: the name can
    # survive while its contents do not
    def publish(mnt: Path) -> None:
        io = Confined(str(mnt))
        try:
            if policy == "create":
                (mnt / "out" / "final.csv").unlink()
                os.sync()
            d = Draft(io, "out")
            d.write(NEW)
            d.publish("final.csv", policy=policy, durable=False)
            fd = os.open(mnt / "out", os.O_RDONLY | os.O_DIRECTORY)
            os.fsync(fd)
            os.close(fd)
        finally:
            io.close()

    return publish


PROTOCOLS = {
    "direct, no sync": direct,
    "rename, no sync": rename_unsynced,
    "rename, file synced": rename_file_synced,
    "draft, not durable": draft(False),
    "draft, durable": draft(True),
    "draft replacing, directory synced only": draft_directory_synced_only("replace"),
    "draft creating, directory synced only": draft_directory_synced_only("create"),
}


def crash_after(tmp_path: Path, protocol, options: str = "") -> bytes | None:
    img, mnt, copy, seen = (
        tmp_path / "fs.img",
        tmp_path / "mnt",
        tmp_path / "crashed.img",
        tmp_path / "seen",
    )
    mnt.mkdir()
    seen.mkdir()
    subprocess.run(["truncate", "-s", "64M", str(img)], check=True)
    subprocess.run(["mkfs.ext4", "-q", "-F", str(img)], check=True)
    if not _ok("mount", "-o", "loop,commit=60" + options, str(img), str(mnt)):
        pytest.skip("cannot loop-mount here")
    try:
        (mnt / "out").mkdir()
        (mnt / "out" / "final.csv").write_bytes(OLD)
        os.sync()  # the old version is on the device
        protocol(mnt)
        shutil.copyfile(img, copy)  # the crash: no sync, what the device holds
    finally:
        subprocess.run(["umount", str(mnt)], check=True)
    subprocess.run(
        ["e2fsck", "-p", str(copy)], capture_output=True
    )  # replay, as a mount would
    subprocess.run(["mount", "-o", "loop,ro", str(copy), str(seen)], check=True)
    try:
        f = seen / "out" / "final.csv"
        return f.read_bytes() if f.exists() else None
    finally:
        subprocess.run(["umount", str(seen)], check=True)


# What a crash may leave, by what each protocol synced. The model: the image
# is copied, unsynced, while mounted; its journal is replayed by e2fsck. An
# unsynced write reaches the device whenever writeback runs, which no test
# controls, so an absent sync permits loss and does not make it certain.
# Only "draft, durable" promises one outcome. For the rest the test asserts
# the outcome is one the syncs permit, never that a particular one occurred.
PERMITTED = {
    # nothing synced: either version, or the truncated file part-written
    "direct, no sync": {"old", "new", "partial"},
    "rename, no sync": {"old", "new", "partial"},
    "draft, not durable": {"old", "new", "partial"},
    # the file synced, the rename not: the rename is lost or kept whole
    "rename, file synced": {"old", "new"},
    # the full protocol: file, publication, directory
    "draft, durable": {"new"},
    # the directory synced commits the name, never the file's data: the new
    # name, its contents written back or not
    "draft replacing, directory synced only": {"new", "partial"},
    "draft creating, directory synced only": {"new", "partial"},
}


def outcome(got: bytes | None) -> str:
    return (
        "new"
        if got == NEW
        else "old"
        if got == OLD
        else "missing"
        if got is None
        else f"partial ({len(got)} bytes)"
    )


def kind(o: str) -> str:
    return "partial" if o.startswith("partial") else o


@pytest.mark.parametrize("name", list(PROTOCOLS))
def test_a_crash_leaves_only_what_the_protocol_permits(tmp_path, name):
    o = outcome(crash_after(tmp_path, PROTOCOLS[name]))
    assert kind(o) in PERMITTED[name], o


# The counterexamples, as demonstrations: each shows a loss *can* happen, so
# each tries a few times and requires it once, not every time (writeback may
# reach the device first; crash_after syncs everything else just before the
# protocol, which makes that rare). On this machine each loss occurred in
# every attempt of 10, 3 and 5 (journal §2).
ATTEMPTS = 5


def demonstrate(tmp_path: Path, name: str, options: str = "") -> list[str]:
    seen = []
    for i in range(ATTEMPTS):
        d = tmp_path / str(i)
        d.mkdir()
        seen.append(outcome(crash_after(d, PROTOCOLS[name], options)))
        if seen[-1] == "partial (0 bytes)":
            break
    return seen


def test_a_name_made_durable_without_its_contents_can_be_left_empty(tmp_path):
    # Creating, with only the directory synced: the name survives the crash
    # and its contents need not. Both syncs are needed.
    seen = demonstrate(tmp_path, "draft creating, directory synced only")
    assert "partial (0 bytes)" in seen, seen


def test_without_auto_da_alloc_replacing_can_lose_the_contents_too(tmp_path):
    # What hid the counterexample for "replace": ext4's auto_da_alloc flushes
    # a file's data when it is renamed over another. With it off, replacing
    # with only the directory synced can leave the name empty, as creating
    # does. The heuristic is no part of the protocol.
    seen = demonstrate(
        tmp_path, "draft replacing, directory synced only", ",noauto_da_alloc"
    )
    assert "partial (0 bytes)" in seen, seen
