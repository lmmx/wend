"""An exact decision procedure for ``relate(a, b, shared=False)`` on a fragment.

It shares nothing with ``wend._relate`` or ``wend._overlap``: it reads an
expression's structure and mirrors the interpreter (``wend._expr``'s
``_render_expr`` and the value checks it calls), which is the reference
semantics. Each expression denotes the set of paths it renders over all
bindings, kept as a nondeterministic finite automaton over a path's parts:

    an anchor token, then each segment's characters followed by "/"

so ``/a/b`` is ``S a / b /`` and ``.`` is ``R``. Under independent bindings
the two sides' sets are independent, so ``same`` is possible exactly where the
automata intersect, ``inside`` where ``a``'s meets ``b``'s followed by one
segment or more, and ``always`` where every pair relates.

Every edge also records which parameter emitted its character, including
the characters an operation consumes and drops (``with_suffix`` drops the old
suffix). So every relation the oracle finds possible comes with bindings
(`Answer.examples`), which wend renders to confirm it.

The fragment, with ``builtin_values=False``:

- **Names used twice.** Rendering is a function of structure (SEMANTICS
  §15.3, 1): two uses of a name render one text where they render it the
  same way, its *shape* (as a path or segment, or formatted with one
  conversion and spec). That set is not regular in general (``{p}/{p}``), so
  `language` refuses it; `relate_independent` reads the uses apart and then
  holds them to each text a use can take, and says ``"undecided"`` where
  that does not settle it.
- **Values are any objects.** A value's ``__format__`` may return any text,
  and an object may compare equal to a choice, so neither a spec nor
  ``choices`` narrows a field's text beyond what rendering enforces: no
  separator, no NUL, and a spec's facts (dot-free, non-empty). A declared
  ``type`` of ``bool`` admits two values, formatted exactly; another type may
  be subclassed, so it narrows nothing.
- **Operations.** ``parent``, ``with_name``, ``with_suffix``, ``with_stem``,
  ``relative_to`` and ``join``, as pathlib 3.14 defines them.
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from wend._expr import (
    REL,
    Const,
    Deferred,
    Field,
    HeadParam,
    PathExpr,
    Root,
    Seg,
    Text,
    _new,
    _Rel,
    format_field,
)
from wend._params import Kind, Param


class Unsupported(Exception):
    """The expression is outside the fragment the oracle decides."""


# -- labels --------------------------------------------------------------------


@dataclass(frozen=True)
class Chars:
    """A set of characters: ``chars`` itself, or all but ``chars``."""

    chars: frozenset[str]
    co: bool = False

    def __and__(self, o: Chars) -> Chars:
        if not self.co and not o.co:
            return Chars(self.chars & o.chars)
        if self.co and o.co:
            return Chars(self.chars | o.chars, True)
        pos, neg = (self, o) if not self.co else (o, self)
        return Chars(pos.chars - neg.chars)

    def __bool__(self) -> bool:
        return self.co or bool(self.chars)

    def pick(self) -> str:
        if not self.co:
            return min(self.chars)
        for c in "axbyc0123456789-_":
            if c not in self.chars:
                return c
        return next(chr(i) for i in itertools.count(0x100) if chr(i) not in self.chars)


def chars(s: str) -> Chars:
    return Chars(frozenset(s))


def but(s: str) -> Chars:
    return Chars(frozenset(s), True)


@dataclass(frozen=True)
class Tok:
    """An anchor: relative ``R``, ``/`` as ``S``, ``//`` as ``D``."""

    name: str


ANCHORS = {"": Tok("R"), "/": Tok("S"), "//": Tok("D")}
ANCHOR_TEXT = {"R": "", "S": "/", "D": "//"}
SEP = chars("/")
SEGCHAR = but("/\x00")  # a character a segment may hold
DOT = chars(".")
NONDOT = but("/\x00.")

Label = Chars | Tok


def meet(x: Label, y: Label) -> Label | None:
    if isinstance(x, Tok) or isinstance(y, Tok):
        return x if x == y else None
    z = x & y
    return z if z else None


def pick(lab: Label) -> str:
    return ANCHOR_TEXT[lab.name] if isinstance(lab, Tok) else lab.pick()


# -- automata ------------------------------------------------------------------

# An effect says a parameter (by key) emitted a character: the edge's own,
# when its label is None, or one of its label, for an edge whose character
# the path does not keep. ("value", v) records a value chosen outright.
Effect = tuple[Any, Any]
Edge = tuple[Label | None, int, tuple[Effect, ...]]


@dataclass
class NFA:
    """States 0..n-1; ``edges[s]`` holds (label or None, target, effects)."""

    edges: list[list[Edge]] = field(default_factory=list)
    start: int = 0
    finals: set[int] = field(default_factory=set)

    def new(self) -> int:
        self.edges.append([])
        return len(self.edges) - 1

    def add(
        self, s: int, label: Label | None, t: int, fx: tuple[Effect, ...] = ()
    ) -> None:
        self.edges[s].append((label, t, fx))

    def embed(self, other: NFA) -> tuple[int, set[int]]:
        """Copy ``other`` in; its start and finals here."""
        off = len(self.edges)
        for es in other.edges:
            self.edges.append([(lab, t + off, fx) for lab, t, fx in es])
        return other.start + off, {f + off for f in other.finals}

    def closure(self, states: Iterable[int]) -> set[int]:
        seen = set(states)
        todo = list(seen)
        while todo:
            s = todo.pop()
            for lab, t, _ in self.edges[s]:
                if lab is None and t not in seen:
                    seen.add(t)
                    todo.append(t)
        return seen


def compact(n: NFA) -> NFA:
    """``n`` without epsilon edges that record nothing, and without states
    that are unreachable or reach no final state. The language and every
    accepted word's effects are unchanged."""

    def quiet_closure(s: int) -> list[int]:
        seen, todo = {s}, [s]
        while todo:
            x = todo.pop()
            for lab, t, fx in n.edges[x]:
                if lab is None and not fx and t not in seen:
                    seen.add(t)
                    todo.append(t)
        return sorted(seen)

    edges: list[list[Edge]] = []
    finals = set()
    for s in range(len(n.edges)):
        out: dict[tuple[Any, int, Any], Edge] = {}
        for x in quiet_closure(s):
            if x in n.finals:
                finals.add(s)
            for lab, t, fx in n.edges[x]:
                if lab is None and not fx:
                    continue
                out[(lab, t, fx)] = (lab, t, fx)
        edges.append(list(out.values()))
    # trim
    reach, todo = {n.start}, [n.start]
    while todo:
        x = todo.pop()
        for _, t, _ in edges[x]:
            if t not in reach:
                reach.add(t)
                todo.append(t)
    back: dict[int, list[int]] = {}
    for x in reach:
        for _, t, _ in edges[x]:
            back.setdefault(t, []).append(x)
    live = {f for f in finals if f in reach}
    todo = list(live)
    while todo:
        t = todo.pop()
        for x in back.get(t, []):
            if x not in live:
                live.add(x)
                todo.append(x)
    keep = sorted(live | {n.start})
    index = {x: i for i, x in enumerate(keep)}
    out_n = NFA(start=index[n.start], finals={index[f] for f in finals if f in index})
    for x in keep:
        out_n.edges.append(
            [(lab, index[t], fx) for lab, t, fx in edges[x] if t in index]
        )
    return out_n


