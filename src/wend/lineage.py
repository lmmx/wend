"""Lineage: where a path came from, before and after it exists (SEMANTICS.md §13).

A path has two pasts.

- **As a plan**, an expression records how it was built (§9): ``upstream``
  lists the expressions it derives from, ``explain`` writes the chain out, and
  ``tags`` collects the tags (``e.tag(source="upload")``) found along it.
- **As an artefact**, a file was produced from other files by some
  operation. A `Ledger` records that, with the inputs' content digests, so
  later you can ask what a file was made from (``provenance``,
  ``upstream``), what was made from it (``downstream``) and whether it is
  out of date (``stale``). `Ledger.run` records a `Step` automatically.

Content addressing names a path after what it holds: ``content_key(*paths)``
digests files (an effect), ``values_key(**values)`` digests plain values
(pure), and either is bound to an ordinary parameter, so ``render`` stays
pure and ``match`` reads the key back::

    cache = P(root) / "cache" / T(t"{key}") / "features.parquet"
    out = cache.render(root="/data", key=content_key(raw))
    cache.match(out)["key"] == content_key(raw)   # still true while raw is unchanged

wend records relations; scheduling (what to rebuild, in which order) is left
to the caller or a workflow tool.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._expr import PathExpr


if TYPE_CHECKING:
    from .conditions import Step


__all__ = [
    "Ledger",
    "Record",
    "content_key",
    "digest_file",
    "explain",
    "tags",
    "upstream",
    "values_key",
]


# ---------------------------------------------------------------------------
# Lineage of expressions (static)
# ---------------------------------------------------------------------------


def _children(e: PathExpr) -> list[PathExpr]:
    d = e.derivation
    if d is None:
        return []
    out = []
    for a in d.args:
        if isinstance(a, PathExpr):
            out.append(a)
        elif isinstance(a, dict):
            out.extend(v for v in a.values() if isinstance(v, PathExpr))
    return out


def upstream(e: PathExpr) -> list[PathExpr]:
    """The expressions ``e`` was built from, sources first, each once."""
    seen: set[int] = set()
    out: list[PathExpr] = []

    def visit(x: PathExpr) -> None:
        for c in _children(x):
            if id(c) not in seen:
                seen.add(id(c))
                visit(c)
                out.append(c)

    visit(e)
    return out


def explain(e: PathExpr) -> str:
    """How ``e`` was built, one operation per line, sources first."""
    lines = []
    for x in [*upstream(e), e]:
        d = x.derivation
        if d is None:
            continue
        args = ", ".join(
            a.pattern if isinstance(a, PathExpr) else repr(a) for a in d.args
        )
        lines.append(f"{x.pattern} = {d.op}({args})")
    return "\n".join(lines) if lines else f"{e.pattern} (built directly)"


def tags(e: PathExpr) -> dict[str, Any]:
    """The tags on ``e`` and on every expression it was built from; a nearer
    expression's tag wins over a source's."""
    out: dict[str, Any] = {}
    for x in [*upstream(e), e]:
        out.update(x.tags)
    return out


# ---------------------------------------------------------------------------
# Digests and content keys
# ---------------------------------------------------------------------------


def digest_file(path: Any, algorithm: str = "sha256") -> str:
    """``"<algorithm>:<hex>"`` of a file's bytes (an effect: reads the file)."""
    h = hashlib.new(algorithm)
    with open(os.fspath(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"{algorithm}:{h.hexdigest()}"


def content_key(*paths: Any, length: int = 16, algorithm: str = "sha256") -> str:
    """A key naming the contents of ``paths`` (in order): the first ``length``
    hex digits of a digest of their digests. An effect: reads the files."""
    h = hashlib.new(algorithm)
    for p in paths:
        h.update(digest_file(p, algorithm).encode())
        h.update(b"\n")
    return h.hexdigest()[:length]


def values_key(length: int = 16, algorithm: str = "sha256", **values: Any) -> str:
    """A key naming a set of values (build parameters, say): a digest of
    their canonical JSON, with keys sorted. Pure."""
    text = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.new(algorithm, text.encode()).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Lineage of artefacts (a ledger)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    """That ``path`` was produced from ``inputs`` by ``operation``.

    ``inputs`` pairs each input path with its digest when recorded (None if
    it was not digested); ``digest`` is the output's own.
    """

    path: str
    inputs: tuple[tuple[str, str | None], ...] = ()
    operation: str = ""
    bindings: Mapping[str, Any] = field(default_factory=dict)
    tags: Mapping[str, Any] = field(default_factory=dict)
    digest: str | None = None
    time: float = 0.0

    def to_json(self) -> str:
        return json.dumps(
            {
                "path": self.path,
                "inputs": [list(i) for i in self.inputs],
                "operation": self.operation,
                "bindings": dict(self.bindings),
                "tags": dict(self.tags),
                "digest": self.digest,
                "time": self.time,
            },
            default=str,
        )

    @classmethod
    def from_json(cls, line: str) -> Record:
        d = json.loads(line)
        return cls(
            d["path"],
            tuple((p, g) for p, g in d["inputs"]),
            d.get("operation", ""),
            d.get("bindings", {}),
            d.get("tags", {}),
            d.get("digest"),
            d.get("time", 0.0),
        )


def _norm(p: Any) -> str:
    return os.path.normpath(os.path.abspath(os.fspath(p)))


class Ledger:
    """An append-only record of which files were made from which, kept as
    JSON lines in ``path``. Paths are stored absolute and normalised; the
    latest record for a path is its provenance."""

    def __init__(self, path: Any, *, digests: bool = True) -> None:
        self.path = Path(path)
        self.digests = digests

    def __repr__(self) -> str:
        return f"Ledger({str(self.path)!r})"

    # -- writing --------------------------------------------------------------

    def record(
        self,
        output: Any,
        inputs: Iterable[Any] = (),
        *,
        operation: str = "",
        bindings: Mapping[str, Any] | None = None,
        tags: Mapping[str, Any] | None = None,
    ) -> Record:
        """Record that ``output`` was made from ``inputs`` (an effect: digests
        the files that exist, then appends to the ledger)."""
        out = _norm(output)
        ins = tuple((_norm(i), self._digest(i)) for i in inputs)
        rec = Record(
            out,
            ins,
            operation,
            dict(bindings or {}),
            dict(tags or {}),
            self._digest(output),
            time.time(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(rec.to_json() + "\n")
        return rec

    def _digest(self, p: Any) -> str | None:
        if not self.digests or not os.path.isfile(os.fspath(p)):
            return None
        return digest_file(p)

    @contextmanager
    def run(
        self,
        step: Step,
        mapping: Mapping[Any, Any] | None = None,
        /,
        **bindings: Any,
    ) -> Iterator[dict[str, Path]]:
        """Run ``step`` like ``with step(...)`` and, when it succeeds, record
        each path it declares it creates, writes or deletes as made from the
        paths it declares it reads (its `effects`). The operation is the
        step's repr; tags are each output expression's lineage tags."""
        from ._expr import _make_env

        env = _make_env(mapping, bindings)
        with step(env) as paths:
            yield paths
        effects = step.effects()
        reads = [paths[e.name] for e in effects if "read" in e.verbs]
        for e in effects:
            if e.verbs & {"create", "write", "delete"}:
                used = {k: v for k, v in env.items() if k in e.expr.param_names}
                self.record(
                    paths[e.name],
                    reads,
                    operation=repr(step),
                    bindings=used,
                    tags=tags(e.expr),
                )

    # -- reading --------------------------------------------------------------

    def records(self) -> list[Record]:
        if not self.path.exists():
            return []
        with open(self.path) as f:
            return [Record.from_json(ln) for ln in f if ln.strip()]

    def _latest(self) -> dict[str, Record]:
        latest: dict[str, Record] = {}
        for r in self.records():
            latest[r.path] = r
        return latest

    def provenance(self, path: Any) -> Record | None:
        """The latest record for ``path``, or None if it was never recorded."""
        return self._latest().get(_norm(path))

    def upstream(self, path: Any) -> list[str]:
        """Every path ``path`` was made from, directly or not, nearest first."""
        latest = self._latest()
        out: list[str] = []
        frontier = [_norm(path)]
        while frontier:
            nxt = []
            for p in frontier:
                r = latest.get(p)
                for i, _ in r.inputs if r else ():
                    if i not in out:
                        out.append(i)
                        nxt.append(i)
            frontier = nxt
        return out

    def downstream(self, path: Any) -> list[str]:
        """Every recorded path made from ``path``, directly or not, nearest
        first: what to invalidate when ``path`` changes or is corrupt."""
        latest = self._latest()
        users: dict[str, list[str]] = {}
        for r in latest.values():
            for i, _ in r.inputs:
                users.setdefault(i, []).append(r.path)
        out: list[str] = []
        frontier = [_norm(path)]
        while frontier:
            nxt = []
            for p in frontier:
                for u in users.get(p, ()):
                    if u not in out:
                        out.append(u)
                        nxt.append(u)
            frontier = nxt
        return out

    def stale(self, path: Any) -> list[str]:
        """The inputs of ``path``'s latest record whose content is not what
        it was when ``path`` was made (changed, or gone), checked now. Empty
        when ``path`` is up to date, or was never recorded."""
        r = self.provenance(path)
        if r is None:
            return []
        out = []
        for i, digest in r.inputs:
            if not os.path.exists(i):
                out.append(i)
            elif (
                digest is not None and digest_file(i, digest.split(":", 1)[0]) != digest
            ):
                out.append(i)
        return out
