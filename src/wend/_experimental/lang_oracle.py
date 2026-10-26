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
suffix). So every path the oracle says is possible comes with a binding, and
`witness_bindings` returns it: rendering it with wend itself confirms the
answer.

The fragment, with ``builtin_values=False``:

- **Linear expressions.** A name used twice in one expression (``{p}/{p}``)
  renders one value twice, and that set is not regular in general; such
  expressions raise `Unsupported`.
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
    Const,
    Deferred,
    Field,
    HeadParam,
    PathExpr,
    Root,
    Seg,
    Splice,
    Text,
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
    """What ``p`` renders through ``render`` (a value to text, raising where
    the value is refused), tagged with ``key``."""
    finite = FINITE_TYPES.get(p.type)
    if finite is not None:
        branches = []
        for v in finite:
            try:
                s = render(v)
            except Exception:  # noqa: BLE001 (a value the field refuses renders nothing)
                continue
            branches.append(_chosen(tag(text(s), key), key, v))
        return union(*branches) if branches else empty()
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


def _field(f: Field, side: str) -> NFA:
    src = f.source
    if f.role == "segment":
        if not isinstance(src, Param):
            raise Unsupported("segment field of a non-parameter")
        key = (side, src.name)
        return product(_value_text(src, key, lambda v: format(v, "")), NAME_OK)
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
    key = (side, src.name)
    spec = f.static_spec
    if src.type in FINITE_TYPES:
        return _value_text(src, key, lambda v: format_field(f, v, spec))
    base = _value_text(src, key, None)
    dot_free, non_empty = f.facts
    if dot_free:
        base = product(base, star(word([NONDOT])))
    return product(base, NONEMPTY) if non_empty else base


def _pieces(pieces: tuple[Any, ...], side: str) -> NFA:
    return compact(
        concat(*(text(p) if isinstance(p, str) else _field(p, side) for p in pieces))
    )


def _seg(part: Seg, side: str) -> NFA:
    if part.literal is not None:
        return concat(text(part.literal), word([SEP]))
    lang = _pieces(part.pieces, side)
    if part.needs_check:
        lang = product(lang, NAME_OK)
    elif nonempty(product(lang, union(text(""), text("."), text("..")))):
        raise Unsupported("an unchecked segment may render '', '.' or '..'")
    return concat(lang, word([SEP]))


def _head_param(p: Param, side: str) -> NFA:
    if p.type is not None:
        raise Unsupported("typed path parameter")
    anchors = ["/", "//"] if p.kind is Kind.ABSOLUTE else ["", "/", "//"]
    return tag(
        concat(union(*(word([ANCHORS[a]]) for a in anchors)), star(CANON_SEG)),
        (side, p.name),
    )


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


def _names(e: PathExpr) -> list[str]:
    """Every parameter name use in ``e``, with repeats."""
    out: list[str] = []

    def field_names(f: Field) -> None:
        for s in f.spec:
            if isinstance(s, Param):
                out.append(s.name)
        src = f.source
        if isinstance(src, Param):
            out.append(src.name)
        elif isinstance(src, Text):
            for p in src.pieces:
                if isinstance(p, Field):
                    field_names(p)
        elif not isinstance(src, Const):
            out.append(f"<{type(src).__name__}>")

    def pieces(ps: tuple[Any, ...]) -> None:
        for p in ps:
            if isinstance(p, Field):
                field_names(p)

    def walk(x: PathExpr) -> None:
        h = x.head
        if isinstance(h, HeadParam):
            out.append(h.param.name)
        elif isinstance(h, Deferred):
            walk(h.base)
            if isinstance(h.arg, PathExpr):
                walk(h.arg)
            elif isinstance(h.arg, Text):
                pieces(h.arg.pieces)
        for part in x.parts:
            if isinstance(part, Splice):
                out.append(part.param.name)
            else:
                pieces(part.pieces)

    walk(e)
    return out


def language(e: PathExpr, side: str = "a") -> NFA:
    """Every path ``e`` renders, over all bindings, as an automaton whose
    edges record which of ``e``'s parameters (keyed ``(side, name)``) emit
    each character."""
    names = _names(e)
    if len(names) != len(set(names)):
        raise Unsupported("a name used twice")
    return _lang(e, side)


def _lang(e: PathExpr, side: str) -> NFA:
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
            if part.param.type is not None:
                raise Unsupported("typed SubPath")
            parts.append(tag(star(SPLICE_SEG), (side, part.param.name)))
    return compact(concat(head, *parts))


def _arg_text(arg: Any, side: str) -> NFA:
    if isinstance(arg, str):
        return text(arg)
    if isinstance(arg, Text):
        return _pieces(arg.pieces, side)
    raise Unsupported(f"argument {arg!r}")


ABSOLUTE = concat(union(word([ANCHORS["/"]]), word([ANCHORS["//"]])), star(SEGMENT))
RELATIVE = concat(word([ANCHORS[""]]), star(SEGMENT))