def word(labels: Iterable[Label]) -> NFA:
    n = NFA()
    s = n.new()
    n.start = s
    for lab in labels:
        t = n.new()
        n.add(s, lab, t)
        s = t
    n.finals = {s}
    return n


def text(s: str) -> NFA:
    return word(chars(c) for c in s)


def empty() -> NFA:
    n = NFA()
    n.start = n.new()
    return n


def union(*ns: NFA) -> NFA:
    out = NFA()
    out.start = out.new()
    for n in ns:
        s, fs = out.embed(n)
        out.add(out.start, None, s)
        out.finals |= fs
    return out


def concat(*ns: NFA) -> NFA:
    out = NFA()
    out.start = out.new()
    ends = {out.start}
    for n in ns:
        s, fs = out.embed(n)
        for e in ends:
            out.add(e, None, s)
        ends = fs
    out.finals = set(ends)
    return out


def star(n: NFA) -> NFA:
    out = NFA()
    out.start = out.new()
    s, fs = out.embed(n)
    out.add(out.start, None, s)
    for f in fs:
        out.add(f, None, out.start)
    out.finals = {out.start}
    return out


def plus(n: NFA) -> NFA:
    return concat(n, star(n))


def tag(n: NFA, key: Any) -> NFA:
    """``n`` with every character it reads emitted by ``key``."""
    out = NFA(start=n.start, finals=set(n.finals))
    for es in n.edges:
        out.edges.append(
            [(lab, t, fx if lab is None else (*fx, (key, None))) for lab, t, fx in es]
        )
    return out


def hidden(fx: tuple[Effect, ...], lab: Label) -> tuple[Effect, ...]:
    """Effects of an edge whose character ``lab`` the path drops."""
    return tuple((k, lab) if v is None else (k, v) for k, v in fx)


def product(a: NFA, b: NFA) -> NFA:
    """The intersection of two automata, built over reachable pairs."""
    out = NFA()
    index: dict[tuple[int, int], int] = {}
    todo: deque[tuple[int, int]] = deque()

    def state(p: int, q: int) -> int:
        if (p, q) not in index:
            index[(p, q)] = out.new()
            todo.append((p, q))
        return index[(p, q)]

    out.start = state(a.start, b.start)
    while todo:
        p, q = todo.popleft()
        s = index[(p, q)]
        if p in a.finals and q in b.finals:
            out.finals.add(s)
        for lab, t, fx in a.edges[p]:
            if lab is None:
                out.add(s, None, state(t, q), fx)
        for lab, t, fx in b.edges[q]:
            if lab is None:
                out.add(s, None, state(p, t), fx)
        for la, ta, fa in a.edges[p]:
            if la is None:
                continue
            for lb, tb, fb in b.edges[q]:
                if lb is None:
                    continue
                m = meet(la, lb)
                if m is not None:
                    out.add(s, m, state(ta, tb), fa + fb)
    return out


def path(n: NFA) -> list[tuple[Label | None, tuple[Effect, ...]]] | None:
    """The edges of a shortest accepted word, or None if ``n`` accepts none."""
    prev: dict[int, tuple[int, Label | None, tuple[Effect, ...]] | None] = {
        n.start: None
    }
    todo = deque([n.start])
    while todo:
        s = todo.popleft()
        if s in n.finals:
            out = []
            step = prev[s]
            while step is not None:
                p, lab, fx = step
                out.append((lab, fx))
                s, step = p, prev[p]
            return out[::-1]
        for lab, t, fx in n.edges[s]:
            if t not in prev:
                prev[t] = (s, lab, fx)
                todo.append(t)
    return None


def nonempty(n: NFA) -> bool:
    return path(n) is not None


def accepts(n: NFA, labels: list[Label]) -> bool:
    cur = n.closure({n.start})
    for x in labels:
        nxt = set()
        for s in cur:
            for lab, t, _ in n.edges[s]:
                if lab is not None and meet(lab, x) is not None:
                    nxt.add(t)
        cur = n.closure(nxt)
    return bool(cur & n.finals)


# -- a segment rewritten ---------------------------------------------------------


@dataclass
class FST:
    """A transducer on the last segment: (state, input label or None, output,
    state), where output is "copy", None (the input is dropped), or an
    automaton whose text is inserted. ``sep`` keeps the segment's "/"."""

    edges: list[tuple[int, Chars | None, Any, int]]
    finals: set[int]
    sep: bool = True


def _last(n: NFA, fst: FST) -> NFA:
    """``n`` with its last segment rewritten by ``fst``. A path with no
    segment has none to rewrite, and drops."""
    out = NFA()
    index: dict[tuple[Any, ...], int] = {}
    todo: deque[tuple[Any, ...]] = deque()

    def state(key: tuple[Any, ...]) -> int:
        if key not in index:
            index[key] = out.new()
            todo.append(key)
        return index[key]

    accept = out.new()
    out.finals = {accept}
    out.start = state(("pre", n.start, False))
    while todo:
        key = todo.popleft()
        s = index[key]
        if key[0] == "pre":
            _, q, boundary = key
            if boundary:
                out.add(s, None, state(("seg", q, 0)))
            for lab, t, fx in n.edges[q]:
                if lab is None:
                    out.add(s, None, state(("pre", t, boundary)), fx)
                else:
                    at = isinstance(lab, Tok) or lab == SEP
                    out.add(s, lab, state(("pre", t, at)), fx)
            continue
        _, q, f = key
        for lab, t, fx in n.edges[q]:
            if lab is None:
                out.add(s, None, state(("seg", t, f)), fx)
            elif lab == SEP and f in fst.finals and n.closure({t}) & n.finals:
                if fst.sep:
                    out.add(s, SEP, accept, fx)
                else:
                    out.add(s, None, accept, hidden(fx, SEP))
        for f0, inl, emit, f1 in fst.edges:
            if f0 != f:
                continue
            if inl is None:
                if emit is None:
                    out.add(s, None, state(("seg", q, f1)))
                else:
                    a, fins = out.embed(emit)
                    out.add(s, None, a)
                    for x in fins:
                        out.add(x, None, state(("seg", q, f1)))
                continue
            for lab, t, fx in n.edges[q]:
                if lab is None or isinstance(lab, Tok) or lab == SEP:
                    continue
                m = meet(lab, inl)
                if m is None:
                    continue
                if emit == "copy":
                    out.add(s, m, state(("seg", t, f1)), fx)
                else:
                    out.add(s, None, state(("seg", t, f1)), hidden(fx, m))
    return out


