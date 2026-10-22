"""Mutants of the research prototypes, and the tests that must reject them.

Each mutant replaces one passage of one source file. For each, the harness:

1. checks the passage occurs exactly once (a mutant that changes nothing
   would read as a survivor);
2. compiles the mutated module (one that does not compile would read as a
   kill, or, run as a subprocess, as a survivor; both are harness errors);
3. runs the named tests on the unmutated sources first, which must pass;
4. runs them on the mutant and records which failed;
5. requires that at least one of ``killed_by`` failed: a kill by some other
   test may be for the wrong reason (an assertion that fails because the
   setup broke, not because the property went);
6. restores the source with its original modification time, and runs the
   tests without writing bytecode. A mutant of the same size as the source,
   restored within the same second, otherwise leaves a cached ``.pyc`` that
   matches the restored source's size and time to the second, and every
   later import, in or out of the harness, runs the mutant.

A mutant may be expected to survive (``survives=`` gives the reason): then
it must survive, so that the reason is checked too. A mutant may end the
test run itself with a signal (``ends_run=``): that is a kill, of a kind no
test can report.

Usage: ``python experiments/mutation/mutants.py [name-substring ...]``.
Exit status 0 only if every mutant met its expectation.
"""

from __future__ import annotations

import os
import py_compile
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRESH = "src/wend/_experimental/fresh.py"
EVENTS = "src/wend/_experimental/events.py"
LEASES = "tests/leases_test.py"
PUBLISH = "src/wend/_experimental/publish.py"
DRAFTS = "tests/drafts_test.py"


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str
    old: str
    new: str
    tests: tuple[str, ...]
    killed_by: tuple[str, ...] = ()
    survives: str = ""  # why it is expected to survive, if it is
    ends_run: int = 0  # a signal that may end the test run itself: a kill
    extra: tuple[tuple[str, str], ...] = field(default=())  # further replacements


