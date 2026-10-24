"""What a program knows about its paths before and after each operation
(research prototype; see docs/journal/2026-10-22-knowledge-states.md).

Three things are kept apart (docs/SEMANTICS.md §10.1):

- a *declaration* (`PathExpr.declares`): an obligation an expression states;
- a *checked* fact: an atom a check found true of one rendered path, at the
  moment of the check;
- *knowledge*: the checked facts no effect has invalidated since.

`Knowledge` is a set of `Fact`\\s with two updates, as in a gen/kill dataflow
analysis:

- *learn*: a check (or a confirmation) that passed adds its atoms for the path;
- *forget*: a mutation of a path (a declared ``write``, ``create`` or
  ``delete``) removes every fact about that path, a path below it, or a path
  above it. Making a path can also make its missing parents, which changes
  whether a missing path beside it is creatable (``create`` and ``write``
  of a missing path depend on its nearest existing ancestor), so those
  facts go too, for every path below a parent not known to exist.

Containment is never forgotten: it is a property of the rendered string.

`Tracker` runs `wend.Step`\\s and keeps the knowledge as they run; `analyse`
computes, before anything runs, what each step will know at entry under
the same rules, assuming every earlier step completed. Both rest on a
*closed world*: between checks, the filesystem changes only through the
steps' declared mutations of the paths they render, and two different
rendered strings name different files (no symlink or case aliasing). Outside
that assumption a checked fact is only what §10.1 says: true when checked.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..conditions import ATOMS, Step, check_conditions, contained
from ..errors import ConditionError, IndeterminateError


__all__ = ["Entry", "Fact", "Knowledge", "Tracker", "analyse", "holds"]

CONDITION = {atom: c for c, atom in ATOMS.items()}
MUTATING = frozenset({"write", "create", "delete"})

# Atoms that cannot hold of one path at one moment. Unlike declaring them,
# finding File and Dir together is possible: both hold of a missing path
# (§10: "p is missing, or is a regular file"), so they exclude each other
# only where the path is known to exist.
EXCLUSIVE = (
    ("exists", "absent"),
    ("absent", "read"),
    ("absent", "list"),
    ("file", "list"),
)


@dataclass(frozen=True)
class Fact:
    """An atom found true of one rendered path."""

    atom: str
    path: str

    def __repr__(self) -> str:
        return f"{self.atom}({self.path})"


def holds(fact: Fact, fs: Any = None) -> bool | None:
    """Whether ``fact`` holds now (None if the filesystem cannot say)."""
    try:
        check_conditions(fact.path, (CONDITION[fact.atom],), {}, fs)
    except IndeterminateError:
        return None
    except ConditionError:
        return False
    return True


def affected(mutated: str, path: str) -> bool:
    """Whether mutating ``mutated`` can change a fact about ``path``: the same
    path, one below it, or one above it."""
    return contained(path, mutated) or contained(mutated, path)


@dataclass
class Knowledge:
    facts: set[Fact] = field(default_factory=set)

    def knows(self, atom: str, path: str) -> bool:
        return Fact(atom, path) in self.facts

    def refutes(self, atom: str, path: str) -> Fact | None:
        """A known fact about ``path`` that ``atom`` cannot hold with."""
        for a, b in EXCLUSIVE:
            other = b if atom == a else a if atom == b else None
            if other is not None and self.knows(other, path):
                return Fact(other, path)
        if atom in ("file", "dir") and self.knows("exists", path):
            other = "dir" if atom == "file" else "file"
            if self.knows(other, path):
                return Fact(other, path)
        return None

    def learn(self, atoms: frozenset[str], path: str) -> None:
        for a in atoms:
            self.facts.add(Fact(a, path))

    def forget(self, mutated: str) -> None:
        region = self._may_create(mutated)
        self.facts = {
            f
            for f in self.facts
            if not affected(mutated, f.path)
            and not (
                f.atom in ("create", "write")
                and not self.knows("exists", f.path)
                and any(contained(f.path, r) for r in region)
            )
        }

    def _may_create(self, mutated: str) -> list[str]:
        """The parents of ``mutated`` that making it may create: those below
        the deepest parent known to exist (all of them if none is)."""
        parents = []
        p = posixpath.dirname(mutated)
        while p and p != posixpath.dirname(p):
            if self.knows("exists", p):
                break
            parents.append(p)
            p = posixpath.dirname(p)
        return parents


@dataclass(frozen=True)
class Entry:
    """At one step's entry, for one of its paths: which required atoms were
    already known, which were checked, and which a known fact refuted."""

    step: str
    port: str
    path: str
    known: frozenset[str]
    checked: frozenset[str]
    refuted: frozenset[str] = frozenset()


def _render(step: Step, env: Mapping[str, Any]) -> dict[str, str]:
    return {k: e.render(env) for k, e in step.paths.items()}


class Tracker:
    """Runs steps and keeps what is known about their paths.

    With ``elide=True`` a required atom already known is not checked again;
    with ``elide=False`` (the default) every required atom is checked, and
    `entries` records which of them were already known, so the claim that
    eliding is safe can be tested.
    """

    def __init__(self, *, elide: bool = False, fs: Any = None) -> None:
        self.knowledge = Knowledge()
        self.entries: list[Entry] = []
        self.elide = elide
        self.fs = fs

    @contextmanager
    def run(
        self, name: str, step: Step, env: Mapping[str, Any]
    ) -> Iterator[dict[str, Path]]:
        k = self.knowledge
        paths = _render(step, env)
        entries = []
        for port, e in step.paths.items():
            p, req = paths[port], e.declares.requires
            known = frozenset(a for a in req if k.knows(a, p))
            todo = req - known if self.elide else req
            check_conditions(p, tuple(CONDITION[a] for a in sorted(todo)), env, self.fs)
            entries.append(Entry(name, port, p, known, frozenset(todo)))
        # Every precondition held: they are known until something mutates.
        for port, e in step.paths.items():
            k.learn(e.declares.requires, paths[port])
        self.entries.extend(entries)
        try:
            yield {port: Path(p) for port, p in paths.items()}
        finally:
            # Whatever the body did (or did partly, if it raised), a declared
            # mutation may have changed its path and those around it.
            for port, e in step.paths.items():
                if e.declares.verbs & MUTATING:
                    k.forget(paths[port])
        for port, e in step.paths.items():
            post = e.declares.ensures
            check_conditions(
                paths[port], tuple(CONDITION[a] for a in sorted(post)), env, self.fs
            )
            k.learn(post, paths[port])


def analyse(
    steps: Sequence[tuple[str, Step]], env: Mapping[str, Any] | None = None
) -> list[Entry]:
    """What each step will know at entry, before anything runs: the same
    learn and forget as `Tracker`, on the paths rendered with ``env``,
    assuming every earlier step completed (its checks passed). ``refuted``
    names required atoms a known fact contradicts: that check will fail."""
    k = Knowledge()
    out = []
    for name, step in steps:
        paths = _render(step, env or {})
        for port, e in step.paths.items():
            p, req = paths[port], e.declares.requires
            known = frozenset(a for a in req if k.knows(a, p))
            refuted = frozenset(a for a in req if k.refutes(a, p))
            out.append(Entry(name, port, p, known, req - known, refuted))
        for port, e in step.paths.items():
            k.learn(e.declares.requires, paths[port])
        for port, e in step.paths.items():
            if e.declares.verbs & MUTATING:
                k.forget(paths[port])
        for port, e in step.paths.items():
            k.learn(e.declares.ensures, paths[port])
    return out
