"""Filesystem layout inference: from observed paths to wend expressions.

The analogue of JSON schema inference (genson, polars-genson) for directory
trees. Observed paths form a tree, which is generalised bottom-up:

- Names are tokenised into ASCII digit runs and the text between them, giving
  a *skeleton* (``chunk_#-of-#.parquet``). A name holding exactly one UUID, or
  one hex token of eight or more digits mixing letters and digits, keeps that
  token as one string token, and the text after it stays literal
  (``part-#-<uuid>-c000.snappy.parquet``). Siblings with the same skeleton
  merge; each digit run that varies becomes an ``int`` field whose format spec
  (``04d``, ``d``) is chosen so that every observed value round-trips, and
  runs that never vary stay literal. Names whose runs need different specs are
  split, so a stray ``epoch_7`` among ``epoch_001``... is reported on its own.
- Sibling directories whose contents are structurally similar (Jaccard
  similarity of their children's skeletons) collapse into one segment field,
  like genson's record-to-map unification. Files that share an extension
  collapse into ``{stem}.ext`` once there are ``min_files`` of them, and so
  do empty directories, which have no contents to compare. A map at a
  position absorbs the similar directories, same-extension files and empty
  directories beside it, whatever their number.
- Merging directories re-unifies their children. A field whose observed
  values always equal an earlier field's becomes the same parameter
  (``n01440764/n01440764_10026.JPEG``).

Opaque families. Directories that hold only files, but whose names share no
skeleton (terminfo's ``a/att4410``, ``b/bvt100``...), are compared by the
extensions of their files instead. Like genson-core's map threshold, this
coarser comparison needs many siblings: only a group of at least
``min_opaque`` (8) such directories, joining clusters that did not merge by
skeleton, collapses into a map, so a code repository's handful of top-level
directories stays a record. An empty directory says nothing about extensions:
it neither counts towards ``min_opaque`` nor keeps a family (``0``...``9``
with an empty ``9``) from being opaque. Inside such an *opaque* map, a name
family seen in only one of its directories is treated like a one-off name,
and a ``{name}`` map takes in the files left over: their names carry no
shared structure.

Variable depth. After flattening, a tail ``T`` (one segment, possibly after
literal directory segments such as ``__pycache__``, with some literal text)
that recurs below a prefix ``A`` becomes the layout ``A/{rel...}/T``. Writing
*holders* for the directories that hold an instance of ``T`` directly, the
recursion criterion is:

1. ``T`` occurs directly in ``A`` (depth 0);
2. ``T`` occurs at ``min_depths`` (3) distinct depths below ``A`` counting
   depth 0, each depth other than 0 with at least two observed paths;
3. it branches: at some depth below ``A`` there are two or more holders, so
   ``T`` recurs in sibling directories rather than along one chain;
4. the root looks like what it recurses into: the extensions of the files
   directly in the depth-0 holders and in the deeper holders are alike
   (weighted Jaccard of their frequencies at least ``similarity``).

The layouts it replaces are those extending ``A`` whose every path ends in an
instance of ``T``. Candidates are taken largest first, so the outermost
recursion root wins, and a fold below a field segment (``site-packages/{pkg}``)
takes in the folds of literal directories beside it that its field matches.
A chain of literal directories fails the third condition
(``a/{stem}.txt``, ``a/b/{stem}.txt``, ``a/b/c/{stem}.txt``); a repository
root whose few scripts sit among records (``README.md``, ``pyproject.toml``)
fails the fourth, so its packages fold below it, if at all; and a tail
without literal text (``{name}``) is never a candidate.

Kinds. The observed paths are files and observed directories: the empty
directories of a walk, or the entries ending in "/" of an iterable. Each
layout has one kind and is inferred from paths of that kind only; a
directory merged with others keeps its own observed path apart from the
files below it, as a ``dir`` layout of the merged pattern
(``{dir}/examples`` when some package directories hold an empty
``examples/``). A dir layout generalises like a file layout, through merged
parents, digit runs, maps and SubPath folds, but a file and a directory
never share one, whatever names they share.

Every observed path matches at least one inferred layout of its kind, and
each layout's ``count`` and field statistics come from the paths it was
inferred from, so the counts partition the observed paths of each kind.
``optional`` and ``cardinality`` are properties of the pattern and the kind:
a layout's paths are the observed paths of its kind that it matches; it is
optional when some observed directory matching a proper prefix of it
contains none of them, and *many* when some directory holds more than one of
them directly (every such directory matches the pattern's parent prefix).
Statistics record the values seen without constraining new ones.

Field names follow the text before a run (``epoch_{epoch:03d}``), dates
(``{year:04d}-{month:02d}-{day:02d}``, ``{date:08d}``, a bare four-digit
``{year:04d}`` directory, and times after a date) and token kinds
(``{uuid}``, ``{hex}``); a directory field is named after its parent.
"""

from __future__ import annotations

import enum
import os
import posixpath
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any

from ._expr import REL, Field, P, PathExpr, Seg, Splice, _norm, _pieces_pattern
from ._match import Match, _match_seg, _seg_fast, seg_plan
from ._params import Kind, Param, SubPath
from .errors import AmbiguousMatchError, WendError
from .fs import FileSystem