MUTANTS = [
    Mutant(
        "leases: no size check (O_TRUNC goes unseen)",
        FRESH,
        "            and os.fstat(fd).st_size == size\n",
        "",
        (LEASES,),
        killed_by=(
            "test_opening_read_only_with_O_TRUNC_empties_the_file_and_keeps_the_lease",
            "test_a_run_sees_its_input_emptied_only_through_the_lease",
            "test_a_leased_collect_is_not_fooled_by_two_truncations",
        ),
    ),
    Mutant(
        "leases: the helper takes none",
        FRESH,
        "        fcntl.fcntl(fd, 1024, fcntl.F_RDLCK)\n",
        "        pass\n",
        (LEASES,),
        killed_by=(
            "test_a_writer_refuses_the_lease_until_it_is_gone",
            "test_a_leased_copy_is_one_version_and_an_unleased_one_need_not_be",
        ),
    ),
    Mutant(
        "leases: taken in this process (the owner is the host)",
        FRESH,
        "            report = _take(self.fds, timeout)\n",
        "            report = _take_here(self.fds)\n",
        (LEASES,),
        killed_by=("test_no_signal_of_a_break_reaches_the_host",),
        # the first break in pytest's own process signals pytest, the owner,
        # by SIGIO, whose default action ends it: the hazard itself
        ends_run=signal.SIGIO,
        extra=(
            (
                "def _take(fds: Sequence[int], timeout: float) -> str:\n",
                "def _take_here(fds):\n"
                "    for fd in fds:\n"
                "        try:\n"
                "            fcntl.fcntl(fd, F_SETLEASE, fcntl.F_RDLCK)\n"
                "        except OSError as e:\n"
                "            return f'{fd} {e.errno}'\n"
                "    return 'ok'\n\n\n"
                "def _take(fds: Sequence[int], timeout: float) -> str:\n",
            ),
        ),
    ),
    Mutant(
        "leases: the previous design (in-process, SIGURG, then no owner)",
        FRESH,
        "            report = _take(self.fds, timeout)\n",
        "            report = _take_redirected(self.fds)\n",
        (LEASES,),
        killed_by=("test_no_moment_of_taking_the_leases_lets_a_break_signal_the_host",),
        extra=(
            (
                "def _take(fds: Sequence[int], timeout: float) -> str:\n",
                "def _take_redirected(fds):\n"
                "    for fd in fds:\n"
                "        fcntl.fcntl(fd, F_SETSIG, 23)\n"
                "        try:\n"
                "            fcntl.fcntl(fd, F_SETLEASE, fcntl.F_RDLCK)\n"
                "        except OSError as e:\n"
                "            return f'{fd} {e.errno}'\n"
                "        fcntl.fcntl(fd, fcntl.F_SETOWN, 0)\n"
                "    return 'ok'\n\n\n"
                "def _take(fds: Sequence[int], timeout: float) -> str:\n",
            ),
        ),
    ),
    Mutant(
        "leases: release gives nothing up",
        FRESH,
        "                fcntl.fcntl(fd, F_SETLEASE, fcntl.F_UNLCK)\n            except OSError:  # none",
        "                pass\n            except OSError:  # none",
        (LEASES,),
        killed_by=("test_a_blocked_writer_goes_on_when_the_leases_are_released",),
    ),
    Mutant(
        "leases: a refusal is not all-or-none in the helper",
        FRESH,
        "        for t in taken:\n            fcntl.fcntl(t, 1024, fcntl.F_UNLCK)\n",
        "        pass\n",
        (LEASES,),
        survives="Leases.__init__ releases every descriptor on any failure as "
        "well; the helper's own release is a second, redundant one",
    ),
    Mutant(
        "leases: a broken lease reads as unbroken",
        FRESH,
        "            fcntl.fcntl(fd, F_GETLEASE) == fcntl.F_RDLCK\n",
        "            True\n",
        (LEASES,),
        killed_by=(
            "test_a_writer_that_arrives_is_held_off_and_breaks_the_lease",
            "test_a_run_whose_input_is_asked_for_writing_publishes_nothing",
        ),
    ),
    Mutant(
        "leases: any filesystem will do",
        FRESH,
        "            if (kind := filesystem(fd)) not in LEASABLE:\n",
        "            if (kind := filesystem(fd)) and False:\n",
        (LEASES,),
        killed_by=("test_a_filesystem_whose_files_change_without_writers_is_refused",),
    ),
    Mutant(
        "run: the leases are never asked after the step",
        EVENTS,
        "                if leases is not None and not leases.unbroken():\n",
        "                if False:\n",
        (LEASES,),
        killed_by=(
            "test_a_run_sees_its_input_emptied_only_through_the_lease",
            "test_a_run_whose_input_is_asked_for_writing_publishes_nothing",
        ),
    ),
    Mutant(
        "run: lease=True takes no leases",
        EVENTS,
        "            if self.lease and held:",
        "            if False:",
        (LEASES,),
        killed_by=("test_a_run_whose_input_has_a_writer_does_not_start",),
    ),
    Mutant(
        "store: a hidden version is made readable by all",
        PUBLISH,
        "os.mkdir(self.hidden, 0o700, dir_fd=self.parentfd)",
        "os.mkdir(self.hidden, 0o755, dir_fd=self.parentfd)",
        (DRAFTS,),
        killed_by=(
            "test_a_hidden_version_is_private_while_it_is_filled",
            "test_other_users_see_a_hidden_version_s_name_but_not_its_contents",
        ),
    ),
    Mutant(
        "store: a claimed version is left private",
        PUBLISH,
        "            os.fchmod(self.dirfd, 0o755)  # readable once claimed\n",
        "",
        (DRAFTS,),
        killed_by=(
            "test_a_hidden_version_is_private_while_it_is_filled",
            "test_other_users_see_a_hidden_version_s_name_but_not_its_contents",
        ),
    ),
    Mutant(
        "store: members are added by the hidden name",
        PUBLISH,
        "        d = Draft(self.store.io, self.dir, held=self.dirfd)\n        d.write(data)\n",
        "        d = Draft(self.store.io, self.dir)\n        d.write(data)\n",
        (DRAFTS,),
        killed_by=("test_a_replaced_hidden_directory_is_neither_filled_nor_claimed",),
    ),
    Mutant(
        "draft: a held directory is ignored",
        PUBLISH,
        "        if self.held is None:\n",
        "        if True:\n",
        (DRAFTS,),
        killed_by=("test_a_replaced_hidden_directory_is_neither_filled_nor_claimed",),
    ),
    Mutant(
        "store: no check before the claim",
        PUBLISH,
        "            if _ident_at(self.parentfd, self.hidden) != self.ident:\n",
        "            if False:\n",
        (DRAFTS,),
        killed_by=(
            "test_a_replaced_hidden_directory_is_neither_filled_nor_claimed",
            "test_a_draft_claimed_by_another_process_is_detected_and_left",
        ),
    ),
    Mutant(
        "store: no check after the claim",
        PUBLISH,
        "            if _ident_at(self.parentfd, name) != self.ident:\n"
        "                raise Inconsistent(\n"
        '                    f"version {self.n} was claimed with',
        "            if False:\n"
        "                raise Inconsistent(\n"
        '                    f"version {self.n} was claimed with',
        (DRAFTS,),
        killed_by=("test_a_directory_put_in_place_as_the_claim_is_made_is_detected",),
    ),
    Mutant(
        "store: a version another process claimed is removed",
        PUBLISH,
        'self.abandon() if outcome == "abandon" else self._spend()',
        'self.abandon() if outcome != "claimed" else self._spend()',
        (DRAFTS,),
        killed_by=(
            "test_a_draft_claimed_by_another_process_is_detected_and_left",
            "test_a_draft_claimed_as_its_claim_is_made_is_left",
        ),
    ),
]