def _prefixed(n: NFA, prefix: NFA, lead: Label | None) -> NFA:
    """The rest of ``n``'s words after a word of ``prefix``, which the path
    drops, with ``lead`` first: ``n``'s left quotient, keeping who emitted
    the dropped prefix."""
    out = NFA()
    index: dict[tuple[Any, ...], int] = {}
    todo: deque[tuple[Any, ...]] = deque()

    def state(key: tuple[Any, ...]) -> int:
        if key not in index:
            index[key] = out.new()
            todo.append(key)
        return index[key]

    first = out.new()
    out.start = first
    out.add(first, lead, state(("pre", n.start, prefix.start)))
    while todo:
        key = todo.popleft()
        s = index[key]
        if key[0] == "rest":
            q = key[1]
            if q in n.finals:
                out.finals.add(s)
            for lab, t, fx in n.edges[q]:
                out.add(s, lab, state(("rest", t)), fx)
            continue
        _, q, r = key
        if r in prefix.finals:
            out.add(s, None, state(("rest", q)))
        for lab, t, fx in n.edges[q]:
            if lab is None:
                out.add(s, None, state(("pre", t, r)), fx)
        for lab, t, fx in prefix.edges[r]:
            if lab is None:
                out.add(s, None, state(("pre", q, t)), fx)
        for la, ta, fa in n.edges[q]:
            if la is None:
                continue
            for lb, tb, fb in prefix.edges[r]:
                if lb is None:
                    continue
                m = meet(la, lb)
                if m is not None:
                    out.add(s, None, state(("pre", ta, tb)), hidden(fa + fb, m))
    return out


def _quiet(n: NFA) -> NFA:
    """``n`` read but not kept: its words become the empty word."""
    out = NFA(start=n.start, finals=set(n.finals))
    for es in n.edges:
        out.edges.append(
            [(None, t, fx if lab is None else hidden(fx, lab)) for lab, t, fx in es]
        )
    return out


# -- the languages of the pieces -------------------------------------------------

ANYTEXT = star(word([SEGCHAR]))  # any text a field may render: no "/", no NUL
NONEMPTY = plus(word([SEGCHAR]))
NAME_OK = union(  # a segment that is not "", "." or ".."
    concat(word([NONDOT]), ANYTEXT),
    concat(text("."), word([NONDOT]), ANYTEXT),
    concat(text(".."), NONEMPTY),
)
NOT_DOT = union(text(""), concat(word([NONDOT]), ANYTEXT), concat(text("."), NONEMPTY))
SEGMENT = concat(NONEMPTY, word([SEP]))  # any segment pathlib keeps, ".." included
CANON_SEG = concat(product(NONEMPTY, NOT_DOT), word([SEP]))  # not ".", ".." allowed
SPLICE_SEG = concat(NAME_OK, word([SEP]))
FINITE_TYPES = {bool: (False, True)}


def _value_text(p: Param, key: Any, render: Any) -> NFA:
    """Any text, emitted by ``key``: a value's ``__format__`` and
    ``__fspath__`` may return anything. A declared type narrows nothing,
    as long as it may be subclassed."""
    if p.type is not None:
        try:
            type("_Sub", (p.type,), {})
        except TypeError:
            raise Unsupported(f"type {p.type!r} cannot be subclassed") from None
    return tag(ANYTEXT, key)


def _chosen(n: NFA, key: Any, v: Any) -> NFA:
    """``n``, recording that ``key`` takes the value ``v``."""
    out = NFA()
    out.start = out.new()
    s, fs = out.embed(n)
    out.add(out.start, None, s, ((key, ("value", v)),))
    out.finals = fs
    return out


# A use's shape is how its text is derived from the value: through
# os.fspath or format(v, "") alone in a segment, a SubPath or a head
# ("fspath"); by format after a conversion with a spec in text; by the value
# itself for a type of two values. Rendering is a function of structure
# (docs/SEMANTICS.md §15.3, 1), so uses of one shape render one text, while
# a value of a type of its own may render different shapes apart.
FSPATH = ("fspath",)
FINITE = ("finite",)


@dataclass
class Side:
    """Who emits a side's characters: keys ``(side, name, shape, use)``,
    with each use of a name in a shape numbered. ``fixed`` holds a text a
    (name, shape) is held to."""

    name: str
    fixed: dict[tuple[str, Any], Any] = field(default_factory=dict)
    uses: dict[tuple[str, Any], int] = field(default_factory=dict)
    # how each use renders: "field" (alone in a segment), "text", "finite",
    # "head" or "splice"
    kinds: dict[Any, str] = field(default_factory=dict)

    def key(self, param: str, shape: Any, kind: str) -> tuple[str, str, Any, int]:
        i = self.uses.get((param, shape), 0)
        self.uses[(param, shape)] = i + 1
        k = (self.name, param, shape, i)
        self.kinds[k] = kind
        return k

    @property
    def repeated(self) -> bool:
        return any(n > 1 for n in self.uses.values())


def _held(lang: NFA, side: Side, param: str, shape: Any, words: NFA) -> NFA:
    """``lang``, held to ``words`` where the (name, shape) is fixed."""
    return product(lang, words) if (param, shape) in side.fixed else lang