_RUN = re.compile(r"[0-9]+")  # ASCII only: int() would accept other digits
_WORD = re.compile(r"[A-Za-z]+")
_HEX = re.compile(
    r"(?<![0-9A-Za-z])(?:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}"
    r"|[0-9a-f]{8,}|[0-9A-F]{8,}"
    r")(?![0-9A-Za-z])"
)
_HEXISH = re.compile(r"[0-9a-fA-F]{8}")  # a cheap test before looking for _HEX
_DATE_SEPS = frozenset("-_.")
_TIME_SEPS = frozenset("-_.:")


@dataclass(frozen=True)
class _Config:
    min_dirs: int = 2
    min_files: int = 3
    similarity: float = 0.5
    min_opaque: int = 8
    min_depths: int = 3


def _tokens(name: str) -> tuple[tuple[str, ...], tuple[str, ...], list[str]]:
    """(literal pieces, token kinds, token values) of a name.

    Tokens are maximal ASCII digit runs (kind "d") and, when the name holds
    exactly one, a UUID ("u") or a hex token of eight or more digits with
    both letters and digits ("x"). The text after a hex token stays literal,
    so the string field it becomes is the last field of its segment.
    """
    hexes = (
        [
            m
            for m in _HEX.finditer(name)
            if "-" in m[0] or (any(c.isdigit() for c in m[0]) and not m[0].isdigit())
        ]
        if _HEXISH.search(name)
        else ()
    )
    if len(hexes) == 1:
        m = hexes[0]
        head = name[: m.start()]
        runs = _RUN.findall(head)
        kind = "u" if "-" in m[0] else "x"
        return (
            (*_RUN.split(head), name[m.end() :]),
            ("d",) * len(runs) + (kind,),
            [*runs, m[0]],
        )
    runs = _RUN.findall(name)
    return tuple(_RUN.split(name)), ("d",) * len(runs), runs


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
    kinds = rules[0].shape[2]
    n = len(kinds)
    varying = [
        i
        for i in range(n)
        if kinds[i] == "d" and len({v for r in rules for v in r.runs[i]}) > 1
    ]

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

    ``shape`` is ("num", literal pieces, token kinds) for names containing
    tokens (their observed values are in ``runs``), ("lit", name) for other
    names, or ("str", suffix) for a name generalised into a string field.
    ``opaque`` marks a directory map formed from an opaque family. ``listed``
    holds the paths of the directories that are observed paths themselves
    (an empty directory in a walk, an entry ending in "/" in an iterable):
    merging keeps them apart from the files below, so they become a ``dir``
    layout of the rule's own pattern.
    """

    kind: str
    shape: tuple[Any, ...]
    runs: list[list[str]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    paths: list[str] = field(
        default_factory=list
    )  # observed full paths, parallel to names
    children: list[_Rule] = field(default_factory=list)
    opaque: bool = False
    listed: list[str] = field(default_factory=list)

    def skeleton(self) -> tuple[Any, ...]:
        return (self.kind, self.shape)

    @property
    def count(self) -> int:
        return len(self.names)

    def literal_like(self) -> bool:
        if self.shape[0] == "lit":
            return True
        return self.shape[0] == "num" and all(len(set(v)) == 1 for v in self.runs)


def _merge(
    rules: list[_Rule], shape: tuple[Any, ...], cfg: _Config, opaque: bool = False
) -> _Rule:
    out = _Rule(rules[0].kind, shape, opaque=opaque)
    if shape[0] == "num":
        out.runs = [
            [v for r in rules for v in r.runs[i]] for i in range(len(rules[0].runs))
        ]
    out.names = [n for r in rules for n in r.names]
    out.paths = [p for r in rules for p in r.paths]
    if out.kind == "dir":
        out.listed = [p for r in rules for p in r.listed]
        out.children = _unify([c for r in rules for c in r.children], cfg, opaque)
    return out


def _jaccard(a: set[Any], b: set[Any]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 1.0


def _suffix(name: str) -> str:
    """``PurePosixPath(name).suffix`` for a single name, without the object."""
    return posixpath.splitext(name)[1]


def _coarse(r: _Rule) -> str:
    return _suffix(r.names[0])


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


def _profile(dirs: Iterable[_Rule]) -> dict[str, float] | None:
    """Extension frequencies of the files in directories holding only files.

    An empty directory says nothing about extensions and is passed over;
    there is no profile when some directory holds a directory, or none holds
    a file.
    """
    counts: Counter[str] = Counter()
    for d in dirs:
        if any(c.kind != "file" for c in d.children):
            return None
        for c in d.children:
            counts[_coarse(c)] += c.count
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()} if total else None


def _overlap(a: dict[str, float], b: dict[str, float]) -> float:
    """Weighted Jaccard similarity of two extension profiles."""
    keys = a.keys() | b.keys()
    lo = sum(min(a.get(k, 0.0), b.get(k, 0.0)) for k in keys)
    hi = sum(max(a.get(k, 0.0), b.get(k, 0.0)) for k in keys)
    return lo / hi


def _opaque_families(
    clusters: list[list[_Rule]], dir_map: _Rule | None, cfg: _Config
) -> set[int]:
    """Clusters that join an opaque map: file-only directories alike in extensions.

    Clusters (of directories already alike by skeleton) group by their files'
    extensions; a group of two or more clusters holding ``min_opaque``
    directories in all joins the map. An opaque map already at this position
    takes in every file-only cluster alike in extensions.
    """
    profiles = [_profile(cl) for cl in clusters]
    groups: list[tuple[dict[str, float], list[int]]] = []  # (leader's profile, members)
    for i in sorted(
        range(len(clusters)), key=lambda i: (-len(clusters[i]), clusters[i][0].names[0])
    ):
        prof = profiles[i]
        if prof is None:
            continue
        for lead, members in groups:
            if _overlap(prof, lead) >= cfg.similarity:
                members.append(i)
                break
        else:
            groups.append((prof, [i]))
    out: set[int] = set()
    for _, members in groups:
        if (
            len(members) > 1
            and sum(len(clusters[i]) for i in members) >= cfg.min_opaque
        ):
            out.update(members)
    if dir_map is not None and dir_map.opaque:
        here = _profile([dir_map])
        if here is not None:
            out.update(
                i
                for i, prof in enumerate(profiles)
                if prof is not None and _overlap(prof, here) >= cfg.similarity
            )
    return out


def _opaque_dirs(dirs: list[_Rule], cfg: _Config) -> bool:
    """Same-skeleton directories (``0``...``9``) whose files share no structure.

    At least ``min_opaque`` directories holding only files, some of them
    unlike the others by skeleton: their name only says they are a family.
    Empty members say nothing either way, so only the others are counted
    and compared.
    """
    if len(dirs) < cfg.min_opaque or dirs[0].kind != "dir":
        return False
    full = [d for d in dirs if d.children]
    if len(full) < cfg.min_opaque or _profile(full) is None:
        return False
    lead = min(full, key=lambda d: (-len(d.children), d.names[0]))
    return any(_similar(d, lead) < cfg.similarity for d in full)


def _local_family(r: _Rule) -> bool:
    """A name family of files seen in one directory only."""
    return (
        r.kind == "file"
        and r.shape[0] == "num"
        and len({p.rpartition("/")[0] for p in r.paths}) == 1
    )


def _unify(rules: list[_Rule], cfg: _Config, opaque: bool = False) -> list[_Rule]:
    out: list[_Rule] = []
    lone: list[_Rule] = []
    # 1. Rules with the same skeleton merge (digit runs pool their values),
    #    in groups whose runs share a format spec. In an opaque map, a family
    #    from one directory only counts as a one-off name.
    by_skel: dict[tuple[Any, ...], list[_Rule]] = defaultdict(list)
    for r in rules:
        by_skel[r.skeleton()].append(r)
    for (_kind, shape), ms in by_skel.items():
        for group in _partition(ms):
            merged = (
                _merge(
                    group,
                    shape,
                    cfg,
                    any(r.opaque for r in group) or _opaque_dirs(group, cfg),
                )
                if len(group) > 1
                else group[0]
            )
            if merged.shape == ("lit", ".."):
                out.append(merged)  # a field never binds "..": it stays literal
            elif merged.literal_like() or (opaque and _local_family(merged)):
                lone.append(merged)
            else:
                out.append(merged)
    # 2. Directories with similar contents collapse into one segment field.
    #    A map already at this position (from merged parents) absorbs similar
    #    directories, and every qualifying cluster joins the same map, since
    #    they would all be the same pattern. Empty directories have no
    #    contents to compare: like files sharing an extension, they join the
    #    map at this position whatever their number, or form one of their own
    #    once there are ``min_files`` of them.
    dir_map = next((r for r in out if r.kind == "dir" and r.shape == ("str", "")), None)
    if dir_map is not None:
        out.remove(dir_map)
    empty = [r for r in lone if r.kind == "dir" and not r.children]
    clusters: list[list[_Rule]] = []
    for d in sorted(
        (r for r in lone if r.kind == "dir" and r.children),
        key=lambda r: (-len(r.children), r.names[0]),
    ):
        for cl in clusters:
            if _similar(d, cl[0]) >= cfg.similarity:
                cl.append(d)
                break
        else:
            clusters.append([d])
    joins = [
        len(cl) >= cfg.min_dirs
        or (dir_map is not None and _similar(cl[0], dir_map) >= cfg.similarity)
        for cl in clusters
    ]
    # Opaque families: file-only directories whose names share no skeleton.
    map_opaque = dir_map is not None and dir_map.opaque
    if len(clusters) > 1 or map_opaque:
        coarse = _opaque_families(clusters, dir_map, cfg)
        for i in coarse:
            joins[i] = True
        map_opaque = map_opaque or bool(coarse)
    into_map: list[_Rule] = [] if dir_map is None else [dir_map]
    for cl, joined in zip(clusters, joins, strict=True):
        (into_map if joined else out).extend(cl)
    here = _profile(into_map) if map_opaque else None
    if here is not None:
        # An opaque map takes in the opaque families of directories beside it
        # that are alike in extensions (terminfo's digits beside its letters).
        for r in [r for r in out if r.kind == "dir" and r.opaque]:
            prof = _profile([r])
            if prof is not None and _overlap(prof, here) >= cfg.similarity:
                out.remove(r)
                into_map.append(r)
    if into_map or len({n for r in empty for n in r.names}) >= cfg.min_files:
        into_map.extend(empty)
    else:
        out.extend(empty)
    if len(into_map) > 1 or (into_map and dir_map is None):
        out.append(_merge(into_map, ("str", ""), cfg, map_opaque))
    elif into_map:
        out.append(into_map[0])
    # 3. Files sharing an extension collapse into {stem}.ext, joining an
    #    existing {stem}.ext map at this position whatever their number. In an
    #    opaque map, a {name} map takes in the files left over.
    file_maps = {r.shape[1]: r for r in out if r.kind == "file" and r.shape[0] == "str"}
    by_suffix: dict[str, list[_Rule]] = defaultdict(list)
    rest: list[_Rule] = []
    for f in (r for r in lone if r.kind == "file"):
        if f.literal_like():
            by_suffix[_coarse(f)].append(f)
            continue
        # A family taken in by an opaque map: by its extension if it has one.
        suffixes = {_suffix(n) for n in f.names}
        (by_suffix[suffixes.pop()] if len(suffixes) == 1 else rest).append(f)
    for suffix, fs in by_suffix.items():
        existing = file_maps.get(suffix)
        if existing is not None:
            out.remove(existing)
            file_maps[suffix] = merged = _merge([existing, *fs], ("str", suffix), cfg)
            out.append(merged)
        elif len({n for f in fs for n in f.names}) >= cfg.min_files:
            file_maps[suffix] = merged = _merge(fs, ("str", suffix), cfg)
            out.append(merged)
        else:
            rest.extend(fs)
    anything = file_maps.get("") if opaque else None
    if anything is not None and rest:
        out.remove(anything)
        out.append(_merge([anything, *rest], ("str", ""), cfg))
    else:
        out.extend(rest)
    return sorted(out, key=lambda r: (r.kind, repr(r.shape), r.names[0]))


class Cardinality(enum.Enum):
    """How many of a layout's paths a directory matching its parent holds.

    Defined on the pattern, over the observed directories: the lower bound is
    zero when the layout is `optional` (some directory matching a proper
    prefix of the pattern contains none of its paths), and the upper bound is
    more than one when some directory holds two or more of its paths
    directly. Values are UML multiplicities.
    """

    ONE = "1"
    OPTIONAL = "0..1"
    AT_LEAST_ONE = "1..*"
    MANY = "0..*"


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


def _stats(name: str, typ: type, values: list[Any]) -> FieldStats:
    return FieldStats(
        name,
        typ,
        len(values),
        len(set(values)),
        min(values) if typ is int else None,
        max(values) if typ is int else None,
        tuple(sorted(set(values), key=str)[:5]),
    )


@dataclass
class Layout:
    """One inferred path pattern, relative to the inferred root.

    ``kind`` is "file" or "dir", and ``count`` and ``fields`` describe the
    observed paths of that kind the layout was inferred from. ``optional`` is
    true when some observed directory matching a proper prefix of ``expr``
    contains none of the observed paths of its kind that ``expr`` matches;
    ``many`` is true when some observed directory holds more than one of them
    directly. ``cardinality`` combines the two.
    """

    expr: PathExpr
    kind: str
    count: int
    fields: dict[str, FieldStats]
    optional: bool
    many: bool = False

    @property
    def cardinality(self) -> Cardinality:
        if self.many:
            return Cardinality.MANY if self.optional else Cardinality.AT_LEAST_ONE
        return Cardinality.OPTIONAL if self.optional else Cardinality.ONE

    def __repr__(self) -> str:
        return (
            f"Layout({self.expr.pattern!r}, {self.kind}, {self.count} paths, "
            f"{self.cardinality.value})"
        )

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
        return Layout(
            self.expr.bind(env), self.kind, self.count, fields, self.optional, self.many
        )


@dataclass
class Schema:
    """The result of `infer`: layouts that together cover every observed path.

    Each observed path is covered by a layout of its own kind: a file by a
    ``file`` layout, an observed directory by a ``dir`` layout. ``total``
    counts the distinct observed paths, which the layouts' counts partition.
    """

    layouts: list[Layout]
    total: int

    def __repr__(self) -> str:
        lines = [f"Schema({self.total} paths, {len(self.layouts)} layouts)"]
        for lay in self.layouts:
            card = lay.cardinality.value
            lines.append(
                f"  {lay.count:>6}  {lay.kind:<4} {card:<4}  {lay.expr.pattern}"
            )
        return "\n".join(lines)

    def match(self, path: Any, kind: str | None = None) -> list[tuple[Layout, Match]]:
        """Every layout of ``kind`` that matches ``path``, with its bindings.

        ``kind`` is "file", "dir" or None. Without it, a string ending in "/"
        is a directory, as in `infer`, and any other path matches layouts of
        either kind.
        """
        if kind is None:
            kind = _kind_of(path)
        elif kind not in ("file", "dir"):
            raise ValueError("kind must be None, 'file' or 'dir'")
        out = []
        for lay in self.layouts:
            if kind is not None and lay.kind != kind:
                continue
            m = lay.match(path)
            if m is not None:
                out.append((lay, m))
        return out

    def check(self, paths: Iterable[Any]) -> list[str]:
        """Paths that no layout of their kind matches (empty when all are covered).

        Each entry is a path or a ``(path, is_dir)`` pair. A string ending in
        "/" is a directory, as in `infer`; any other path is checked against
        layouts of either kind.
        """
        out = []
        for entry in paths:
            if isinstance(entry, tuple):
                path, is_dir = entry
                kind = "dir" if is_dir else "file"
            else:
                path, kind = entry, None
            if not self.match(path, kind):
                out.append(str(path))
        return out


def _kind_of(path: Any) -> str | None:
    """The kind a path carries: a string ending in "/" is a directory."""
    return "dir" if isinstance(path, str) and path.endswith("/") else None


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


def _token_names(
    pieces: tuple[str, ...], kinds: tuple[str, ...], runs: list[list[str]]
) -> list[str]:
    """Base names for a name's tokens: the word before a run, dates, token kinds."""
    names = []
    for i, k in enumerate(kinds):
        if k != "d":
            names.append("uuid" if k == "u" else "hex")
            continue
        words = _WORD.findall(pieces[i])
        names.append(_ident(words[-1]) if words else "")

    def num(i: int, lo: int, hi: int, widths: tuple[int, ...]) -> bool:
        return (
            i < len(kinds)
            and kinds[i] == "d"
            and all(len(v) in widths and lo <= int(v) <= hi for v in runs[i])
        )

    def sep(i: int, allowed: frozenset[str]) -> bool:
        return len(pieces[i]) == 1 and pieces[i] in allowed

    i = 0
    while i < len(kinds):
        if (
            num(i, 1900, 2100, (4,))
            and sep(i + 1, _DATE_SEPS)
            and num(i + 1, 1, 12, (1, 2))
        ):
            names[i], names[i + 1] = "year", "month"
            j = i + 2
            if pieces[j] == pieces[i + 1] and num(j, 1, 31, (1, 2)):
                names[j] = "day"
                j += 1
                if (
                    num(j, 0, 23, (2,))
                    and pieces[j] in ("T", "_", "-", ".", " ")
                    and sep(j + 1, _TIME_SEPS)
                    and num(j + 1, 0, 59, (2,))
                ):
                    names[j], names[j + 1] = "hour", "minute"
                    j += 2
                    if pieces[j] == pieces[j - 1] and num(j, 0, 60, (2,)):
                        names[j] = "second"
                        j += 1
            i = j
            continue
        if not names[i] and num(i, 1900, 2100, (4,)):
            names[i] = "year"
        elif num(i, 19000101, 21001231, (8,)) and all(
            1 <= int(v[4:6]) <= 12 and 1 <= int(v[6:]) <= 31 for v in runs[i]
        ):
            names[i] = "date"
        i += 1
    return names


