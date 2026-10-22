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


def crash_after(tmp_path: Path, protocol) -> bytes | None:
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
    if not _ok("mount", "-o", "loop,commit=60", str(img), str(mnt)):
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


@pytest.mark.parametrize("name", list(PROTOCOLS))
def test_what_survives_a_crash_just_after_publication(tmp_path, name):
    got = crash_after(tmp_path, PROTOCOLS[name])
    outcome = (
        "new"
        if got == NEW
        else "old"
        if got == OLD
        else "missing"
        if got is None
        else f"partial ({len(got)} bytes)"
    )
    print(f"{name}: {outcome}")
    if name == "draft, durable":
        assert outcome == "new"  # the only protocol that promises it
    elif name == "draft creating, directory synced only":
        # The counterexample: the name was made durable, its contents not.
        # (Replacing hides this on ext4, which flushes data on a rename over
        # a file.) Both syncs are needed: the file's, then the directory's.
        assert outcome == "partial (0 bytes)"
    else:
        assert outcome in ("new", "old", "missing") or outcome.startswith("partial")