def failed_tests(tests: tuple[str, ...]) -> tuple[set[str], int]:
    with tempfile.TemporaryDirectory() as d:
        xml = Path(d) / "r.xml"
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={xml}",
                *tests,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=900,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        failed = set()
        if xml.exists():
            for case in ET.parse(xml).iter("testcase"):
                if case.find("failure") is not None or case.find("error") is not None:
                    failed.add(case.get("name", "").split("[")[0])
        return failed, r.returncode


def run(m: Mutant) -> tuple[bool, str]:
    path = ROOT / m.file
    original = path.read_text()
    times = os.stat(path)
    text = original
    for old, new in ((m.old, m.new), *m.extra):
        if text.count(old) != 1:
            return False, f"HARNESS: passage occurs {text.count(old)} times: {old!r}"
        text = text.replace(old, new)
    try:
        path.write_text(text)
        with tempfile.TemporaryDirectory() as d:
            py_compile.compile(str(path), cfile=f"{d}/m.pyc", doraise=True)
        failed, code = failed_tests(m.tests)
    except py_compile.PyCompileError as e:
        return False, f"HARNESS: the mutant does not compile: {e.msg}"
    finally:
        path.write_text(original)
        os.utime(path, ns=(times.st_atime_ns, times.st_mtime_ns))
    if m.ends_run and code == -m.ends_run:
        return (
            True,
            f"killed: the test run itself ended by {signal.Signals(-code).name}",
        )
    if code not in (0, 1):
        return False, f"HARNESS: pytest exited {code} (not a test result)"
    if m.survives:
        if failed:
            return (
                False,
                f"expected to survive ({m.survives}); killed by {sorted(failed)}",
            )
        return True, f"survives, as expected: {m.survives}"
    if not failed:
        return False, "SURVIVED"
    right = failed & set(m.killed_by)
    if m.killed_by and not right:
        return False, f"killed, but only by {sorted(failed)}: not by {m.killed_by}"
    return True, f"killed by {sorted(right or failed)}"


def main(names: list[str]) -> int:
    chosen = [m for m in MUTANTS if not names or any(n in m.name for n in names)]
    baseline = sorted({t for m in chosen for t in m.tests})
    failed, code = failed_tests(tuple(baseline))
    if code != 0:
        print(f"BASELINE FAILS: {sorted(failed)}; no mutant can be judged")
        return 1
    bad = 0
    for m in chosen:
        ok, why = run(m)
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {m.name}: {why}", flush=True)
    print(f"{len(chosen) - bad} of {len(chosen)} mutants met their expectation")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