def _segment(
    r: _Rule, parent: str, used: set[str], stats: list[tuple[str, type, list[Any]]]
) -> Seg:
    kind, arg = r.shape[0], r.shape[1]
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
    kinds = r.shape[2]
    base = _token_names(arg, kinds, r.runs)
    pieces: list[Any] = []
    for i, lit in enumerate(arg):
        pieces.append(lit)
        if i == len(kinds):
            break
        vals = r.runs[i]
        if len(set(vals)) == 1:
            pieces.append(vals[0])
            continue
        name = _unique(base[i], used)
        spec = _int_spec(vals) if kinds[i] == "d" else None
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


# A layout with the observed paths it was inferred from.
type _Item = tuple[Layout, list[str]]


def _flatten(
    rules: list[_Rule],
    prefix: tuple[Seg, ...],
    parent: str,
    used: set[str],
    stats: list[tuple[str, type, list[Any]]],
    out: list[_Item],
) -> None:
    for r in rules:
        my_used = set(used)
        my_stats = list(stats)
        seg = _segment(r, parent, my_used, my_stats)
        path = (*prefix, seg)
        if r.kind == "file":
            out.append(_leaf(path, "file", r.paths, my_stats))
            continue
        # A directory rule gives a dir layout for its observed directories
        # (all of them when it has no children), and its children give the
        # layouts below it: a file and a directory never share a layout.
        if r.listed:
            out.append(_leaf(path, "dir", r.listed, my_stats))
        if r.children:
            label = r.names[0] if r.literal_like() else parent
            _flatten(r.children, path, label, my_used, my_stats, out)