def _field(f: Field, side: Side) -> NFA:
    src = f.source
    if f.role == "segment":
        if not isinstance(src, Param):
            raise Unsupported("segment field of a non-parameter")
        if src.type in FINITE_TYPES:
            return _finite(src, side, lambda v: format(v, ""), NAME_OK)
        lang = product(
            _value_text(src, side.key(src.name, FSPATH, "field"), None), NAME_OK
        )
        return _held(lang, side, src.name, FSPATH, _fixed_text(side, src.name, FSPATH))
    if isinstance(src, Const):
        if f.static_spec is None:
            raise Unsupported("constant with a dynamic spec")
        try:
            return text(format_field(f, src.value, f.static_spec))
        except Exception:  # noqa: BLE001
            return empty()
    if not isinstance(src, Param):
        raise Unsupported(f"field of {type(src).__name__}")
    if f.static_spec is None:
        raise Unsupported("dynamic spec")
    if f.conversion is not None and f.static_spec:
        raise Unsupported("a conversion with a spec formats a str")
    if f.conversion == "a":
        raise Unsupported("ascii conversion")
    spec = f.static_spec
    if src.type in FINITE_TYPES:
        return _finite(src, side, lambda v: format_field(f, v, spec), None)
    shape = ("format", f.conversion, spec)
    base = _value_text(src, side.key(src.name, shape, "text"), None)
    dot_free, non_empty = f.facts
    if dot_free:
        base = product(base, star(word([NONDOT])))
    if non_empty:
        base = product(base, NONEMPTY)
    return _held(base, side, src.name, shape, _fixed_text(side, src.name, shape))


def _fixed_text(side: Side, param: str, shape: Any) -> NFA:
    t = side.fixed.get((param, shape))
    return text(t) if isinstance(t, str) else empty()


def _finite(p: Param, side: Side, render: Any, within: NFA | None) -> NFA:
    """A field of a type of two values: each value's text, chosen outright."""
    key = side.key(p.name, FINITE, "finite")
    branches = []
    for v in FINITE_TYPES[p.type]:
        if (p.name, FINITE) in side.fixed and side.fixed[(p.name, FINITE)] is not v:
            continue
        try:
            t = render(v)
        except Exception:  # noqa: BLE001 (a value the field refuses renders nothing)
            continue
        lang = _chosen(tag(text(t), key), key, v)
        branches.append(product(lang, within) if within is not None else lang)
    return union(*branches) if branches else empty()


def _pieces(pieces: tuple[Any, ...], side: Side) -> NFA:
    return compact(
        concat(*(text(p) if isinstance(p, str) else _field(p, side) for p in pieces))
    )


def _seg(part: Seg, side: Side) -> NFA:
    if part.literal is not None:
        return concat(text(part.literal), word([SEP]))
    lang = _pieces(part.pieces, side)
    if part.needs_check:
        lang = product(lang, NAME_OK)
    elif nonempty(product(lang, union(text(""), text("."), text("..")))):
        raise Unsupported("an unchecked segment may render '', '.' or '..'")
    return concat(lang, word([SEP]))


def _head_param(p: Param, side: Side) -> NFA:
    if p.type is not None:
        raise Unsupported("typed path parameter")
    anchors = ["/", "//"] if p.kind is Kind.ABSOLUTE else ["", "/", "//"]
    lang = tag(
        concat(union(*(word([ANCHORS[a]]) for a in anchors)), star(CANON_SEG)),
        side.key(p.name, FSPATH, "head"),
    )
    t = side.fixed.get((p.name, FSPATH))
    return _held(
        lang, side, p.name, FSPATH, word(encode(t)) if isinstance(t, str) else empty()
    )


def _splice(p: Param, side: Side) -> NFA:
    if p.type is not None:
        raise Unsupported("typed SubPath")
    lang = tag(star(SPLICE_SEG), side.key(p.name, FSPATH, "splice"))
    t = side.fixed.get((p.name, FSPATH))
    held = empty()
    if isinstance(t, str):
        held = concat(
            *(concat(text(x), word([SEP])) for x in t.split("/") if x not in ("", "."))
        )
    return _held(lang, side, p.name, FSPATH, held)


def _with_name(n: NFA, name: NFA) -> NFA:
    name = compact(product(name, product(NONEMPTY, NOT_DOT)))
    return _last(
        n, FST([(0, None, name, 1), (1, SEGCHAR, None, 2), (2, SEGCHAR, None, 2)], {2})
    )


# A name splits as stem·suffix where the suffix is its last dot onward and the
# stem holds a character other than a dot (pathlib 3.14's suffix and stem).
# Otherwise it is all stem: leading dots, then no dot at all.


def _with_suffix(n: NFA, suffix: str) -> NFA:
    add = text(suffix)
    return _last(
        n,
        FST(
            [
                # u (holding a non-dot) is kept, ".v" dropped, the suffix added
                (0, None, None, 10),
                (10, SEGCHAR, "copy", 10),
                (10, NONDOT, "copy", 1),
                (1, SEGCHAR, "copy", 1),
                (1, DOT, None, 2),
                (2, NONDOT, None, 2),
                (2, None, add, 9),
                # no suffix: dots, then dot-free text, all kept, the suffix added
                (0, None, None, 3),
                (3, DOT, "copy", 3),
                (3, NONDOT, "copy", 4),
                (4, NONDOT, "copy", 4),
                (3, None, add, 9),
                (4, None, add, 9),
            ],
            {9},
        ),
    )


def _with_stem(n: NFA, stem: NFA) -> NFA:
    return _last(
        n,
        FST(
            [
                # with a suffix: u dropped, the stem (not empty) added, ".v" kept
                (0, None, compact(product(stem, NONEMPTY)), 1),
                (1, SEGCHAR, None, 1),
                (1, NONDOT, None, 2),
                (2, SEGCHAR, None, 2),
                (2, DOT, "copy", 3),
                (3, NONDOT, "copy", 3),
                # without one: the name dropped, the stem is the new name
                (0, None, compact(product(stem, product(NONEMPTY, NOT_DOT))), 5),
                (5, DOT, None, 5),
                (5, NONDOT, None, 6),
                (6, NONDOT, None, 6),
            ],
            {3, 5, 6},
        ),
    )


# -- expressions -------------------------------------------------------------------


def language(e: PathExpr, side: str = "a") -> NFA:
    """Every path ``e`` renders, over all bindings, as an automaton whose
    edges record which of ``e``'s parameters emit each character. Raises
    `Unsupported` where a name is used twice in one shape: its uses render
    one text, and the set is not regular in general."""
    sd = Side(side)
    lang = _lang(e, sd)
    if sd.repeated:
        raise Unsupported("a name used twice")
    return lang


