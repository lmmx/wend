"""Filesystem layout inference: from observed paths to wend expressions.

The analogue of JSON schema inference (genson, polars-genson) for directory
trees. Observed paths form a tree, which is generalised bottom-up:

- Names are tokenised into digit runs and the text between them, giving a
  *skeleton* (``chunk_#-of-#.parquet``). Siblings with the same skeleton merge;
  each digit run that varies becomes an ``int`` field whose format spec
  (``04d``, ``d``) is chosen so that every observed value round-trips, and runs
  that never vary stay literal. Names whose runs need different specs are
  split, so a stray ``epoch_7`` among ``epoch_001``... is reported on its own.
- Sibling directories whose contents are structurally similar (Jaccard
  similarity of their children's skeletons) collapse into one segment field,
  like genson's record-to-map unification. Files that share an extension
  collapse into ``{stem}.ext`` once there are enough of them. A map at a
  position absorbs the similar directories and same-extension files beside it.
- Merging directories re-unifies their children. A field whose observed
  values always equal an earlier field's becomes the same parameter
  (``n01440764/n01440764_10026.JPEG``).

Every observed path matches at least one inferred layout, and each layout's
``count`` and field statistics come from the paths it was inferred from, so
the counts partition the observed paths. ``optional`` is a property of the
pattern: some observed directory matching a prefix of it contains none of
the paths it matches. Statistics record the values seen without constraining
new ones.
"""

from __future__ import annotations

import itertools
import os
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any

from ._expr import REL, Field, P, PathExpr, Seg, _norm
from ._match import Match, _match_seg, _seg_fast, seg_plan
from ._params import Kind, Param
from .errors import WendError


_RUN = re.compile(r"[0-9]+")  # ASCII only: int() would accept other digits
_WORD = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class _Config:
    min_dirs: int = 2
    min_files: int = 3
    similarity: float = 0.5


def _int_spec(values: list[str]) -> str | None:
    """A format spec under which every observed digit string round-trips.

    Runs of one width wider than a digit read as zero padded even without a
    leading zero (``IMG_1234`` most likely comes from ``IMG_{n:04d}``).
    """
    width = min(len(v) for v in values)
    if width > 1 and all(len(v) == width for v in values):
        return f"0{width}d"
    if all(v == "0" or not v.startswith("0") for v in values):
        return "d"
    if all(len(v) == width or not v.startswith("0") for v in values):
        return f"0{width}d"
    return None


def _fits(value: str, spec: str | None) -> bool:
    return spec is None or format(int(value), spec) == value


def _partition(rules: list[_Rule]) -> list[list[_Rule]]:
    """Split same-skeleton rules into groups whose digit runs share a spec.

    Each rule is consistent on its own, so the spec vector of the rule
    covering the most names always selects a non-empty group: a stray
    ``epoch_7`` among ``epoch_001``... becomes its own rule instead of
    turning the field into a string.
    """
    if len(rules) == 1 or not rules[0].runs:
        return [rules]
    n = len(rules[0].runs)
    varying = [i for i in range(n) if len({v for r in rules for v in r.runs[i]}) > 1]

    def vector(r: _Rule) -> tuple[str | None, ...]:
        return tuple(_int_spec(r.runs[i]) if i in varying else None for i in range(n))

    def fits(r: _Rule, vec: tuple[str | None, ...]) -> bool:
        return all(_fits(v, vec[i]) for i in varying for v in r.runs[i])

    groups: list[list[_Rule]] = []
    rest = rules
    while rest:
        cands = {vector(r) for r in rest}
        best = max(
            cands,
            key=lambda vec: (sum(r.count for r in rest if fits(r, vec)), str(vec)),
        )
        group = [r for r in rest if fits(r, best)]
        rest = [r for r in rest if not fits(r, best)]
        groups.append(group)
    return groups


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
    if out.kind == "dir":
        out.children = _unify([c for r in rules for c in r.children], cfg)
    return out