def _leaf(
    segs: tuple[Seg, ...],
    kind: str,
    paths: list[str],
    stats: list[tuple[str, type, list[Any]]],
) -> _Item:
    """The layout of observed ``paths`` of one kind, all matching ``segs``."""
    expr = PathExpr(REL, segs)
    names = [n for n, _, _ in stats]
    seen = _seen(expr, paths, names)
    # A field that always repeats an earlier one is the same parameter, as in
    # n01440764/n01440764_10026.JPEG. Three distinct values, or two over four
    # paths, make a coincidence unlikely.
    same: dict[str, str] = {}
    for i, a in enumerate(names):
        distinct = len(set(seen[a]))
        if a in same or distinct < 2 or (distinct == 2 and len(paths) < 4):
            continue
        for b in names[i + 1 :]:
            if b not in same and seen[a] == seen[b]:
                same[b] = a
    if same:
        params = expr.params
        expr = expr.bind({b: params[a] for b, a in same.items()})
        stats = [st for st in stats if st[0] not in same]
        seen = _seen(expr, paths, [n for n, _, _ in stats])
    fields = {n: _stats(n, t, seen[n]) for n, t, _ in stats}
    return Layout(expr, kind, len(paths), fields, False), paths


def _shape_key(segs: tuple[Seg, ...]) -> tuple[str, ...]:
    """Segment patterns with parameters numbered by first appearance."""
    index: dict[str, int] = {}
    out = []
    for seg in segs:
        text = []
        for p in seg.pieces:
            if isinstance(p, str):
                text.append(p.replace("{", "{{").replace("}", "}}"))
                continue
            src = p.source
            assert isinstance(src, Param)
            k = index.setdefault(src.name, len(index))
            tname = getattr(src.type, "__name__", None)
            text.append(
                f"{{{k}!{p.conversion}:{''.join(map(str, p.spec))}|{p.role}|{tname}}}"
            )
        out.append("".join(text))
    return tuple(out)