def _lang(e: PathExpr, side: Side) -> NFA:
    h = e.head
    if isinstance(h, _Rel):
        head = word([ANCHORS[""]])
    elif isinstance(h, Root):
        head = word([ANCHORS[h.anchor]])
    elif isinstance(h, HeadParam):
        head = _head_param(h.param, side)
    elif isinstance(h, Deferred):
        head = _deferred(h, side)
    else:
        raise Unsupported(f"head {h!r}")
    parts = []
    for part in e.parts:
        if isinstance(part, Seg):
            parts.append(_seg(part, side))
        else:
            parts.append(_splice(part.param, side))
    return compact(concat(head, *parts))


def _arg_text(arg: Any, side: Side) -> NFA:
    if isinstance(arg, str):
        return text(arg)
    if isinstance(arg, Text):
        return _pieces(arg.pieces, side)
    raise Unsupported(f"argument {arg!r}")


ABSOLUTE = concat(union(word([ANCHORS["/"]]), word([ANCHORS["//"]])), star(SEGMENT))
RELATIVE = concat(word([ANCHORS[""]]), star(SEGMENT))


def _deferred(h: Deferred, side: Side) -> NFA:
    return compact(_deferred_raw(h, side))


def _deferred_raw(h: Deferred, side: Side) -> NFA:
    base = _lang(h.base, side)
    if h.op == "parent":
        anchor_only = union(*(word([t]) for t in ANCHORS.values()))
        drop = FST([(0, SEGCHAR, None, 1), (1, SEGCHAR, None, 1)], {1}, sep=False)
        return union(product(base, anchor_only), _last(base, drop))
    if h.op == "with_name":
        return _with_name(base, _arg_text(h.arg, side))
    if h.op == "with_suffix":
        if not isinstance(h.arg, str):
            raise Unsupported("dynamic suffix")
        return _with_suffix(base, h.arg)
    if h.op == "with_stem":
        return _with_stem(base, _arg_text(h.arg, side))
    if h.op == "relative_to":
        if not isinstance(h.arg, PathExpr):
            raise Unsupported("relative_to of a non-path")
        # The other path is base or one of its parents, anchors included.
        return _prefixed(base, _lang(h.arg, side), ANCHORS[""])
    if h.op == "join":
        if not isinstance(h.arg, PathExpr):
            raise Unsupported("join of a non-path")
        arg = _lang(h.arg, side)
        rel = _prefixed(product(arg, RELATIVE), word([ANCHORS[""]]), None)
        return union(concat(base, rel), concat(_quiet(base), product(arg, ABSOLUTE)))
    raise Unsupported(f"operation {h.op}")


# -- witnesses ----------------------------------------------------------------------


class _Shows:
    """A value that renders its text for each shape: through ``__fspath__``,
    and through ``__format__``, ``__str__`` and ``__repr__`` for each spec
    and conversion."""

    def __init__(self, texts: dict[Any, str]) -> None:
        self.texts = texts

    def _for(self, shape: Any) -> str:
        return self.texts.get(shape, "")

    def __format__(self, spec: str) -> str:
        return self._for(("format", None, spec))

    def __str__(self) -> str:
        return self._for(("format", "s", ""))

    def __repr__(self) -> str:
        return self._for(("format", "r", ""))

    def __fspath__(self) -> str:
        return self._for(FSPATH)


def _value(p: Param, texts: dict[Any, str]) -> Any:
    """A value of ``p`` that renders ``texts[shape]`` in each shape it is
    used in. A plain str does where only its path text is used; otherwise an
    object of its own, of ``p``'s type and equal to a choice where declared."""
    if p.type is None and p.choices is None and set(texts) <= {FSPATH}:
        return texts.get(FSPATH, "")
    bases: tuple[type, ...] = (_Shows,) if p.type is None else (_Shows, p.type)
    cls = type("_Value", bases, {})
    if p.choices is not None:
        c = next(iter(p.choices))
        cls.__hash__ = lambda self, c=c: hash(c)  # type: ignore[method-assign]
        cls.__eq__ = lambda self, o: True  # type: ignore[method-assign,assignment]
    if p.type is None:
        return cls(texts)
    try:  # a str subclass's own text is its path text
        v = p.type.__new__(cls, texts.get(FSPATH, ""))
    except Exception:  # noqa: BLE001 (a type that is not built from text)
        v = p.type.__new__(cls)
    _Shows.__init__(v, texts)
    return v


def _params(e: PathExpr) -> dict[str, Param]:
    return {p.name: p for p in e.params.values()}


@dataclass
class _Reading:
    """What a witness gives each side: a value per name, where each shape's
    uses agree, and the texts of a (name, shape)'s uses where they do not."""

    envs: dict[str, dict[str, Any]]
    conflicts: dict[str, dict[tuple[str, Any], set[Any]]]


TIED = "*"  # the group of a name tied across both sides


def _path_text(t: str) -> str:
    """A path's text as its characters spell it: anchor, then segments each
    followed by "/"; as rendered."""
    return t.rstrip("/") or ("." if not t else t)


def _bindings(
    edges: list[tuple[Label | None, tuple[Effect, ...]]],
    sides: dict[str, tuple[PathExpr, Side]],
    tied: frozenset[str] = frozenset(),
) -> _Reading:
    texts: dict[Any, list[str]] = {}
    chosen: dict[Any, Any] = {}
    for lab, fx in edges:
        for key, how in fx:
            if isinstance(how, tuple) and how and how[0] == "value":
                chosen[key] = how[1]
                continue
            shown = lab if how is None else how
            assert isinstance(shown, Chars | Tok)  # an effect's edge reads one
            texts.setdefault(key, []).append(pick(shown))
    # A name's uses are grouped by side, or across both sides where the
    # name is tied (one value on both, under shared bindings): group "*".
    seen: dict[str, dict[tuple[str, Any], set[Any]]] = {}
    for side, (_, sd) in sides.items():
        for (name, shape), count in sd.uses.items():
            group = seen.setdefault(TIED if name in tied else side, {})
            got = group.setdefault((name, shape), set())
            for use in range(count):
                key = (side, name, shape, use)
                if shape == FINITE:
                    got.add(chosen.get(key))
                    continue
                t = "".join(texts.get(key, []))
                # A path's text ends in "/" (or is empty), a segment's
                # never: both are its value's os.fspath.
                got.add(_path_text(t) if shape == FSPATH else t)
    conflicts = {
        g: {k: v for k, v in groups.items() if len(v) > 1} for g, groups in seen.items()
    }
    conflicts = {g: c for g, c in conflicts.items() if c}
    envs: dict[str, dict[str, Any]] = {}
    for side, (e, _) in sides.items():
        env: dict[str, Any] = {}
        for name, p in _params(e).items():
            g = TIED if name in tied else side
            if any(k[0] == name for k in conflicts.get(g, {})):
                continue
            per_shape = {
                shape: next(iter(v)) for (n, shape), v in seen[g].items() if n == name
            }
            env[name] = (
                per_shape[FINITE] if FINITE in per_shape else _value(p, per_shape)
            )
        envs[side] = env
    return _Reading(envs, conflicts)


