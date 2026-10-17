"""Filesystem layout inference: from observed paths to wend expressions.

The analogue of JSON schema inference (genson, polars-genson) for directory
trees. Observed paths form a tree, which is generalised bottom-up:

- Names are tokenised into digit runs and the text between them, giving a
  *skeleton* (``chunk_#-of-#.parquet``). Siblings with the same skeleton merge;
  each digit run that varies becomes an ``int`` field whose format spec
  (``04d``, ``d``) is chosen so that every observed value round-trips, and runs
  that never vary stay literal.
- Sibling directories whose contents are structurally similar (Jaccard
  similarity of their children's skeletons) collapse into one segment field,
  like genson's record-to-map unification. Files that share an extension
  collapse into ``{stem}.ext`` once there are enough of them.
- Merging directories re-unifies their children, and every child records
  which of the merged directories contained it, so optional entries are
  reported (genson's required vs optional keys).

Every observed path matches at least one inferred layout; field statistics
record the values seen without constraining new ones.
"""

from __future__ import annotations

import itertools
import os
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any

from ._expr import REL, Field, P, PathExpr, Seg, _norm
from ._match import Match
from ._params import Kind, Param


_RUN = re.compile(r"[0-9]+")  # ASCII only: int() would accept other digits
_WORD = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class _Config:
    min_dirs: int = 2
    min_files: int = 3
    similarity: float = 0.5


def _int_spec(values: list[str]) -> str | None:
    """A format spec under which every observed digit string round-trips."""
    if all(v == "0" or not v.startswith("0") for v in values):
        return "d"
    width = min(len(v) for v in values)
    if all(len(v) == width or not v.startswith("0") for v in values):
        return f"0{width}d"
    return None