def _fold_subpaths(
    items: list[_Item], tree: dict[str, Any], cfg: _Config
) -> list[_Item]:
    """Replace the layouts of a recursive tail with one ``A/{rel...}/T`` layout.

    See the module docstring for the criterion. Each candidate (A, T) comes
    from a layout of at least two paths that ends in T below A; the layouts
    it replaces extend A and end, path by path, in an instance of T.
    """
    # Flattened layouts hold segments only.
    segs = [tuple(p for p in lay.expr.parts if isinstance(p, Seg)) for lay, _ in items]
    pats = [tuple(_pieces_pattern(s.pieces) for s in ss) for ss in segs]
    cands: dict[tuple[Any, ...], tuple[tuple[Seg, ...], tuple[Seg, ...]]] = {}
    for idx, (lay, _) in enumerate(items):
        parts = segs[idx]
        n = len(parts)
        if lay.count < 2:
            continue
        for t in range(1, n):
            if t > 1 and parts[n - t].literal is None:
                break  # only literal directories may precede the tail's last segment
            tail = parts[n - t :]
            if t == 1 and not any(isinstance(p, str) for p in tail[0].pieces):
                continue  # a tail without literal text says nothing
            tk = (lay.kind, _shape_key(tail))
            for a in range(n - t):
                cands.setdefault((pats[idx][:a], tk), (parts[:a], tail))
    if not cands:
        return items
    tails: dict[Any, tuple[tuple[Seg, ...], PathExpr]] = {}
    for (_, tk), (_, tail) in cands.items():
        if tk not in tails:
            tails[tk] = tail, PathExpr(REL, tail)
    keys: dict[tuple[int, int], tuple[str, ...]] = {}
    last = [paths[0].rpartition("/")[2] for _, paths in items]

    def ends_in(tk: Any, idx: int) -> bool:
        """Every path of layout ``idx`` ends in an instance of tail ``tk``."""
        tail, expr = tails[tk]
        t = len(tail)
        if (idx, t) not in keys:
            keys[idx, t] = _shape_key(segs[idx][-t:])
        if keys[idx, t] == tk[1]:
            return True
        # Literal text first: the end of the last name, then the rest.
        end = tail[-1].pieces[-1]
        return (
            (not isinstance(end, str) or last[idx].endswith(end))
            and _plausible(tail, items[idx][1][0])
            and all(_matches(expr, "/".join(p.split("/")[-t:])) for p in items[idx][1])
        )

    ends: dict[Any, list[int]] = {}

    def ending(tk: Any) -> list[int]:
        """The layouts whose paths all end in tail ``tk``."""
        if tk not in ends:
            t = len(tails[tk][0])
            ends[tk] = [
                idx
                for idx, (lay, _) in enumerate(items)
                if lay.kind == tk[0] and len(segs[idx]) >= t and ends_in(tk, idx)
            ]
        return ends[tk]

    held: dict[tuple[int, int], set[str]] = {}

    def holders_of(idx: int, t: int) -> set[str]:
        """Directories holding the tail in layout ``idx``'s paths."""
        if (idx, t) not in held:
            held[idx, t] = {
                p.rsplit("/", t)[0] if p.count("/") >= t else "" for p in items[idx][1]
            }
        return held[idx, t]

    profiles: dict[str, Counter[str]] = {}

    def files_in(d: str) -> Counter[str]:
        """Extensions of the files directly in observed directory ``d``."""
        if d not in profiles:
            node = tree
            for name in d.split("/") if d else ():
                node = node[name]
            profiles[d] = Counter(
                _suffix(name) for name, sub in node.items() if sub is None
            )
        return profiles[d]

    def evaluate(akey: Any, tk: Any, a: int, taken: set[int]) -> list[int] | None:
        t = len(tails[tk][0])
        absorbed: list[int] = []
        depths: Counter[int] = Counter()
        holders: dict[int, set[str]] = defaultdict(set)  # directories holding T
        for idx in ending(tk):
            if idx in taken or len(segs[idx]) < a + t or pats[idx][:a] != akey:
                continue
            d = len(segs[idx]) - a - t
            if any(s.literal == ".." for s in segs[idx][a : a + d]):
                continue  # a SubPath never binds "..": keep such paths literal
            absorbed.append(idx)
            depths[d] += items[idx][0].count
            holders[d] |= holders_of(idx, t)
        supported = {d for d, c in depths.items() if c >= 2} | {0}
        if not depths[0] or len(supported) < cfg.min_depths:
            return None
        # Branching: T recurs in sibling directories, not along one chain.
        if not any(len(ds) > 1 for d, ds in holders.items() if d):
            return None
        # The root of the recursion looks like the directories it recurses
        # into: their files' extensions are alike.
        top: Counter[str] = Counter()
        below: Counter[str] = Counter()
        for d, ds in holders.items():
            for h in ds:
                (below if d else top).update(files_in(h))
        if not top or not below:
            return None
        n_top, n_below = sum(top.values()), sum(below.values())
        share = _overlap(
            {k: v / n_top for k, v in top.items()},
            {k: v / n_below for k, v in below.items()},
        )
        return absorbed if share >= cfg.similarity else None

    ranked = []
    for (akey, tk), (A, _) in cands.items():
        absorbed = evaluate(akey, tk, len(A), set())
        if absorbed is not None:
            size = sum(items[i][0].count for i in absorbed)
            ranked.append((-size, len(A), akey, tk))
    ranked.sort()
    taken: set[int] = set()
    # Accepted folds: [prefix A, tail T, tail key, absorbed layouts].
    accepted: list[tuple[tuple[Seg, ...], tuple[Seg, ...], Any, list[int]]] = []
    for _, a, akey, tk in ranked:
        absorbed = evaluate(akey, tk, a, taken)
        if absorbed is None:
            continue
        taken.update(absorbed)
        A, tail = cands[(akey, tk)]
        accepted.append((A, tail, tk, absorbed))
    # As a map absorbs similar siblings, a fold below a field segment
    # (site-packages/{pkg}/{rel...}/T) takes in the folds of the literal
    # directories beside it with the same tail, when its field matches them.
    hosts: list[tuple[tuple[Seg, ...], tuple[Seg, ...], Any, list[int]]] = []
    for fold in sorted(
        accepted, key=lambda f: bool(f[0]) and f[0][-1].literal is not None
    ):
        A, _, tk, absorbed = fold
        for h in hosts:
            if not (
                h[2] == tk
                and len(h[0]) == len(A)
                and h[0][:-1] == A[:-1]
                and h[0][-1].literal is None
            ):
                continue
            head = PathExpr(REL, h[0])
            if all(
                _matches(head, "/".join(p.split("/")[: len(A)]))
                for i in absorbed
                for p in items[i][1]
            ):
                h[3].extend(absorbed)
                break
        else:
            hosts.append(fold)
    folded = [
        _folded(A, tail, tk[0], [items[i] for i in absorbed])
        for A, tail, tk, absorbed in hosts
    ]
    return [it for i, it in enumerate(items) if i not in taken] + folded