# -- relations -----------------------------------------------------------------------

BELOW = plus(SEGMENT)  # one segment or more


def encode(path_text: str) -> list[Label]:
    """A rendered path's labels."""
    from pathlib import PurePosixPath

    p = PurePosixPath(path_text)
    out: list[Label] = [ANCHORS[p.anchor]]
    for seg in p.parts[1:] if p.anchor else p.parts:
        out.extend(chars(c) for c in seg)
        out.append(SEP)
    return out


def _singleton(n: NFA) -> list[Label] | None:
    """The one word ``n`` accepts, if it accepts exactly one."""
    w = path(n)
    if w is None:
        return None
    labels = [lab for lab, _ in w if lab is not None]
    if any(isinstance(x, Chars) and (x.co or len(x.chars) != 1) for x in labels):
        return None
    return None if nonempty(product(n, _not_word(labels, below=False))) else labels


ANYLABEL: list[Label] = [*ANCHORS.values(), but("")]


def _any_star() -> NFA:
    return star(union(*(word([x]) for x in ANYLABEL)))


def _not_word(w: list[Label], below: bool) -> NFA:
    """Every word but ``w`` (whose labels are single); with ``below``, also
    but ``w`` followed by one segment or more (``w`` itself included)."""
    branches = [word(w[:i]) for i in range(len(w))]
    if below:
        branches.append(word(w))
    for i, x in enumerate(w):
        others: list[Label] = [t for t in ANCHORS.values() if t != x]
        others.append(Chars(x.chars, True) if isinstance(x, Chars) else but(""))
        branches.append(
            concat(word(w[:i]), union(*(word([o]) for o in others)), _any_star())
        )
    if not below:
        branches.append(concat(word(w), plus(union(*(word([x]) for x in ANYLABEL)))))
    return union(*branches)


@dataclass(frozen=True)
class Answer:
    """Each relation: ``"never"``, ``"sometimes"`` or ``"always"``, exactly;
    ``"possible"`` where a binding shows it but whether it always holds is
    not decided; ``"undecided"`` where neither is shown."""

    same: str
    inside: str
    contains: str
    # for each relation shown to hold, bindings of each side showing it
    examples: dict[str, dict[str, dict[str, Any]]]

    def __getitem__(self, how: str) -> str:
        return getattr(self, how)


POSSIBLE = ("sometimes", "always", "possible")
HOWS = ("same", "inside", "contains")


def _shows(a: PathExpr, b: PathExpr, how: str, envs: dict[str, dict[str, Any]]) -> bool:
    from wend._relate import lexically  # how two rendered strings relate

    try:
        pa = a.render({k: v for k, v in envs["a"].items() if k in a.param_names})
        pb = b.render({k: v for k, v in envs["b"].items() if k in b.param_names})
    except Exception:  # noqa: BLE001 (a binding either side refuses)
        return False
    return lexically(pa, pb) == how


Fixed = dict[str, dict[tuple[str, Any], Any]]


def relate_independent(
    a: PathExpr, b: PathExpr, *, depth: int = 2, fixed: Fixed | None = None
) -> Answer:
    """The relation of ``a`` and ``b`` under independent bindings (`_relate`)."""
    return _relate(a, b, depth, fixed or {}, frozenset())


def _relate(
    a: PathExpr, b: PathExpr, depth: int, fixed: Fixed, tied: frozenset[str]
) -> Answer:
    """The relation of ``a`` and ``b`` under independent bindings.

    Each use of a name is read on its own, so where a name is used twice in
    one shape the language is larger than what renders, and ``"never"``
    stays exact. A witness counts only where each shape's uses of a name
    agree, which rendering confirms. Failing that, the texts a disagreeing
    (name, shape) can take are fixed one by one (``depth`` times over) and
    decided again; where those were all its texts and none shows the
    relation, it never holds. ``fixed`` holds a side's (name, shape) to a
    text, or a value for a type of two values. A ``tied`` name takes one
    value on both sides: its uses on both are grouped as one name's."""
    sa, sb = Side("a", dict(fixed.get("a", {}))), Side("b", dict(fixed.get("b", {})))
    la, lb = _lang(a, sa), _lang(b, sb)
    exact = not (sa.repeated or sb.repeated or tied)
    if not nonempty(la) or not nonempty(lb):
        # No binding renders both: every relation is vacuously never (§15.1).
        return Answer("never", "never", "never", {})
    sides = {"a": (a, sa), "b": (b, sb)}
    examples: dict[str, dict[str, dict[str, Any]]] = {}
    out: dict[str, str] = {}
    for how, x, y in (
        ("same", la, lb),
        ("inside", la, concat(lb, BELOW)),
        ("contains", concat(la, BELOW), lb),
    ):
        both = product(x, y)
        w = path(both)
        if w is None:
            out[how] = "never"
            continue
        reading = _bindings(w, sides, tied)
        if not reading.conflicts and _shows(a, b, how, reading.envs):
            out[how] = "sometimes"
            examples[how] = reading.envs
            continue
        verdict, envs = "undecided", None
        if _counted_never(both, sides, tied):
            verdict = "never"
        elif reading.conflicts and depth > 0:
            verdict, envs = _substitute(
                a, b, how, _candidates(both, reading, sides), fixed, depth, tied
            )
        out[how] = "sometimes" if verdict == "possible" else verdict
        if envs is not None:
            examples[how] = envs
    # always: every pair relates. Decided on the languages, which are exact
    # without repeats; with them, only where some pair was shown to relate.
    sa_w, sb_w = _singleton(la), _singleton(lb)
    always = {
        "same": sa_w is not None and sb_w is not None and sa_w == sb_w,
        "inside": sb_w is not None
        and not nonempty(product(la, _not_word(sb_w, below=True))),
        "contains": sa_w is not None
        and not nonempty(product(lb, _not_word(sa_w, below=True))),
    }
    for how in HOWS:
        if out[how] == "sometimes":
            if always[how]:
                out[how] = "always"
            elif not exact:
                out[how] = "possible"
    return Answer(out["same"], out["inside"], out["contains"], examples)


