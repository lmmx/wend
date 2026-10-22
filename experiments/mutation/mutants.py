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
IDENTITY = "src/wend/_experimental/identity.py"
CONFINED_SRC = "src/wend/_experimental/confined.py"
KNOWLEDGE_SRC = "src/wend/_experimental/knowledge.py"
CONFINED = "tests/confined_test.py"
ALIASING = "tests/aliasing_test.py"
KNOWLEDGE = "tests/knowledge_test.py"
PUBLISH_TEST = "tests/publish_test.py"
CONSISTENCY = "tests/consistency_test.py"
EVENTS_TEST = "tests/events_test.py"
FAMILIES_SRC = "src/wend/_experimental/families.py"
FAMILIES = "tests/families_test.py"


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
        "run: a held input's kind is left to the earlier check",
        EVENTS,
        "                    if not held[n].is_file:\n",
        "                    if False:\n",
        (EVENTS_TEST,),
        killed_by=("test_a_swap_between_the_check_and_the_hold_is_judged_at_the_hold",),
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
    # -- confined runs (2026-10-22-confined-runs.md §3) ----------------------
    Mutant(
        "confined: symlinks allowed (no RESOLVE_NO_SYMLINKS)",
        IDENTITY,
        "    RESOLVE = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV\n",
        "    RESOLVE = RESOLVE_BENEATH | RESOLVE_NO_XDEV\n",
        (CONFINED, ALIASING),
        killed_by=("test_an_alias_inside_the_root_is_refused_not_only_escapes",),
    ),
    Mutant(
        "confined: mounts crossed (no RESOLVE_NO_XDEV)",
        IDENTITY,
        "    RESOLVE = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV\n",
        "    RESOLVE = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS\n",
        (CONFINED,),
        killed_by=(
            "test_a_confined_run_never_reaches_outside_the_root",
            "test_each_move_escapes_a_plain_run_and_is_refused_by_a_confined_one",
            "test_deleting_a_tree_does_not_descend_into_a_mount_below_it",
        ),
    ),
    Mutant(
        "confined: deletion enters subdirectories by a plain O_NOFOLLOW open",
        CONFINED_SRC,
        "            sub = openat2(fd, entry.name, os.O_RDONLY | os.O_DIRECTORY, Beneath.RESOLVE)\n",
        "            sub = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)\n",
        (CONFINED,),
        killed_by=("test_deleting_a_tree_does_not_descend_into_a_mount_below_it",),
    ),
    Mutant(
        "confined: parents made by os.makedirs on the path string",
        CONFINED_SRC,
        '        fd = self._dir("")\n        for part in head.split("/") if head else ():\n            if make:\n',
        '        fd = self._dir("")\n        if make and head:\n'
        "            os.makedirs(os.path.join(self.root, head), exist_ok=True)\n"
        '        for part in head.split("/") if head else ():\n            if False:\n',
        (CONFINED,),
        killed_by=("test_making_parents_does_not_follow_a_link_on_the_way",),
    ),
    Mutant(
        "confined: creation not exclusive",
        CONFINED_SRC,
        "            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL\n",
        "            flags = os.O_WRONLY | os.O_CREAT\n",
        (CONFINED,),
        killed_by=("test_a_confined_run_of_the_plan_is_a_checked_plain_run",),
    ),
    Mutant(
        "confined: the plan kept after a step fails",
        CONFINED_SRC,
        "        if not all(done):\n            elide = {}\n",
        "        if False:\n            elide = {}\n",
        (CONFINED,),
        killed_by=("test_a_confined_run_of_the_plan_is_a_checked_plain_run",),
    ),
    Mutant(
        "confined: hard-linked files allowed",
        CONFINED_SRC,
        "            if s.st_nlink != 1:\n",
        "            if False:\n",
        (CONFINED,),
        killed_by=(
            "test_a_confined_run_never_reaches_outside_the_root",
            "test_writing_a_hard_linked_file_refuses_before_truncating",
        ),
    ),
    Mutant(
        "confined: objects of any kind allowed",
        CONFINED_SRC,
        "        elif not st.S_ISDIR(s.st_mode):\n",
        "        elif False:\n",
        (CONFINED,),
        killed_by=("test_a_planted_fifo_is_refused_at_once_and_blocks_a_plain_read",),
    ),
    Mutant(
        "confined: truncation at the open, before the judgement",
        CONFINED_SRC,
        '        with os.fdopen(self._open(rel, os.O_WRONLY), "wb") as f:\n            f.truncate()\n',
        '        with os.fdopen(self._open(rel, os.O_WRONLY | os.O_TRUNC), "wb") as f:\n            pass\n',
        (CONFINED,),
        killed_by=("test_writing_a_hard_linked_file_refuses_before_truncating",),
    ),
    Mutant(
        "confined: blocking opens",
        CONFINED_SRC,
        "        fd = self.b.open(rel, flags | os.O_NONBLOCK)\n",
        "        fd = self.b.open(rel, flags)\n",
        (CONFINED,),
        killed_by=("test_a_planted_fifo_is_refused_at_once_and_blocks_a_plain_read",),
    ),
    # -- knowledge (2026-10-22-knowledge-states.md, its addendum) -------------
    Mutant(
        "knowledge: learn nothing",
        KNOWLEDGE_SRC,
        "            self.facts.add(Fact(a, path))\n",
        "            pass\n",
        (KNOWLEDGE,),
        killed_by=(
            "test_the_analysis_knows_exactly_what_the_worked_pipeline_establishes",
            "test_a_mutation_forgets_the_path_its_parents_and_children",
        ),
    ),
    Mutant(
        "knowledge: never forget",
        KNOWLEDGE_SRC,
        "        region = self._may_create(mutated)\n",
        "        return\n        region = self._may_create(mutated)\n",
        (KNOWLEDGE,),
        killed_by=("test_every_known_fact_holds_at_every_entry",),
    ),
    Mutant(
        "knowledge: forget only the mutated path",
        KNOWLEDGE_SRC,
        "            if not affected(mutated, f.path)\n",
        "            if f.path != mutated\n",
        (KNOWLEDGE,),
        killed_by=("test_every_known_fact_holds_at_every_entry",),
    ),
    Mutant(
        "knowledge: learn a port's preconditions before every check has passed",
        KNOWLEDGE_SRC,
        "            entries.append(Entry(name, port, p, known, frozenset(todo)))\n",
        "            entries.append(Entry(name, port, p, known, frozenset(todo)))\n"
        "            k.learn(req, p)\n",
        (KNOWLEDGE,),
        # a sound refinement, rejected by asserting the rule as designed
        killed_by=(
            "test_the_tracker_knows_the_same_and_learns_nothing_from_a_failed_entry",
        ),
    ),
    # -- aliasing (2026-10-22-aliasing.md §8, addendum A.2) -------------------
    Mutant(
        "families: prefixes cancelled even under different heads",
        FAMILIES_SRC,
        "    if not must_equal(ha, hb) or isinstance(a.head, Deferred):\n",
        "    if isinstance(a.head, Deferred):\n",
        (FAMILIES,),
        killed_by=("test_what_the_analysis_knows_holds_and_what_it_refutes_fails",),
    ),
    Mutant(
        "families: relation is coincidence only, not above or below",
        FAMILIES_SRC,
        '    above or below it."""\n    if must_equal(a, b):\n',
        '    above or below it."""\n    return coincide(a, b)\n    if must_equal(a, b):\n',
        (FAMILIES,),
        killed_by=("test_what_the_analysis_knows_holds_and_what_it_refutes_fails",),
    ),
    Mutant(
        "families: a child's existence derived from its parent's",
        FAMILIES_SRC,
        "                    must_equal(p, e) for p in _parents(f.expr)\n",
        "                    must_equal(p, f.expr) for p in _parents(e)\n",
        (FAMILIES,),
        killed_by=("test_what_the_analysis_knows_holds_and_what_it_refutes_fails",),
    ),
    Mutant(
        "families: must-equal by head and length only",
        FAMILIES_SRC,
        "    return a.pattern == b.pattern and _defaults(a) == _defaults(b)\n",
        "    return PathExpr(a.head, ()).pattern == PathExpr(b.head, ()).pattern and "
        "len(a.parts) == len(b.parts)\n",
        (FAMILIES,),
        killed_by=("test_what_the_analysis_knows_holds_and_what_it_refutes_fails",),
    ),
    Mutant(
        "families: independence ignores the other step's reads",
        FAMILIES_SRC,
        '            for e in b.paths.values():\n                if relation(e, m) != "no":\n',
        "            for e in b.paths.values():\n"
        "                if not e.declares.verbs & MUTATING:\n"
        "                    continue\n"
        '                if relation(e, m) != "no":\n',
        (FAMILIES,),
        killed_by=("test_adjacent_independent_steps_commute",),
    ),
    Mutant(
        "families: forget treats MAYBE as NO",
        FAMILIES_SRC,
        '            if relation(f.expr, m) != "no":\n                continue\n',
        '            if relation(f.expr, m) == "yes":\n                continue\n',
        (FAMILIES,),
        killed_by=("test_a_mutation_related_only_by_maybe_still_forgets",),
    ),
    Mutant(
        "families: must-equal ignores defaults",
        FAMILIES_SRC,
        "    return a.pattern == b.pattern and _defaults(a) == _defaults(b)\n",
        "    return a.pattern == b.pattern\n",
        (FAMILIES,),
        killed_by=("test_different_defaults_are_different_paths",),
    ),
    Mutant(
        "families: learn nothing",
        FAMILIES_SRC,
        "                self.facts.append(FamilyFact(a, _plain(e)))\n",
        "                pass\n",
        (FAMILIES,),
        killed_by=(
            "test_the_worked_pipeline_knows_refutes_and_commutes_what_its_table_shows",
        ),
    ),
    Mutant(
        "families: forget ignores made parents",
        FAMILIES_SRC,
        "                and _may_be_below(f.expr, made)\n",
        "                and False\n",
        (FAMILIES,),
        killed_by=(
            "test_making_a_path_forgets_creatability_below_the_parents_it_may_make",
        ),
    ),
    Mutant(
        "families: independence ignores made parents",
        FAMILIES_SRC,
        '                if e.declares.requires & {"create", "write"} and _may_be_below(e, made):\n',
        "                if False:\n",
        (FAMILIES,),
        killed_by=("test_independence_sees_the_parents_a_creation_may_make",),
    ),
    Mutant(
        "families: made parents bounded where none is known to exist",
        FAMILIES_SRC,
        "            out.append(p)\n        return None\n",
        "            out.append(p)\n        return out\n",
        (FAMILIES,),
        survives=(
            "no construction was found in which the bounded and unbounded readings "
            "differ; overlap answers coarsely for head parameters, which masks it "
            "(families addendum A.1)"
        ),
    ),
    Mutant(
        "aliasing: creation keyed by the first missing entry",
        IDENTITY,
        '    if atom in ("create", "write") and t.obj is None:\n',
        "    if False:\n",
        (ALIASING,),
        # equivalent once #111 is merged: then expected to survive
        killed_by=("test_a_missing_paths_creation_is_judged_where_the_check_looks",),
    ),
    Mutant(
        "aliasing: absent follows a final symlink",
        IDENTITY,
        '        return ("l", t.lfinal) if t.lfinal is not None else ("d", t.is_dir)\n',
        '        return ("f", t.final) if t.final is not None else ("d", t.is_dir)\n',
        (ALIASING,),
        killed_by=("test_absent_does_not_follow_a_final_symlink",),
    ),
    Mutant(
        "aliasing: a path below a file is the file",
        IDENTITY,
        "            below = DirEntry(_ident(os.stat(cand)), todo[0])\n",
        "            return trace(final, None, todo)\n"
        "            below = DirEntry(_ident(os.stat(cand)), todo[0])\n",
        (ALIASING,),
        killed_by=(
            "test_below_a_file_is_not_the_file",
            "test_keyed_by_what_checks_read_every_known_atom_holds",
        ),
    ),
    Mutant(
        "aliasing: a final symlink not followed",
        IDENTITY,
        "        if st.S_ISLNK(s.st_mode):\n",
        "        if st.S_ISLNK(s.st_mode) and todo:\n",
        (ALIASING,),
        killed_by=(
            "test_keyed_by_what_checks_read_every_known_atom_holds",
            "test_an_output_made_as_a_symlink_follows_its_target",
        ),
    ),
    Mutant(
        "aliasing: no entry clause",
        IDENTITY,
        "    if m.final is not None and m.final in f.entries:\n",
        "    if False:\n",
        (ALIASING,),
        killed_by=(
            "test_keyed_by_what_checks_read_every_known_atom_holds",
            "test_with_aliases_eliding_known_checks_changes_nothing",
        ),
    ),
    Mutant(
        "aliasing: no directory clause",
        IDENTITY,
        "    return m.is_dir is not None and m.is_dir in f.dirs\n",
        "    return False\n",
        (ALIASING,),
        killed_by=("test_deleting_a_directory_reached_through_a_bind_mount",),
    ),
    Mutant(
        "aliasing: no object clause",
        IDENTITY,
        "    if m.obj is not None and m.obj == f.obj:\n",
        "    if False:\n",
        (ALIASING,),
        killed_by=(
            "test_two_names_of_one_object_are_forgotten_together",
            "test_hard_links_keep_the_atoms_and_break_content",
        ),
    ),
    Mutant(
        "aliasing: alias_free ignores symlinks",
        IDENTITY,
        "        if any(x.startswith(below) for x in self.links):\n",
        "        if False:\n",
        (ALIASING,),
        killed_by=(
            "test_the_kernel_agrees_with_the_model_on_what_is_alias_free",
            "test_on_an_alias_free_run_string_keyed_knowledge_is_exact",
        ),
    ),
    Mutant(
        "aliasing: alias_free ignores ..",
        IDENTITY,
        "        if any(x == r or x.startswith(below) for x in self.ups):\n",
        "        if False:\n",
        (ALIASING,),
        killed_by=(
            "test_the_kernel_agrees_with_the_model_on_what_is_alias_free",
            "test_on_an_alias_free_run_string_keyed_knowledge_is_exact",
        ),
    ),
    Mutant(
        "aliasing: alias_free ignores mounts",
        IDENTITY,
        '        return "*" not in mounts and not any(\n',
        "        return True or not any(\n",
        (ALIASING,),
        killed_by=(
            "test_a_bind_mount_is_one_directory",
            "test_beneath_refuses_a_mount_crossing_and_dotdot",
        ),
    ),
    Mutant(
        "aliasing: alias_free takes the root as spelled",
        IDENTITY,
        "        r = os.path.realpath(root)\n",
        "        r = root\n",
        (ALIASING,),
        killed_by=(
            "test_alias_freedom_is_judged_below_the_root_however_it_is_spelled",
        ),
    ),
    # -- publication and consistency (2026-10-22-publication-and-consistency.md)
    Mutant(
        "publish: a draft has a name from the start (no O_TMPFILE)",
        PUBLISH,
        '                ".", os.O_TMPFILE | os.O_WRONLY | os.O_CLOEXEC, 0o644, dir_fd=self.dirfd\n',
        '                ".draft", os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC, 0o644, dir_fd=self.dirfd\n',
        (PUBLISH_TEST, CONSISTENCY),
        killed_by=(
            "test_what_a_writer_killed_halfway_leaves_behind",
            "test_a_failed_draft_leaves_nothing",
            "test_a_derivation_names_what_changed_and_what_superseded_it",
        ),
    ),
    Mutant(
        "publish: a derivation ignores its output",
        PUBLISH,
        "        if not self.output.current(io):\n",
        "        if False:\n",
        (CONSISTENCY,),
        killed_by=("test_a_derivation_names_what_changed_and_what_superseded_it",),
    ),
    Mutant(
        "publish: exchange ignores expect",
        PUBLISH,
        "                    if expect is not None and previous != expect:\n",
        "                    if False:\n",
        (PUBLISH_TEST,),
        killed_by=("test_exchange_with_expect_undoes_a_lost_update_but_was_visible",),
    ),
    Mutant(
        "publish: no directory sync",
        PUBLISH,
        "        if durable:\n            os.fsync(self.dirfd)\n",
        "",
        (PUBLISH_TEST,),
        killed_by=(
            "test_the_durability_protocol_syncs_the_file_then_publishes_then_syncs_the_directory",
        ),
    ),
    Mutant(
        "collect: names not resolved again",
        FRESH,
        "                if observe(io, r, content=False).ident != before.ident:\n",
        "                if False:\n",
        (CONSISTENCY,),
        killed_by=(
            "test_a_name_renamed_over_between_the_collects_is_seen_by_its_name",
        ),
    ),
    Mutant(
        "collect: its watch ignored",
        FRESH,
        "        if watch is not None and watch.changed():\n",
        "        if False:\n",
        (CONSISTENCY,),
        killed_by=("test_which_observer_accepts_a_snapshot_that_never_existed",),
    ),
    Mutant(
        "collect: the digest from one read, the copy from another",
        FRESH,
        "            fp, data = _copy(fd)\n",
        "            fp = fingerprint(fd, content=True)\n"
        "            data = os.pread(fd, fp.size, 0)\n",
        (CONSISTENCY,),
        killed_by=("test_a_collect_observes_the_bytes_it_copies",),
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