def _plausible(tail: tuple[Seg, ...], path: str) -> bool:
    """A quick test on literal text before matching ``path``'s end against ``tail``."""
    names = path.split("/")
    if len(names) < len(tail):
        return False
    for part, name in zip(reversed(tail), reversed(names), strict=False):
        pieces = part.pieces
        if isinstance(pieces[0], str) and not name.startswith(pieces[0]):
            return False
        if isinstance(pieces[-1], str) and not name.endswith(pieces[-1]):
            return False
    return True


def _matches(expr: PathExpr, path: str) -> bool:
    try:
        return expr.match(path) is not None
    except AmbiguousMatchError:
        return False


def _folded(
    prefix: tuple[Seg, ...], tail: tuple[Seg, ...], kind: str, members: list[_Item]
) -> _Item:
    used = {n for s in prefix for n in s.param_names}
    rel = _unique("rel", used)
    end = PathExpr(REL, tail)
    renames = {}
    for p in end.params.values():
        new = _unique(p.name, used)
        if new != p.name:
            renames[p.name] = Param(new, p.kind, p.type, p.choices)
    if renames:
        end = end.bind(renames)
    expr = PathExpr(REL, (*prefix, Splice(SubPath(rel)), *end.parts))
    paths = [p for _, ps in members for p in ps]
    params = expr.params
    seen: dict[str, list[Any]] = {n: [] for n in params}
    # The prefix and the tail have fixed lengths and no parameter in common,
    # so each is matched on its own (with its fast plan) and the splice takes
    # what lies between; rendering verifies the whole, as `match` would.
    head, a, t = PathExpr(REL, prefix), len(prefix), len(end.parts)
    render = expr._compiled.render
    for path in paths:
        names = path.split("/")
        env: dict[str, Any] = {rel: "/".join(names[a : len(names) - t]) or "."}
        for part, sub in ((head, names[:a]), (end, names[len(names) - t :])):
            m = part.match("/".join(sub)) if sub else {}
            if m is None:  # pragma: no cover - would be an inference bug
                raise AssertionError(f"{path!r} does not match {expr.pattern!r}")
            env.update(m)
        if render(env) != path:  # pragma: no cover - would be an inference bug
            raise AssertionError(f"{path!r} does not match {expr.pattern!r}")
        for k, v in env.items():
            seen[k].append(v)
    fields = {
        n: _stats(n, int if p.type is int else str, seen[n]) for n, p in params.items()
    }
    return Layout(expr, kind, len(paths), fields, False), paths


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