@dataclass
class _Rule:
    """A generalised entry: a name pattern, a kind, and (for dirs) contents.

    ``shape`` is ("num", literal pieces) for names containing digit runs (the
    runs' observed values are in ``runs``), ("lit", name) for other names, or
    ("str", suffix) for a name generalised into a string field.
    """

    kind: str
    shape: tuple[Any, ...]
    runs: list[list[str]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    paths: list[str] = field(
        default_factory=list
    )  # observed full paths, parallel to names
    children: list[_Rule] = field(default_factory=list)
    ids: frozenset[int] = frozenset()  # original directories merged into this rule
    owners: frozenset[int] = frozenset()  # original parent directories containing it

    def skeleton(self) -> tuple[Any, ...]:
        return (self.kind, self.shape)

    @property
    def count(self) -> int:
        return len(self.names)

    def literal_like(self) -> bool:
        if self.shape[0] == "lit":
            return True
        return self.shape[0] == "num" and all(len(set(v)) == 1 for v in self.runs)


def _merge(rules: list[_Rule], shape: tuple[Any, ...], cfg: _Config) -> _Rule:
    out = _Rule(rules[0].kind, shape)
    if shape[0] == "num":
        out.runs = [
            [v for r in rules for v in r.runs[i]] for i in range(len(rules[0].runs))
        ]
    out.names = [n for r in rules for n in r.names]
    out.paths = [p for r in rules for p in r.paths]
    out.ids = frozenset().union(*(r.ids for r in rules))
    out.owners = frozenset().union(*(r.owners for r in rules))
    if out.kind == "dir":
        out.children = _unify([c for r in rules for c in r.children], cfg)
    return out


def _jaccard(a: set[Any], b: set[Any]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 1.0


def _unify(rules: list[_Rule], cfg: _Config) -> list[_Rule]:
    out: list[_Rule] = []
    lone: list[_Rule] = []
    # 1. Rules with the same skeleton merge (digit runs pool their values).
    by_skel: dict[tuple[Any, ...], list[_Rule]] = defaultdict(list)
    for r in rules:
        by_skel[r.skeleton()].append(r)
    for (_kind, shape), ms in by_skel.items():
        merged = _merge(ms, shape, cfg) if len(ms) > 1 else ms[0]
        (lone if merged.literal_like() else out).append(merged)
    # 2. Directories with similar contents collapse into one segment field.
    dirs = [r for r in lone if r.kind == "dir"]
    clusters: list[list[_Rule]] = []
    for d in sorted(dirs, key=lambda r: (-len(r.children), r.names[0])):
        keys = {c.skeleton() for c in d.children}
        for cl in clusters:
            if (
                keys
                and _jaccard(keys, {c.skeleton() for c in cl[0].children})
                >= cfg.similarity
            ):
                cl.append(d)
                break
        else:
            clusters.append([d])
    for cl in clusters:
        if len(cl) >= cfg.min_dirs and cl[0].children:
            out.append(_merge(cl, ("str", ""), cfg))
        else:
            out.extend(cl)
    # 3. Files sharing an extension collapse into {stem}.ext.
    by_suffix: dict[str, list[_Rule]] = defaultdict(list)
    for f in (r for r in lone if r.kind == "file"):
        by_suffix[PurePosixPath(f.names[0]).suffix].append(f)
    for suffix, fs in by_suffix.items():
        if len(fs) >= cfg.min_files:
            out.append(_merge(fs, ("str", suffix), cfg))
        else:
            out.extend(fs)
    return sorted(out, key=lambda r: (r.kind, repr(r.shape), r.names[0]))


@dataclass
class FieldStats:
    """What was observed for one inferred field."""

    name: str
    type: type
    count: int
    distinct: int
    min: Any = None
    max: Any = None
    sample: tuple[Any, ...] = ()

    def __repr__(self) -> str:
        rng = f" in [{self.min}, {self.max}]" if self.type is int else ""
        return (
            f"<{self.name}: {self.type.__name__}{rng}, {self.distinct} distinct, "
            f"e.g. {list(self.sample[:3])}>"
        )


@dataclass
class Layout:
    """One inferred path pattern, relative to the inferred root."""

    expr: PathExpr
    kind: str
    count: int
    fields: dict[str, FieldStats]
    optional: bool

    def __repr__(self) -> str:
        opt = ", optional" if self.optional else ""
        return f"Layout({self.expr.pattern!r}, {self.kind}, {self.count} paths{opt})"

    def match(self, path: Any) -> Match | None:
        return self.expr.match(path)

    def under(self, root: Any) -> PathExpr:
        """The layout as an expression rooted at ``root``."""
        return P(root) / self.expr

    def rename(self, **names: str) -> Layout:
        """Rename inferred fields, e.g. ``layout.rename(data="split")``."""
        env = {}
        for old, new in names.items():
            p = self.expr.params[old]
            env[old] = Param(new, p.kind, p.type)
        fields = {
            names.get(k, k): replace(v, name=names.get(k, k))
            for k, v in self.fields.items()
        }
        return Layout(self.expr.bind(env), self.kind, self.count, fields, self.optional)


@dataclass
class Schema:
    """The result of `infer`: layouts that together cover every observed path."""

    layouts: list[Layout]
    total: int

    def __repr__(self) -> str:
        lines = [f"Schema({self.total} paths, {len(self.layouts)} layouts)"]
        for lay in self.layouts:
            opt = "  (optional)" if lay.optional else ""
            lines.append(f"  {lay.count:>6}  {lay.kind:<4} {lay.expr.pattern}{opt}")
        return "\n".join(lines)

    def match(self, path: Any) -> list[tuple[Layout, Match]]:
        """Every layout that matches ``path``, with its bindings."""
        out = []
        for lay in self.layouts:
            m = lay.match(path)
            if m is not None:
                out.append((lay, m))
        return out

    def check(self, paths: Iterable[Any]) -> list[str]:
        """Paths that no layout matches (empty when the schema covers them all)."""
        return [str(p) for p in paths if not self.match(p)]


def _ident(s: str) -> str:
    s = re.sub(r"\W+", "_", s).strip("_").lower()
    return s if s and not s[0].isdigit() else ""


def _unique(base: str, used: set[str]) -> str:
    base = base or "n"
    name, i = base, 2
    while name in used:
        name, i = f"{base}{i}", i + 1
    used.add(name)
    return name


def _segment(
    r: _Rule, parent: str, used: set[str], stats: list[tuple[str, type, list[Any]]]
) -> Seg:
    kind, arg = r.shape
    if kind == "lit":
        return Seg((r.names[0],))
    if kind == "str":
        if r.kind == "dir":
            name = _unique(_ident(parent) or "dir", used)
            stats.append((name, str, list(r.names)))
            return Seg((Field(Param(name, Kind.SEGMENT), role="segment"),))
        name = _unique("stem" if arg else "name", used)
        stats.append(
            (name, str, [n[: len(n) - len(arg)] if arg else n for n in r.names])
        )
        return Seg(_norm([Field(Param(name, type=str)), arg]))
    pieces: list[Any] = []
    for lit, vals in itertools.zip_longest(arg, r.runs):
        pieces.append(lit)
        if vals is None:
            continue
        if len(set(vals)) == 1:
            pieces.append(vals[0])
            continue
        words = _WORD.findall(lit)
        name = _unique(_ident(words[-1]) if words else "n", used)
        spec = _int_spec(vals)
        if spec is None:
            pieces.append(Field(Param(name, type=str)))
            stats.append((name, str, list(vals)))
        else:
            pieces.append(Field(Param(name, type=int), None, (spec,)))
            stats.append((name, int, [int(v) for v in vals]))
    return Seg(_norm(pieces))


def _flatten(
    rules: list[_Rule],
    prefix: tuple[Seg, ...],
    parent: str,
    parent_ids: frozenset[int],
    used: set[str],
    stats: list[tuple[str, type, list[Any]]],
    optional: bool,
    out: list[Layout],
) -> None:
    for r in rules:
        my_used = set(used)
        my_stats = list(stats)
        seg = _segment(r, parent, my_used, my_stats)
        is_opt = optional or (bool(parent_ids) and r.owners != parent_ids)
        path = (*prefix, seg)
        if r.kind == "file" or not r.children:
            expr = PathExpr(REL, path)
            # Statistics come from matching this leaf's own observed paths,
            # which also verifies that each of them round-trips.
            seen: dict[str, list[Any]] = {n: [] for n, _, _ in my_stats}
            for observed in r.paths:
                m = expr.match(observed)
                if m is None:  # pragma: no cover - would be an inference bug
                    raise AssertionError(
                        f"{observed!r} does not match inferred {expr.pattern!r}"
                    )
                for k, v in m.items():
                    seen[k].append(v)
            fields = {
                n: FieldStats(
                    n,
                    t,
                    len(seen[n]),
                    len(set(seen[n])),
                    min(seen[n]) if t is int else None,
                    max(seen[n]) if t is int else None,
                    tuple(sorted(set(seen[n]), key=str)[:5]),
                )
                for n, t, _ in my_stats
            }
            out.append(Layout(expr, r.kind, len(r.paths), fields, is_opt))
        else:
            label = r.names[0] if r.literal_like() else parent
            _flatten(r.children, path, label, r.ids, my_used, my_stats, is_opt, out)


def _observe(source: Any, include_hidden: bool) -> list[tuple[str, bool]]:
    if isinstance(source, (str, os.PathLike)):
        if not os.path.isdir(source):
            raise NotADirectoryError(f"{os.fspath(source)!r} is not a directory")
        root = os.fspath(source)
        found: list[tuple[str, bool]] = []
        for dp, dns, fns in os.walk(root):
            if not include_hidden:
                dns[:] = [d for d in dns if not d.startswith(".")]
                fns = [f for f in fns if not f.startswith(".")]
            dns.sort()
            rel = os.path.relpath(dp, root)
            for f in sorted(fns):
                found.append((f if rel == "." else f"{rel}/{f}", False))
            if not dns and not fns and rel != ".":
                found.append((rel, True))
        return found
    out = []
    for p in source:
        s = os.fspath(p)
        out.append((str(PurePosixPath(s)), s.endswith("/")))
    return out


def infer(
    source: Any,
    *,
    min_dirs: int = 2,
    min_files: int = 3,
    similarity: float = 0.5,
    include_hidden: bool = False,
) -> Schema:
    """Infer layouts from a directory (walked) or an iterable of relative paths.

    In an iterable, a trailing "/" marks a directory. ``min_dirs`` and
    ``min_files`` are how many similar siblings it takes to generalise a name
    into a field; ``similarity`` is the Jaccard threshold on directory
    contents. Hidden entries are skipped unless ``include_hidden``.
    """
    cfg = _Config(min_dirs, min_files, similarity)
    observed = _observe(source, include_hidden)
    tree: dict[str, Any] = {}
    for path, is_dir in observed:
        parts = [x for x in PurePosixPath(path).parts if x != "/"]
        node = tree
        for i, name in enumerate(parts):
            if i == len(parts) - 1 and not is_dir:
                if isinstance(node.get(name), dict):
                    raise ValueError(f"{path!r} is listed as a file and as a directory")
                node[name] = None
            else:
                if name in node and node[name] is None:
                    raise ValueError(
                        f"{'/'.join(parts[: i + 1])!r} is listed as a file and as a directory"
                    )
                node = node.setdefault(name, {})

    counter = itertools.count()

    def build(children: dict[str, Any], owner: int, at: str) -> list[_Rule]:
        rules = []
        for name, sub in children.items():
            full = f"{at}/{name}" if at else name
            runs = _RUN.findall(name)
            shape = ("num", tuple(_RUN.split(name))) if runs else ("lit", name)
            r = _Rule(
                "file" if sub is None else "dir",
                shape,
                [[v] for v in runs],
                [name],
                [full],
                owners=frozenset([owner]),
            )
            if sub is not None:
                me = next(counter)
                r.ids = frozenset([me])
                r.children = build(sub, me, full)
            rules.append(r)
        return _unify(rules, cfg)

    root_id = next(counter)
    layouts: list[Layout] = []
    _flatten(
        build(tree, root_id, ""),
        (),
        "",
        frozenset([root_id]),
        set(),
        [],
        False,
        layouts,
    )
    layouts.sort(key=lambda lay: (-lay.count, lay.expr.pattern))
    return Schema(layouts, len(observed))