def _jaccard(a: set[Any], b: set[Any]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 1.0


def _coarse(r: _Rule) -> str:
    return PurePosixPath(r.names[0]).suffix


def _similar(a: _Rule, b: _Rule) -> float:
    """Similarity of two directories' contents.

    Jaccard similarity of the children's skeletons, except that directories
    holding only one-off file names are alike when their extensions are the
    same (``alpha/{alpha.txt, data.bin}`` and ``beta/{beta.txt, data.bin}``).
    """
    fine = _jaccard(
        {c.skeleton() for c in a.children}, {c.skeleton() for c in b.children}
    )
    kids = (*a.children, *b.children)
    if all(c.kind == "file" and c.literal_like() for c in kids) and {
        _coarse(c) for c in a.children
    } == {_coarse(c) for c in b.children}:
        return 1.0
    return fine


def _unify(rules: list[_Rule], cfg: _Config) -> list[_Rule]:
    out: list[_Rule] = []
    lone: list[_Rule] = []
    # 1. Rules with the same skeleton merge (digit runs pool their values),
    #    in groups whose runs share a format spec.
    by_skel: dict[tuple[Any, ...], list[_Rule]] = defaultdict(list)
    for r in rules:
        by_skel[r.skeleton()].append(r)
    for (_kind, shape), ms in by_skel.items():
        for group in _partition(ms):
            merged = _merge(group, shape, cfg) if len(group) > 1 else group[0]
            (lone if merged.literal_like() else out).append(merged)
    # 2. Directories with similar contents collapse into one segment field.
    #    A map already at this position (from merged parents) absorbs similar
    #    directories, and every qualifying cluster joins the same map, since
    #    they would all be the same pattern.
    dir_map = next((r for r in out if r.kind == "dir" and r.shape == ("str", "")), None)
    if dir_map is not None:
        out.remove(dir_map)
    clusters: list[list[_Rule]] = []
    for d in sorted(
        (r for r in lone if r.kind == "dir"),
        key=lambda r: (-len(r.children), r.names[0]),
    ):
        for cl in clusters:
            if d.children and _similar(d, cl[0]) >= cfg.similarity:
                cl.append(d)
                break
        else:
            clusters.append([d])
    into_map: list[_Rule] = [] if dir_map is None else [dir_map]
    for cl in clusters:
        if cl[0].children and (
            len(cl) >= cfg.min_dirs
            or (dir_map is not None and _similar(cl[0], dir_map) >= cfg.similarity)
        ):
            into_map.extend(cl)
        else:
            out.extend(cl)
    if len(into_map) > 1 or (into_map and dir_map is None):
        out.append(_merge(into_map, ("str", ""), cfg))
    elif into_map:
        out.append(into_map[0])
    # 3. Files sharing an extension collapse into {stem}.ext, joining an
    #    existing {stem}.ext map at this position whatever their number.
    file_maps = {r.shape[1]: r for r in out if r.kind == "file" and r.shape[0] == "str"}
    by_suffix: dict[str, list[_Rule]] = defaultdict(list)
    for f in (r for r in lone if r.kind == "file"):
        by_suffix[PurePosixPath(f.names[0]).suffix].append(f)
    for suffix, fs in by_suffix.items():
        existing = file_maps.get(suffix)
        if existing is not None:
            out.remove(existing)
            out.append(_merge([existing, *fs], ("str", suffix), cfg))
        elif len(fs) >= cfg.min_files:
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
    """One inferred path pattern, relative to the inferred root.

    ``count`` and ``fields`` describe the observed paths the layout was
    inferred from. ``optional`` is true when some observed directory matching
    a prefix of ``expr`` contains none of the observed paths ``expr`` matches.
    """

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


def _seen(expr: PathExpr, paths: list[str], names: list[str]) -> dict[str, list[Any]]:
    """Field values from matching observed paths, verifying each round-trips."""
    seen: dict[str, list[Any]] = {n: [] for n in names}
    for observed in paths:
        m = expr.match(observed)
        if m is None:  # pragma: no cover - would be an inference bug
            raise AssertionError(
                f"{observed!r} does not match inferred {expr.pattern!r}"
            )
        for k, v in m.items():
            seen[k].append(v)
    return seen


def _flatten(
    rules: list[_Rule],
    prefix: tuple[Seg, ...],
    parent: str,
    used: set[str],
    stats: list[tuple[str, type, list[Any]]],
    out: list[Layout],
) -> None:
    for r in rules:
        my_used = set(used)
        my_stats = list(stats)
        seg = _segment(r, parent, my_used, my_stats)
        path = (*prefix, seg)
        if r.kind == "file" or not r.children:
            expr = PathExpr(REL, path)
            names = [n for n, _, _ in my_stats]
            seen = _seen(expr, r.paths, names)
            # A field that always repeats an earlier one is the same parameter,
            # as in n01440764/n01440764_10026.JPEG. Three distinct values, or
            # two over four paths, make a coincidence unlikely.
            same: dict[str, str] = {}
            for i, a in enumerate(names):
                distinct = len(set(seen[a]))
                if a in same or distinct < 2 or (distinct == 2 and len(r.paths) < 4):
                    continue
                for b in names[i + 1 :]:
                    if b not in same and seen[a] == seen[b]:
                        same[b] = a
            if same:
                params = expr.params
                expr = expr.bind({b: params[a] for b, a in same.items()})
                my_stats = [st for st in my_stats if st[0] not in same]
                seen = _seen(expr, r.paths, [n for n, _, _ in my_stats])
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
            out.append(Layout(expr, r.kind, len(r.paths), fields, False))
        else:
            label = r.names[0] if r.literal_like() else parent
            _flatten(r.children, path, label, my_used, my_stats, out)


def _step(
    seg: Seg, node: dict[str, Any], env: dict[str, Any]
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Children of ``node`` matching ``seg``, with the extended bindings."""
    lit = seg.literal
    if lit is not None:
        if lit in node:
            yield lit, env
        return
    plan = seg_plan(seg)
    for name in node:
        if plan is not None:
            found = _seg_fast(plan, name, env)
            if found is not None:
                yield name, found
        else:
            for found in _match_seg(seg, name, env):
                yield name, found


# Directories reached by a prefix: (path parts, bindings, subtree).
type _Frontier = list[tuple[tuple[str, ...], dict[str, Any], dict[str, Any]]]


def _mark_optional(layouts: list[Layout], tree: dict[str, Any]) -> None:
    """Flag each layout that some directory matching a prefix of it lacks.

    Each pattern is walked down the observed tree with the segment matcher
    that `match` uses, so the flag holds for every directory a prefix
    matches, including directories inferred under a different layout.
    Layouts share the directories reached by their common prefixes.
    """
    frontiers: dict[tuple[Seg, ...], _Frontier] = {(): [((), {}, tree)]}

    def verified(expr: PathExpr, path: tuple[str, ...], env: dict[str, Any]) -> bool:
        # The segment matcher proposes candidates (``{n:d}`` accepts "00");
        # rendering decides, as in `match`.
        try:
            return expr._compiled.render(env) == "/".join(path)
        except WendError, ValueError:
            return False

    def frontier(prefix: tuple[Seg, ...]) -> _Frontier:
        if prefix not in frontiers:
            expr = PathExpr(REL, prefix)
            out: _Frontier = []
            for at, env, node in frontier(prefix[:-1]):
                for name, found in _step(prefix[-1], node, env):
                    sub = node[name]
                    if sub is not None and verified(expr, (*at, name), found):
                        out.append(((*at, name), found, sub))
            frontiers[prefix] = out
        return frontiers[prefix]

    for lay in layouts:
        parts = tuple(p for p in lay.expr.parts if isinstance(p, Seg))
        assert len(parts) == len(lay.expr.parts)  # inferred layouts have no SubPath
        n = len(parts)
        want_file = lay.kind == "file"
        hits: set[tuple[str, ...]] = set()
        for at, env, node in frontier(parts[:-1]):
            for name, found in _step(parts[-1], node, env):
                sub = node[name]
                if (sub is None) != want_file or (sub and not want_file):
                    continue
                if verified(lay.expr, (*at, name), found):
                    hits.add((*at, name))
        lay.optional = any(
            {at for at, _, _ in frontier(parts[:j])} - {h[:j] for h in hits}
            for j in range(1, n)
        )


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

    def build(children: dict[str, Any], at: str) -> list[_Rule]:
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
            )
            if sub is not None:
                r.children = build(sub, full)
            rules.append(r)
        return _unify(rules, cfg)

    layouts: list[Layout] = []
    _flatten(build(tree, ""), (), "", set(), [], layouts)
    _mark_optional(layouts, tree)
    layouts.sort(key=lambda lay: (-lay.count, lay.expr.pattern))
    return Schema(layouts, len(observed))