def _below(
    node: dict[str, Any], at: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    """``node`` and every directory below it, with their relative parts."""
    yield at, node
    for name, sub in node.items():
        if sub is not None:
            yield from _below(sub, (*at, name))


# Directories reached by a prefix: (path parts, bindings, subtree).
type _Frontier = list[tuple[tuple[str, ...], dict[str, Any], dict[str, Any]]]


def _mark_cardinality(
    layouts: list[Layout], tree: dict[str, Any], listed: set[str]
) -> None:
    """Set each layout's ``optional`` and ``many`` flags from its pattern.

    Each pattern is walked down the observed tree with the segment matcher
    that `match` uses (a ``SubPath`` reaches a directory and every directory
    below it), so the flags hold for every directory a prefix matches,
    including directories inferred under a different layout. Layouts share
    the directories reached by their common prefixes. A layout's paths are
    the observed paths of its kind that it matches: files, or the observed
    directories in ``listed``.
    """
    frontiers: dict[tuple[Any, ...], _Frontier] = {(): [((), {}, tree)]}

    def verified(expr: PathExpr, path: tuple[str, ...], env: dict[str, Any]) -> bool:
        # The segment matcher proposes candidates (``{n:d}`` accepts "00");
        # rendering decides, as in `match`.
        try:
            return expr._compiled.render(env) == ("/".join(path) or ".")
        except WendError, ValueError:
            return False

    def frontier(prefix: tuple[Any, ...]) -> _Frontier:
        if prefix not in frontiers:
            expr = PathExpr(REL, prefix)
            last = prefix[-1]
            out: _Frontier = []
            for at, env, node in frontier(prefix[:-1]):
                if isinstance(last, Splice):
                    name = last.param.name
                    for rel, sub in _below(node, ()):
                        found = {**env, name: "/".join(rel) or "."}
                        if verified(expr, (*at, *rel), found):
                            out.append(((*at, *rel), found, sub))
                    continue
                for name, found in _step(last, node, env):
                    sub = node[name]
                    if sub is not None and verified(expr, (*at, name), found):
                        out.append(((*at, name), found, sub))
            frontiers[prefix] = out
        return frontiers[prefix]

    for lay in layouts:
        parts = lay.expr.parts
        last = parts[-1]
        assert isinstance(last, Seg)  # inferred layouts end in a segment
        want_file = lay.kind == "file"
        hits: set[tuple[str, ...]] = set()
        for at, env, node in frontier(parts[:-1]):
            for name, found in _step(last, node, env):
                if (node[name] is None) != want_file or not (
                    want_file or "/".join((*at, name)) in listed
                ):
                    continue
                if verified(lay.expr, (*at, name), found):
                    hits.add((*at, name))
        holders = {h[:i] for h in hits for i in range(len(h))}
        lay.optional = any(
            at not in holders
            for j in range(1, len(parts))
            for at, _, _ in frontier(parts[:j])
        )
        lay.many = any(c > 1 for c in Counter(h[:-1] for h in hits).values())


def _observe(
    source: Any, include_hidden: bool, fs: FileSystem | None = None
) -> list[tuple[str, bool]]:
    if isinstance(source, (str, os.PathLike)):
        root = os.fspath(source)
        if fs is not None:
            fs = fs.subtree(root)  # one view for the walk: one listing on a store
        if not (os.path.isdir(root) if fs is None else fs.kind(root) == "dir"):
            raise NotADirectoryError(f"{root!r} is not a directory")
        found: list[tuple[str, bool]] = []
        for dp, dns, fns in os.walk(root) if fs is None else fs.walk(root):
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
    if fs is not None:
        raise TypeError("infer(source, fs=...) takes a directory path, not paths")
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
    fs: FileSystem | None = None,
) -> Schema:
    """Infer layouts from a directory (walked) or an iterable of relative paths.

    The observed paths are the files and, in a walk, the empty directories.
    In an iterable, a trailing "/" marks a directory, which is an observed
    path of kind ``dir`` whether or not other paths lie below it; repeated
    paths count once. ``min_dirs`` and ``min_files`` are how many similar
    siblings it takes to generalise a name into a field (``min_files`` also
    counts empty directories, which have no contents to compare);
    ``similarity`` is the Jaccard threshold on directory contents. Hidden
    entries are skipped unless ``include_hidden``.

    With ``fs`` (a `wend.fs.FileSystem`), ``source`` is a directory in that
    filesystem, such as the path `wend.fs.url_to_fs` gives for a bucket.
    An object store has empty directories only as explicit markers.
    """
    cfg = _Config(min_dirs, min_files, similarity)
    tree: dict[str, Any] = {}
    listed: set[str] = set()  # observed directories
    files = 0
    for path, is_dir in _observe(source, include_hidden, fs):
        parts = [x for x in PurePosixPath(path).parts if x != "/"]
        if not parts:
            continue  # the root itself
        node = tree
        for i, name in enumerate(parts):
            if i == len(parts) - 1 and not is_dir:
                if isinstance(node.get(name), dict):
                    raise ValueError(f"{path!r} is listed as a file and as a directory")
                files += name not in node
                node[name] = None
            else:
                if name in node and node[name] is None:
                    raise ValueError(
                        f"{'/'.join(parts[: i + 1])!r} is listed as a file and as a directory"
                    )
                node = node.setdefault(name, {})
        if is_dir:
            listed.add("/".join(parts))

    def build(children: dict[str, Any], at: str) -> list[_Rule]:
        rules = []
        for name, sub in children.items():
            full = f"{at}/{name}" if at else name
            pieces, kinds, runs = _tokens(name)
            shape = ("num", pieces, kinds) if kinds else ("lit", name)
            r = _Rule(
                "file" if sub is None else "dir",
                shape,
                [[v] for v in runs],
                [name],
                [full],
            )
            if sub is not None:
                r.children = build(sub, full)
                if full in listed:
                    r.listed = [full]
            rules.append(r)
        return _unify(rules, cfg)

    items: list[_Item] = []
    _flatten(build(tree, ""), (), "", set(), [], items)
    items = _fold_subpaths(items, tree, cfg)
    # Each layout's paths are observed paths of its kind (they come from rules
    # of that kind, and `_leaf` and `_folded` verify that they match), and the
    # counts per kind partition the observed paths of that kind.
    counted: Counter[str] = Counter()
    for lay, paths in items:
        counted[lay.kind] += len(paths)
    if counted != Counter(file=files, dir=len(listed)):  # pragma: no cover
        raise AssertionError(
            f"inferred layouts count {dict(counted)} observed paths, "
            f"not {files} files and {len(listed)} directories"
        )
    layouts = [lay for lay, _ in items]
    _mark_cardinality(layouts, tree, listed)
    layouts.sort(key=lambda lay: (-lay.count, lay.expr.pattern, lay.kind))
    return Schema(layouts, files + len(listed))