def _deferred(h: Deferred, side: str) -> NFA:
    return compact(_deferred_raw(h, side))


def _deferred_raw(h: Deferred, side: str) -> NFA:
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
    """A value that formats, prints and converts to ``text`` whatever the spec."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __format__(self, spec: str) -> str:
        return self.text

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return self.text

    def __fspath__(self) -> str:
        return self.text


def _value(p: Param, text: str, chosen: Any, role: str) -> Any:
    """A value of ``p`` that renders ``text`` where it is used."""
    if chosen is not _UNSET:
        return chosen
    if role == "path":
        if p.choices is None:
            return text
        cls = type("_Path", (_Shows,), {})  # os.PathLike by its __fspath__
    elif role == "segment" and p.type is None and p.choices is None:
        return text
    else:
        bases: tuple[type, ...] = (_Shows,) if p.type is None else (_Shows, p.type)
        cls = type("_Value", bases, {})
    if p.choices is not None:
        c = next(iter(p.choices))
        cls.__hash__ = lambda self, c=c: hash(c)  # type: ignore[method-assign]
        cls.__eq__ = lambda self, o: True  # type: ignore[method-assign,assignment]
    v = cls.__new__(cls) if p.type is not None else cls(text)
    if p.type is not None:
        _Shows.__init__(v, text)
    return v


_UNSET = object()


def _roles(e: PathExpr) -> dict[str, tuple[Param, str]]:
    """Each parameter of ``e`` with how it renders: a path, a segment, a value."""
    out: dict[str, tuple[Param, str]] = {}

    def pieces(ps: tuple[Any, ...]) -> None:
        for p in ps:
            if isinstance(p, Field) and isinstance(p.source, Param):
                out[p.source.name] = (
                    p.source,
                    "segment" if p.role == "segment" else "value",
                )

    def walk(x: PathExpr) -> None:
        h = x.head
        if isinstance(h, HeadParam):
            out[h.param.name] = (h.param, "path")
        elif isinstance(h, Deferred):
            walk(h.base)
            if isinstance(h.arg, PathExpr):
                walk(h.arg)
            elif isinstance(h.arg, Text):
                pieces(h.arg.pieces)
        for part in x.parts:
            if isinstance(part, Splice):
                out[part.param.name] = (part.param, "path")
            else:
                pieces(part.pieces)

    walk(e)
    return out


def _bindings(
    edges: list[tuple[Label | None, tuple[Effect, ...]]], sides: dict[str, PathExpr]
) -> dict[str, dict[str, Any]]:
    texts: dict[Any, list[str]] = {}
    chosen: dict[Any, Any] = {}
    for lab, fx in edges:
        for key, how in fx:
            if isinstance(how, tuple) and how and how[0] == "value":
                chosen[key] = how[1]
                continue
            shown = lab if how is None else how
            assert isinstance(shown, Chars | Tok)  # an effect's edge reads one
            c = pick(shown)
            texts.setdefault(key, []).append(c)
    out: dict[str, dict[str, Any]] = {}
    for side, e in sides.items():
        env: dict[str, Any] = {}
        for name, (p, role) in _roles(e).items():
            t = "".join(texts.get((side, name), []))
            if role == "path":
                t = t.rstrip("/") or ("." if not t else t)
            env[name] = _value(p, t, chosen.get((side, name), _UNSET), role)
        out[side] = env
    return out


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
    same: str
    inside: str
    contains: str
    # for each relation that may hold, bindings of each side showing it
    examples: dict[str, dict[str, dict[str, Any]]]

    def __getitem__(self, how: str) -> str:
        return getattr(self, how)


def relate_independent(a: PathExpr, b: PathExpr) -> Answer:
    """The exact relation of ``a`` and ``b`` under independent bindings."""
    la, lb = language(a, "a"), language(b, "b")
    if not nonempty(la) or not nonempty(lb):
        # No binding renders both: every relation is vacuously never (§15.1).
        return Answer("never", "never", "never", {})
    sides = {"a": a, "b": b}
    examples = {}
    out = {}
    for how, x, y in (
        ("same", la, lb),
        ("inside", la, concat(lb, BELOW)),
        ("contains", concat(la, BELOW), lb),
    ):
        w = path(product(x, y))
        if w is None:
            out[how] = "never"
            continue
        out[how] = "sometimes"
        examples[how] = _bindings(w, sides)
    sa, sb = _singleton(la), _singleton(lb)
    if sa is not None and sb is not None and sa == sb:
        out["same"] = "always"
    if (
        out["inside"] == "sometimes"
        and sb is not None
        and not nonempty(product(la, _not_word(sb, below=True)))
    ):
        out["inside"] = "always"
    if (
        out["contains"] == "sometimes"
        and sa is not None
        and not nonempty(product(lb, _not_word(sa, below=True)))
    ):
        out["contains"] = "always"
    return Answer(out["same"], out["inside"], out["contains"], examples)


__all__ = [
    "Answer",
    "NFA",
    "Unsupported",
    "accepts",
    "encode",
    "language",
    "relate_independent",
]