def relate_shared(a: PathExpr, b: PathExpr, *, depth: int = 2) -> Answer:
    """The relation of ``a`` and ``b`` under shared bindings (SEMANTICS
    §15.1): a name of both takes one value on both sides, so its uses on both
    are tied as one name's (`_relate`).

    A name both sides give a default may also be left unbound, and each side
    then renders its own default. Each such name is decided both ways: tied,
    and with each side bound to its own default. The relation holds never
    (or always) where it does in every case, and is possible where it is in
    one."""
    pa, pb = _params(a), _params(b)
    common = sorted(pa.keys() & pb.keys())
    for n in common:
        x, y = pa[n], pb[n]
        if x.type is not y.type or x.choices != y.choices or x.kind != y.kind:
            raise Unsupported(f"{n!r} is declared differently on each side")
    split = [n for n in common if pa[n].has_default and pb[n].has_default]
    if len(split) > 3:
        raise Unsupported("more than three names with defaults on both sides")
    cases = []
    for k in range(len(split) + 1):
        for unbound in itertools.combinations(split, k):
            a_ = a.bind({n: pa[n].default for n in unbound}) if unbound else a
            b_ = b.bind({n: pb[n].default for n in unbound}) if unbound else b
            tied = frozenset(common) - set(unbound)
            r = _relate(a_, b_, depth, {}, tied)
            rest = _cancelled(a_, b_)
            if rest is not None:
                r = _refined(r, _relate(*rest, depth, {}, tied))
            cases.append(r)
    out: dict[str, str] = {}
    examples: dict[str, dict[str, dict[str, Any]]] = {}
    for how in HOWS:
        got = [r[how] for r in cases]
        shown = next((r for r in cases if r[how] in POSSIBLE), None)
        if all(g == "never" for g in got):
            out[how] = "never"
        elif all(g == "always" for g in got):
            out[how] = "always"
        elif "sometimes" in got:
            out[how] = "sometimes"
        elif shown is not None:
            out[how] = "possible"
        else:
            out[how] = "undecided"
        if shown is not None and how in shown.examples:
            env = {**shown.examples[how]["a"], **shown.examples[how]["b"]}
            examples[how] = {"a": env, "b": env}
    return Answer(out["same"], out["inside"], out["contains"], examples)


def _cancelled(a: PathExpr, b: PathExpr) -> tuple[PathExpr, PathExpr] | None:
    """What follows a head and leading parts ``a`` and ``b`` share, as two
    relative paths; None if their heads differ.

    Under shared bindings a piece equal on both sides renders one text on
    both (SEMANTICS §15.3, 1), and a path's characters are its head's then
    its parts'. In a free monoid ``uv = uw`` exactly where ``v = w``, and
    ``uv`` is ``uw`` followed by more exactly where ``v`` is ``w`` followed
    by more. So on every binding that renders both, ``a`` and ``b`` relate
    as what follows does. Every such binding renders what follows, since a
    part renders by itself, so a relation never (or always) holding there
    never (or always) holds of ``a`` and ``b``."""
    if a.head != b.head:
        return None
    k = 0
    while k < min(len(a.parts), len(b.parts)) and a.parts[k] == b.parts[k]:
        k += 1
    return _new(REL, a.parts[k:]), _new(REL, b.parts[k:])


def _refined(whole: Answer, rest: Answer) -> Answer:
    """``whole``, with what the parts after a shared prefix decide (`_cancelled`)."""
    out: dict[str, str] = {}
    for how in HOWS:
        mine, theirs = whole[how], rest[how]
        if theirs == "never" and mine in POSSIBLE:
            raise AssertionError(
                f"{how}: a rendered witness, though never after a prefix"
            )
        # "always" only where a binding was shown: one that renders both
        # may not exist, and every possible answer comes with one.
        if theirs == "never" or (theirs == "always" and mine in POSSIBLE):
            out[how] = theirs
        else:
            out[how] = mine
    examples = {how: env for how, env in whole.examples.items() if out[how] in POSSIBLE}
    return Answer(out["same"], out["inside"], out["contains"], examples)


# -- counts --------------------------------------------------------------------
#
# Uses of a name in one shape render one text, so they emit as many
# characters, and uses that each render a path's segments emit as many
# separators. A word of the intersection shows a binding only where those
# counts agree. Each disagreement is a weight on the automaton's edges, and
# where some sum of them is positive (or negative) on every accepting walk,
# no word has them all zero: the relation never holds. The walks' least
# weight is a shortest path, with -infinity where a negative cycle lies on
# one (Bellman-Ford): a Farkas certificate for the counts' integer program.


def _emitted(lab: Label | None, fx: tuple[Effect, ...]) -> list[tuple[Any, str]]:
    """(key, "chars" or "seps") for each character an edge's effects emit."""
    out = []
    for k, how in fx:
        if isinstance(how, tuple) and how and how[0] == "value":
            continue
        shown = lab if how is None else how
        if isinstance(shown, Chars):
            out.append((k, "seps" if shown == SEP else "chars"))
    return out


def _count_dims(
    sides: dict[str, tuple[PathExpr, Side]], tied: frozenset[str]
) -> list[tuple[str, Any, Any]]:
    """Each count two uses of one (name, shape) must agree on: (measure,
    first use, other use). A type of two values renders each spec its own
    way, so its uses are not compared; separators are compared where every
    use renders a path's segments the same way (all heads, or all
    SubPaths)."""
    groups: dict[tuple[str, str, Any], list[Any]] = {}
    kinds: dict[Any, str] = {}
    for side, (_, sd) in sides.items():
        kinds.update(sd.kinds)
        for (name, shape), n in sd.uses.items():
            if shape == FINITE:
                continue
            g = (TIED if name in tied else side, name, shape)
            groups.setdefault(g, []).extend((side, name, shape, i) for i in range(n))
    dims = []
    for uses in groups.values():
        same_kind = len({kinds.get(u) for u in uses}) == 1
        paths = same_kind and kinds.get(uses[0]) in ("head", "splice")
        for u in uses[1:]:
            dims.append(("chars", uses[0], u))
            if paths:
                dims.append(("seps", uses[0], u))
    return dims


def _least_walk(n: NFA, w: dict[tuple[int, int], int]) -> float:
    """The least total weight of a walk from ``n``'s start to a final state,
    over ``n`` trimmed; -inf where a negative cycle lies on one."""
    dist: dict[int, float] = {n.start: 0}
    for _ in range(len(n.edges)):
        changed = False
        for s, d in list(dist.items()):
            for i, (_, t, _) in enumerate(n.edges[s]):
                nd = d + w.get((s, i), 0)
                if nd < dist.get(t, float("inf")):
                    dist[t] = nd
                    changed = True
        if not changed:
            break
    else:
        return float("-inf")
    return min((dist[f] for f in n.finals if f in dist), default=float("inf"))


def _counted_never(
    both: NFA,
    sides: dict[str, tuple[PathExpr, Side]],
    tied: frozenset[str],
    limit: int = 2_000_000,
) -> bool:
    """Whether the counts of `_count_dims` rule out every word of ``both``."""
    dims = _count_dims(sides, tied)
    if not dims:
        return False
    n = compact(both)
    if not n.finals:
        return True
    size = len(n.edges) * max(1, sum(len(es) for es in n.edges))
    if size > limit:
        return False
    index = {d: i for i, d in enumerate(dims)}
    by_use: dict[tuple[str, Any], list[tuple[int, int]]] = {}
    for i, (measure, u0, u) in enumerate(dims):
        by_use.setdefault((measure, u0), []).append((i, 1))
        by_use.setdefault((measure, u), []).append((i, -1))
    vec: dict[tuple[int, int], list[int]] = {}
    for s, es in enumerate(n.edges):
        for j, (lab, _, fx) in enumerate(es):
            v = [0] * len(dims)
            for k, measure in _emitted(lab, fx):
                for i, sign in by_use.get((measure, k), ()):
                    v[i] += sign
            if any(v):
                vec[(s, j)] = v
    if not vec:
        return False
    m = len(index)
    if m <= 4:
        ys = [
            y
            for y in itertools.product((-1, 0, 1), repeat=m)
            if any(y) and next(c for c in y if c) > 0
        ]
    else:
        ys = [tuple(int(i == j) for j in range(m)) for i in range(m)]
        for measure in ("chars", "seps"):
            ys.append(tuple(int(d[0] == measure) for d in dims))
    for y in ys:
        w = {e: sum(a * b for a, b in zip(y, v, strict=True)) for e, v in vec.items()}
        if not any(w.values()):
            continue
        if _least_walk(n, w) > 0 or _least_walk(n, {e: -x for e, x in w.items()}) > 0:
            return True
    return False


def _projection(n: NFA, key: Any, limit: int = 64) -> set[str] | None:
    """The texts ``key`` emits on the words of ``n``, if there are at most
    ``limit`` of them; None if there are more (or infinitely many)."""
    m = NFA(start=n.start, finals=set(n.finals))
    for es in n.edges:
        row: list[Edge] = []
        for lab, t, fx in es:
            shown = [lab if how is None else how for k, how in fx if k == key]
            shown = [x for x in shown if isinstance(x, Chars | Tok)]
            if len(shown) == 1:
                row.append((shown[0], t, ()))
            else:
                row.append((None, t, ()))
        m.edges.append(row)
    m = compact(m)
    # finite exactly when no cycle reads a label
    out: set[str] = set()
    todo: list[tuple[int, str, frozenset[int]]] = [(m.start, "", frozenset())]
    seen_states: dict[tuple[int, str], None] = {}
    while todo:
        s, txt, onpath = todo.pop()
        if (s, txt) in seen_states:
            continue
        seen_states[(s, txt)] = None
        if s in m.finals:
            out.add(txt)
            if len(out) > limit:
                return None
        for lab, t, _ in m.edges[s]:
            if lab is None:
                if t in onpath:
                    continue
                todo.append((t, txt, onpath | {s}))
                continue
            if isinstance(lab, Chars) and (lab.co or len(lab.chars) > 1):
                return None  # more texts than we enumerate
            if len(txt) > 64:
                return None  # a cycle reads a label: infinitely many
            todo.append((t, txt + pick(lab), frozenset()))
    return out


def _candidates(
    both: NFA, reading: _Reading, sides: dict[str, tuple[PathExpr, Side]]
) -> list[tuple[str, tuple[str, Any], list[Any], bool]]:
    """For each (name, shape) whose uses disagreed: the texts to hold it to,
    and whether they are all it can render where the relation holds. Each
    use can emit only texts it emits on some word of ``both``; where one use
    can emit finitely many, the (name, shape)'s text is one of them."""
    out = []
    for group, groups in reading.conflicts.items():
        members = list(sides) if group == TIED else [group]
        for (name, shape), seen in groups.items():
            if shape == FINITE:
                p = next(
                    _params(e)[name]
                    for e, _ in (sides[m] for m in members)
                    if name in _params(e)
                )
                out.append((group, (name, shape), list(FINITE_TYPES[p.type]), True))
                continue
            finite: set[str] | None = None
            for m in members:
                for use in range(sides[m][1].uses.get((name, shape), 0)):
                    texts = _projection(both, (m, name, shape, use))
                    if texts is None:
                        continue
                    if shape == FSPATH:
                        texts = {_path_text(t) for t in texts}
                    finite = texts if finite is None else finite & texts
            if finite is not None:
                out.append((group, (name, shape), sorted(finite), True))
            else:
                out.append((group, (name, shape), sorted(seen, key=repr), False))
    return out


def _substitute(
    a: PathExpr,
    b: PathExpr,
    how: str,
    cands: list[tuple[str, tuple[str, Any], list[Any], bool]],
    fixed: Fixed,
    depth: int,
    tied: frozenset[str] = frozenset(),
    limit: int = 64,
) -> tuple[str, dict[str, dict[str, Any]] | None]:
    """Hold each disagreeing (name, shape) to each of its candidates and
    decide again: ``("possible", bindings)`` where one shows ``how``;
    ``("never", None)`` where the candidates were all its texts and none
    can; otherwise ``("undecided", None)``."""
    combos = list(
        itertools.islice(itertools.product(*(vs for _, _, vs, _ in cands)), limit + 1)
    )
    complete = all(c for _, _, _, c in cands) and len(combos) <= limit
    for combo in combos[:limit]:
        held = {s: dict(fixed.get(s, {})) for s in ("a", "b")}
        for (side, group, _, _), v in zip(cands, combo, strict=True):
            for s in ("a", "b") if side == TIED else (side,):
                held[s][group] = v
        r = _relate(a, b, depth - 1, held, tied)
        if r[how] in POSSIBLE:
            return "possible", r.examples[how]
        if r[how] != "never":
            complete = False
    return ("never", None) if complete else ("undecided", None)


__all__ = [
    "Answer",
    "NFA",
    "Unsupported",
    "accepts",
    "encode",
    "language",
    "relate_independent",
    "relate_shared",
]
