"""Symbolic overlap: can two path expressions render the same path?

Experimental (see `wend._experimental`). ``overlaps(a, b)`` answers:

- ``YES``: a concrete path that both expressions render, with a binding of
  each side that renders it. Each binding either came from ``match_all``
  (which returns only bindings that render back to the path, SEMANTICS.md
  §7) or is one the path was rendered from: a sample value, or every
  binding of a small finite domain, rendered once per expression.
- ``NO``: no path can be rendered by both. The argument is an
  over-approximation: each expression's renderable paths are contained in a
  set of *shapes* (below), and no shape of one intersects a shape of the
  other. Every rule that builds a shape keeps every path the contract lets
  the expression render, so an empty intersection of shapes is an empty
  intersection of paths.
- ``MAYBE``: neither was established. A failed search for a witness is
  never read as disjointness.

Shapes. A shape is an anchor (``""`` for a relative path, ``"/"`` or
``"//"``) and a sequence of items, each either one segment drawn from a
regular language of strings, or a *run* of zero or more segments each drawn
from one. Segments are compared after normalisation, as ``render`` returns
them. The languages are built from the expression's terms:

- a literal segment is itself, a literal ``..`` included;
- a formatted segment (a template's literal text and fields) is the
  concatenation of its pieces' languages, less ``""``, ``"."`` and ``".."``,
  which no formatted segment renders (§4);
- a field whose parameter has a finite domain is the set of texts wend
  renders for its values. ``type=bool`` and an ``Enum`` type are finite
  under the contract. ``choices=`` are not: membership is ``value in
  choices``, so ``1.0`` and ``True`` pass for ``choices={1}`` (and render
  as ``1.0`` and ``True``), and a ``str`` subclass equal to a choice may
  format however it likes. Choices are finite only with
  ``builtin_values=True``, where each stands for itself and the builtin
  numbers equal to it. Where every parameter of a segment is finite and
  the product is small, the segment is the exact set of its renderings,
  so repeated parameters inside it are exact too;
- any other field is every string without ``/`` or NUL, without ``.`` when
  the field's facts guarantee that (§4), and non-empty when they guarantee
  that. Under the contract that is all an integer-formatted field
  guarantees: an ``int`` subclass may format as letters. With
  ``builtin_values=True`` the analysis assumes bound values are of builtin
  types (``str``, ``int``, ``float``, ``complex``, ``bool``, ``None``,
  pathlib paths), so ``{n:04d}`` is at least four characters of its
  presentation type's alphabet. Results that relied on it list
  ``"builtin_values"`` in ``assumptions``;
- a ``SubPath`` is a run of segments other than ``.`` and ``..`` (§3), or,
  with ``choices=``, the exact set of its values;
- a head parameter is any anchor and a run of any segments (``..``
  included), or with ``choices=`` the exact set; a deferred head
  (``parent`` of a ``SubPath``, say) is any path at all.

Bindings. By default the two expressions' parameters are independent: the
question is whether some binding of ``a`` and some binding of ``b`` render
one path. With ``shared=True`` a parameter name common to both takes one
value, as the paths of one `wend.Step`, or of steps run with the same
bindings, do; a witness then needs readings that agree on every common
name, and the abstraction (which ignores the correlation) can only prove
NO, never YES, on its own.

Both modes assume rendering is deterministic: the same bindings give the
same text (as ``match`` also assumes when it verifies a reading by rendering
it). That is what lets two segments that are one parameter's field with one
spec be required to agree.

Unions are handled alternative by alternative.
"""

from __future__ import annotations

import enum
import functools
import itertools
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from .._expr import (
    REL,
    Const,
    Deferred,
    Field,
    HeadParam,
    PathExpr,
    Root,
    Seg,
    Splice,
    _render_field,
    _render_pieces,
    check_seg,
)
from .._params import Kind, Param
from .._spec import INT_TYPES, parse_spec
from ..errors import NotInvertibleError, WendError


Verdict = Literal["yes", "no", "maybe"]

# Bounds on enumeration. Above them the analysis widens to a coarser shape
# (still sound) rather than enumerating.
MAX_DOMAIN = 256  # values of one finite parameter
MAX_SHAPES = 256  # shapes of one expression
MAX_SEGMENT_PRODUCT = 512  # renderings enumerated for one segment


# -- character sets and segment automata ---------------------------------------


@dataclass(frozen=True)
class Chars:
    """``chars``, or (``negated``) every character but ``chars``."""

    chars: frozenset[str]
    negated: bool = False

    def __and__(self, o: Chars) -> Chars:
        if self.negated and o.negated:
            return Chars(self.chars | o.chars, True)
        if self.negated:
            return Chars(o.chars - self.chars)
        if o.negated:
            return Chars(self.chars - o.chars)
        return Chars(self.chars & o.chars)

    def __bool__(self) -> bool:
        return self.negated or bool(self.chars)

    def __contains__(self, c: str) -> bool:
        return (c in self.chars) != self.negated

    def pick(self, prefer: str = "") -> str:
        """A member, preferring ``prefer``, then a plain letter."""
        for c in prefer:
            if c in self:
                return c
        if not self.negated:
            return min(self.chars)
        for c in "abcdefghijklmnopqrstuvwxyz0123456789_-":
            if c not in self.chars:
                return c
        n = 0x100
        while chr(n) in self.chars:
            n += 1
        return chr(n)


ANY = Chars(frozenset("/\x00"), negated=True)
EXCLUDED = ("", ".", "..")  # what no formatted segment renders


class NFA:
    """An automaton over characters: one start state, one accepting state,
    edges labelled by `Chars`, and epsilon edges."""

    def __init__(self) -> None:
        self.edges: list[list[tuple[Chars, int]]] = []
        self.eps: list[list[int]] = []

    def state(self) -> int:
        self.edges.append([])
        self.eps.append([])
        return len(self.edges) - 1

    def closure(self, states: Iterable[int]) -> frozenset[int]:
        seen = set(states)
        todo = list(seen)
        while todo:
            for t in self.eps[todo.pop()]:
                if t not in seen:
                    seen.add(t)
                    todo.append(t)
        return frozenset(seen)


@dataclass(frozen=True)
class Lang:
    """A language of segment texts.

    ``strings`` is set for a finite, exactly known language; otherwise
    ``nfa`` accepts a superset (``start`` to ``end``) and ``exclude`` lists
    texts removed from it.
    """

    strings: frozenset[str] | None = None
    nfa: NFA | None = field(default=None, compare=False)
    start: int = 0
    end: int = 0
    exclude: tuple[str, ...] = ()

    @staticmethod
    def finite(strings: Iterable[str]) -> Lang:
        return Lang(strings=frozenset(strings))

    def accepts(self, s: str) -> bool:
        if self.strings is not None:
            return s in self.strings
        if s in self.exclude:
            return False
        assert self.nfa is not None
        cur = self.nfa.closure([self.start])
        for c in s:
            nxt = [t for q in cur for cs, t in self.nfa.edges[q] if c in cs]
            cur = self.nfa.closure(nxt)
            if not cur:
                return False
        return self.end in cur


class _Builder:
    """Builds the automaton of a formatted segment from its pieces."""

    def __init__(self) -> None:
        self.nfa = NFA()
        self.start = self.end = self.nfa.state()

    def lit(self, s: str) -> None:
        for c in s:
            self.chars(Chars(frozenset(c)))

    def chars(self, cs: Chars) -> None:
        t = self.nfa.state()
        self.nfa.edges[self.end].append((cs, t))
        self.end = t

    def repeat(self, cs: Chars, lo: int, hi: int | None) -> None:
        for _ in range(lo):
            self.chars(cs)
        if hi is None:
            loop = self.nfa.state()
            self.nfa.eps[self.end].append(loop)
            self.nfa.edges[loop].append((cs, loop))
            self.end = loop
            return
        out = self.nfa.state()
        for _ in range(hi - lo):
            self.nfa.eps[self.end].append(out)
            self.chars(cs)
        self.nfa.eps[self.end].append(out)
        self.end = out

    def alternatives(self, strings: Iterable[str]) -> None:
        out = self.nfa.state()
        for s in strings:
            q = self.end
            for c in s:
                t = self.nfa.state()
                self.nfa.edges[q].append((Chars(frozenset(c)), t))
                q = t
            self.nfa.eps[q].append(out)
        self.end = out

    def either(self, *branches: Callable[[_Builder], None]) -> None:
        """Append the union of what each branch appends."""
        fork, out = self.end, self.nfa.state()
        for branch in branches:
            self.end = fork
            branch(self)
            self.nfa.eps[self.end].append(out)
        self.end = out

    def lang(self, exclude: tuple[str, ...]) -> Lang:
        return Lang(None, self.nfa, self.start, self.end, exclude)


def _nfa_view(lang: Lang) -> tuple[NFA, int, int]:
    """Any language as an automaton (a finite one is built on the fly)."""
    if lang.strings is None:
        assert lang.nfa is not None
        return lang.nfa, lang.start, lang.end
    b = _Builder()
    b.alternatives(sorted(lang.strings))
    return b.nfa, b.start, b.end


_NONDOT = Chars(frozenset("."), negated=True)


def _representatives(cs: Chars) -> list[str]:
    """One character of ``cs`` per class that matters: ``.`` and a non-dot.

    Automaton edges depend only on membership in their labels, and whether
    a text is excluded (``""``, ``"."``, ``".."``) only on which of its
    characters are dots, so these two stand for every character of ``cs``.
    """
    out = ["."] if "." in cs else []
    rest = cs & _NONDOT
    if rest:
        out.append(rest.pick("ax_"))
    return out


def _dots_after(dots: int | None, c: str) -> int | None:
    """Track whether a text is still ``""``, ``"."`` or ``".."`` (0, 1, 2)."""
    if dots is None or c != "." or dots == 2:
        return None
    return dots + 1


def intersect(a: Lang, b: Lang, limit: int = 1) -> list[str]:
    """Up to ``limit`` shortest texts in both languages; none means disjoint.

    Exact: a breadth-first search over (state of a, state of b, dots), a
    finite space, so it terminates without a length bound, and each state
    is expanded at most ``limit`` times, which keeps every reachable state
    reachable.
    """
    if a.strings is not None and b.strings is not None:
        return sorted(a.strings & b.strings, key=lambda s: (len(s), s))[:limit]
    if a.strings is not None or b.strings is not None:
        finite, other = (a, b) if a.strings is not None else (b, a)
        assert finite.strings is not None
        hits = [s for s in finite.strings if other.accepts(s)]
        return sorted(hits, key=lambda s: (len(s), s))[:limit]
    excluded = set(a.exclude) | set(b.exclude)
    na, sa, ea = _nfa_view(a)
    nb, sb, eb = _nfa_view(b)
    visits: dict[tuple[int, int, int | None], int] = {}
    queue: deque[tuple[int, int, int | None, str]] = deque([(sa, sb, 0, "")])
    out: list[str] = []
    while queue:
        qa, qb, dots, text = queue.popleft()
        key = (qa, qb, dots)
        if visits.get(key, 0) >= limit:
            continue
        visits[key] = visits.get(key, 0) + 1
        if qa == ea and qb == eb and (dots is None or EXCLUDED[dots] not in excluded):
            if text not in out:
                out.append(text)
                if len(out) >= limit:
                    break
        for ta in na.eps[qa]:
            queue.append((ta, qb, dots, text))
        for tb in nb.eps[qb]:
            queue.append((qa, tb, dots, text))
        for csa, ta in na.edges[qa]:
            for csb, tb in nb.edges[qb]:
                for c in _representatives(csa & csb):
                    queue.append((ta, tb, _dots_after(dots, c), text + c))
    return sorted(out, key=lambda s: (len(s), s))


def intersect_all(langs: list[Lang], limit: int = 1) -> list[str]:
    """Up to ``limit`` shortest texts in every language of ``langs`` (exact,
    as `intersect`)."""
    if len(langs) == 1:
        langs = [langs[0], langs[0]]
    if len(langs) == 2:
        return intersect(langs[0], langs[1], limit)
    finite = [x for x in langs if x.strings is not None]
    if finite:
        pool = set.intersection(*(set(x.strings or ()) for x in finite))
        hits = [t for t in pool if all(x.accepts(t) for x in langs)]
        return sorted(hits, key=lambda t: (len(t), t))[:limit]
    excluded = set().union(*(x.exclude for x in langs))
    views = [_nfa_view(x) for x in langs]
    start = tuple(v[1] for v in views)
    visits: dict[tuple[tuple[int, ...], int | None], int] = {}
    queue: deque[tuple[tuple[int, ...], int | None, str]] = deque([(start, 0, "")])
    out: list[str] = []
    while queue:
        qs, dots, text = queue.popleft()
        key = (qs, dots)
        if visits.get(key, 0) >= limit:
            continue
        visits[key] = visits.get(key, 0) + 1
        if all(q == v[2] for q, v in zip(qs, views, strict=True)) and (
            dots is None or EXCLUDED[dots] not in excluded
        ):
            if text not in out:
                out.append(text)
                if len(out) >= limit:
                    break
        for k, (nfa, _, _) in enumerate(views):
            for t in nfa.eps[qs[k]]:
                queue.append(((*qs[:k], t, *qs[k + 1 :]), dots, text))
        # Character moves: every automaton takes one edge on the same character.
        options: list[list[tuple[Chars, int]]] = [
            v[0].edges[q] for v, q in zip(views, qs, strict=True)
        ]
        for combo in itertools.product(*options):
            cs = combo[0][0]
            for c_, _ in combo[1:]:
                cs = cs & c_
                if not cs:
                    break
            if not cs:
                continue
            nxt = tuple(t for _, t in combo)
            for c in _representatives(cs):
                queue.append((nxt, _dots_after(dots, c), text + c))
    return sorted(out, key=lambda t: (len(t), t))


# -- shapes -------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One segment from ``lang`` (``run=False``), or zero or more (``run``).

    ``var`` is set on a segment that is exactly one parameter's field with a
    static spec: its text is a function of that parameter's value (formatting
    is assumed deterministic), so two segments with the same ``var`` render
    the same text whenever the parameter takes one value.
    """

    lang: Lang
    run: bool = False
    var: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class Shape:
    anchors: frozenset[str]
    items: tuple[Item, ...]


ALL_ANCHORS = frozenset({"", "/", "//"})


def _any_segment(exclude: tuple[str, ...]) -> Lang:
    b = _Builder()
    b.repeat(ANY, 1, None)
    return b.lang(exclude)


SUBPATH_SEGMENT = _any_segment(EXCLUDED)
PATH_SEGMENT = _any_segment(("", "."))  # a PATH value's segments may be ".."
TOP = Shape(ALL_ANCHORS, (Item(PATH_SEGMENT, run=True),))


def _numeric_twins(c: Any) -> list[Any]:
    """The builtin numbers equal to ``c`` (so equal as choices: ``1 in {1.0}``
    and ``True in {1}`` hold), each of which renders its own way."""
    if not isinstance(c, (int, float, complex)) or isinstance(c, complex) and c.imag:
        return []
    real = c.real if isinstance(c, complex) else c
    if real != real or real in (float("inf"), float("-inf")):
        return [complex(real)] if not isinstance(c, complex) else [real]
    out: list[Any] = [float(real), complex(real)]
    if real == int(real):
        out.append(int(real))
        if real in (0, 1):
            out.append(bool(real))
        if real == 0:
            out += [-0.0, complex(-0.0)]
    return out


def _domain(p: Param, assumed: _Assumed | None = None) -> list[Any] | None:
    """Every value ``p`` accepts, when they are few and known.

    ``type=bool`` and an ``Enum`` type are exhaustive (neither has other
    instances). ``choices`` are not, under the contract alone: membership
    is ``value in choices``, so ``1.0`` and ``True`` are accepted for
    ``choices={1}`` and render as ``1.0`` and ``True``, and a ``str``
    subclass equal to a choice may format however it likes. With
    ``assumed.builtin`` (builtin values only) a choice stands for itself and
    the builtin numbers equal to it. With ``assumed`` None the same values
    are returned for searches, which verify what they find by rendering.
    """
    if p.type is bool:
        values: list[Any] = [False, True]
    elif isinstance(p.type, type) and issubclass(p.type, enum.Enum):
        values = list(p.type)
    elif p.choices is not None:
        if assumed is not None:
            if not assumed.builtin:
                return None
            assumed.used.add("builtin_values")
        values = list(p.choices)
        for c in list(values):
            for twin in _numeric_twins(c):
                if not any(
                    type(v) is type(twin) and repr(v) == repr(twin) for v in values
                ):
                    values.append(twin)
        if p.type is not None:
            values = [v for v in values if isinstance(v, p.type)]
    else:
        return None
    return values if len(values) <= MAX_DOMAIN else None


def _environments(
    params: Iterable[Param], cap: int, assumed: _Assumed | None = None
) -> list[dict[str, Any]] | None:
    """Every binding of ``params``, when each has a small domain and there
    are at most ``cap`` bindings; None otherwise. ``assumed`` as `_domain`."""
    names, domains = [], []
    size = 1
    for q in params:
        dom = _domain(q, assumed)
        if dom is None:
            return None
        size *= len(dom)
        if size > cap:
            return None
        names.append(q.name)
        domains.append(dom)
    return [
        dict(zip(names, combo, strict=True)) for combo in itertools.product(*domains)
    ]


def _segments(text: str) -> tuple[str, tuple[str, ...]]:
    p = PurePosixPath(text)
    anchor = p.anchor
    parts = p.parts[1:] if anchor else p.parts
    return anchor, tuple(parts)


def _literal_shape(text: str) -> Shape:
    anchor, segs = _segments(text)
    return Shape(frozenset({anchor}), tuple(Item(Lang.finite([s])) for s in segs))


class _Assumed:
    """Records the assumptions a shape relied on."""

    def __init__(self, builtin: bool) -> None:
        self.builtin = builtin
        self.used: set[str] = set()


def _int_chars(spec: Any) -> frozenset[str]:
    """The characters ``format(n, spec)`` can write for a builtin ``int``
    under an integer presentation type (or none): digits, a sign, the
    grouping character, the ``#`` prefix, hex letters for ``x``/``X``, and
    the fill character."""
    chars = set("0123456789+- ")
    if spec.grouping:
        chars.add(spec.grouping)
    t = spec.type or "d"
    if t == "x":
        chars |= set("abcdef")
    elif t == "X":
        chars |= set("ABCDEF")
    if spec.alt and t != "d":
        chars.add(t)  # the 0x, 0X, 0o, 0b prefix
    chars.add(spec.padding(numeric=True)[0])
    return frozenset(chars)


def _field_lang(b: _Builder, f: Field, assumed: _Assumed) -> None:
    """Append field ``f``'s language to ``b``."""
    src = f.source
    if isinstance(src, Param):
        dom = _domain(src, assumed) if f.static_spec is not None else None
        if dom is not None:
            texts = set()
            for v in dom:
                try:
                    texts.add(_render_field(f, {src.name: v}))
                except WendError, ValueError:
                    pass
            b.alternatives(sorted(texts))
            return
    elif isinstance(src, Const) and f.static_spec is not None:
        try:
            b.lit(_render_field(f, {}))
            return
        except WendError, ValueError:
            b.alternatives([])  # it never renders
            return
    if f.role == "segment":
        # A whole-segment parameter: its value as is, or formatted as ``{v}``.
        dot_free, non_empty, static = False, True, ""
    else:
        (dot_free, non_empty), static = f.facts, f.static_spec
    cs = ANY & Chars(frozenset("."), negated=True) if dot_free else ANY
    lo = 1 if non_empty else 0
    hi: int | None = None
    spec = parse_spec(static) if static is not None else None
    if assumed.builtin and spec is not None and f.conversion is None:
        declared = src.type if isinstance(src, Param) else None
        integer = spec.type in INT_TYPES or (spec.type is None and declared is int)
        if integer and declared in (None, int):
            # ``bool`` is a builtin int: ``format(True, "")`` is ``True``
            # (any other spec formats it as 1), so a parameter's renderings
            # of it join the integers'.
            bools = []
            if isinstance(src, Param):
                for v in (False, True):
                    try:
                        bools.append(_render_field(f, {src.name: v}))
                    except WendError, ValueError:
                        pass
            ints, at_least = Chars(_int_chars(spec)), max(lo, spec.width or 1)
            b.either(
                lambda b: b.repeat(ints, at_least, None),
                lambda b: b.alternatives(bools),
            )
            assumed.used.add("builtin_values")
            return
        elif declared is str and spec.type in (None, "s"):
            lo = max(lo, spec.width or 0)
            if spec.precision is not None:
                hi = max(spec.precision, spec.width or 0)
            assumed.used.add("builtin_values")
    b.repeat(cs, lo, hi)


def _seg_lang(seg: Seg, assumed: _Assumed) -> Lang:
    lit = seg.literal
    if lit is not None:
        return Lang.finite([lit])
    # Every parameter of the segment with a small known domain: enumerate the
    # renderings, which is exact (repeated parameters included).
    params: dict[str, Param] = {}
    for p in seg.pieces:
        if isinstance(p, Field):
            if isinstance(p.source, Param):
                params[p.source.name] = p.source
            params.update({s.name: s for s in p.spec if isinstance(s, Param)})
            if not isinstance(p.source, (Param, Const)):
                params = {}
                break
    envs = (
        _environments(params.values(), MAX_SEGMENT_PRODUCT, assumed) if params else None
    )
    if envs is not None:
        texts = set()
        for env in envs:
            try:
                texts.add(check_seg(_render_pieces(seg.pieces, env)))
            except WendError, ValueError:
                pass
        return Lang.finite(texts)
    b = _Builder()
    for p in seg.pieces:
        if isinstance(p, str):
            b.lit(p)
        else:
            _field_lang(b, p, assumed)
    return b.lang(EXCLUDED)


def _var(seg: Seg) -> tuple[Any, ...] | None:
    """The equality key of a segment that is one field of one parameter."""
    if len(seg.pieces) != 1 or not isinstance(seg.pieces[0], Field):
        return None
    f = seg.pieces[0]
    if not isinstance(f.source, Param) or f.static_spec is None:
        return None
    return (f.source.name, f.role, f.conversion, f.static_spec)


def _name_lang(pieces: tuple[Any, ...], assumed: _Assumed) -> Lang:
    """The language of a name given as text pieces (``with_name``)."""
    return _seg_lang(Seg(tuple(pieces)), assumed) if pieces else Lang.finite([])


def _rename(shape: Shape, last: Any) -> list[Shape]:
    """Shapes of every path of ``shape`` with its last segment replaced, where
    ``last(item)`` gives the new last item for an old one, or None if the old
    one cannot be renamed. A run at the end may be empty, so the segment
    replaced may come from before it."""
    items = shape.items
    if not items:
        return []  # "." and "/" have no name to replace (pathlib raises)
    *rest, end = items
    if not end.run:
        new = last(end)
        return [] if new is None else [Shape(shape.anchors, (*rest, new))]
    new = last(Item(end.lang))
    out = [] if new is None else [Shape(shape.anchors, (*rest, end, new))]
    return out + _rename(Shape(shape.anchors, tuple(rest)), last)


def _deferred_shapes(d: Deferred, assumed: _Assumed) -> list[Shape]:
    """Shapes of a deferred operation, from its base's shapes where the
    operation's effect on them is known; any path otherwise."""
    base, used = shapes(d.base, builtin_values=assumed.builtin)
    assumed.used |= used
    if d.op == "parent":

        def parents(shape: Shape) -> list[Shape]:
            if not shape.items:
                return [shape]  # the parent of "." is ".", of "/" is "/"
            *rest, end = shape.items
            up = Shape(shape.anchors, tuple(rest))
            # A final run of one or more segments loses one and stays a run;
            # an empty one leaves the parent of what precedes it.
            return [shape, *parents(up)] if end.run else [up]

        return [x for b in base for x in parents(b)]
    if d.op == "with_name":
        name = _name_lang(tuple(d.arg.pieces), assumed)
        return [x for b in base for x in _rename(b, lambda _: Item(name))]
    if d.op == "with_suffix":
        suffix = d.arg

        def replaced(item: Item) -> Item | None:
            if item.lang.strings is not None:
                texts = set()
                for t in item.lang.strings:
                    try:
                        texts.add(PurePosixPath(t).with_suffix(suffix).name)
                    except ValueError:
                        pass
                return Item(Lang.finite(texts))
            b = _Builder()
            b.repeat(ANY, 0 if suffix else 1, None)
            b.lit(suffix)
            return Item(b.lang(EXCLUDED))

        return [x for b in base for x in _rename(b, replaced)]
    if d.op == "with_stem":
        pieces = tuple(d.arg.pieces)
        literal = pieces[0] if len(pieces) == 1 and isinstance(pieces[0], str) else None

        def restemmed(item: Item) -> Item | None:
            if literal is not None and item.lang.strings is not None:
                texts = set()
                for t in item.lang.strings:
                    try:
                        texts.add(PurePosixPath(t).with_stem(literal).name)
                    except ValueError:
                        pass
                return Item(Lang.finite(texts))
            return Item(_any_segment(EXCLUDED))

        return [x for b in base for x in _rename(b, restemmed)]
    return [TOP]  # join (an AnyPath operand) and relative_to


def shapes(
    e: PathExpr, *, builtin_values: bool = False
) -> tuple[list[Shape], frozenset[str]]:
    """Shapes containing every path ``e`` can render, and the assumptions used."""
    assumed = _Assumed(builtin_values)
    h = e.head
    heads: list[Shape]
    if h is REL:
        heads = [Shape(frozenset({""}), ())]
    elif isinstance(h, Root):
        heads = [Shape(frozenset({h.anchor}), ())]
    elif isinstance(h, HeadParam):
        dom = _domain(h.param, assumed)
        if dom is not None:
            heads = []
            for v in dom:
                try:
                    heads.append(_literal_shape(PathExpr(h).render({h.param.name: v})))
                except WendError, ValueError:
                    pass
        elif h.param.kind is Kind.ABSOLUTE:
            heads = [Shape(frozenset({"/", "//"}), (Item(PATH_SEGMENT, run=True),))]
        else:
            heads = [TOP]
    else:
        assert isinstance(h, Deferred)
        if not PathExpr(h).param_names:
            heads = [_literal_shape(PathExpr(h).render())]
        else:
            heads = _deferred_shapes(h, assumed)
    # Each part multiplies the shapes by its alternatives.
    alternatives: list[list[tuple[Item, ...]]] = []
    for part in e.parts:
        if isinstance(part, Seg):
            alternatives.append([(Item(_seg_lang(part, assumed), var=_var(part)),)])
            continue
        assert isinstance(part, Splice)
        dom = _domain(part.param, assumed)
        values: list[tuple[Item, ...]] = []
        if dom is not None:
            for v in dom:
                try:
                    text = PathExpr(REL, (part,)).render({part.param.name: v})
                except WendError, ValueError:
                    continue
                values.append(tuple(Item(Lang.finite([s])) for s in _segments(text)[1]))
        alternatives.append(
            values if dom is not None else [(Item(SUBPATH_SEGMENT, run=True),)]
        )
    count = len(heads)
    for alts in alternatives:
        count *= max(len(alts), 1)
    if count > MAX_SHAPES:
        # Widen each finite part to its unrestricted form, which is a superset.
        alternatives = [
            alts if len(alts) == 1 else [(Item(SUBPATH_SEGMENT, run=True),)]
            for alts in alternatives
        ]
        if len(heads) > MAX_SHAPES:
            heads = [TOP]
    out = []
    for head in heads:
        for combo in itertools.product(*alternatives):
            items = head.items + tuple(i for chunk in combo for i in chunk)
            out.append(Shape(head.anchors, items))
    return out, frozenset(assumed.used)


# -- aligning two shapes ------------------------------------------------------


def _alignments(a: Shape, b: Shape, limit: int) -> Iterator[list[str]]:
    """Alignments of ``a`` and ``b`` in which every aligned pair of segments
    has a common text, each as the list of those texts, up to ``limit``.
    None at all means no path is in both shapes.

    Moves from (i, j): a run skips (it takes no more segments); a run takes
    the other side's next single segment; two single segments pair up. A
    run never needs to share a segment with the other side's run: removing a
    segment both runs take leaves a path both shapes still contain. Every
    move advances i + j, so the search terminates.
    """
    na, nb = len(a.items), len(b.items)
    common: dict[tuple[int, int, int], list[str]] = {}

    def texts(x: Item, y: Item, k: int) -> list[str]:
        key = (id(x.lang), id(y.lang), k)
        if key not in common:
            common[key] = intersect(x.lang, y.lang, limit=k)
        return common[key]

    def moves(i: int, j: int, k: int) -> Iterator[tuple[int, int, str | None]]:
        x = a.items[i] if i < na else None
        y = b.items[j] if j < nb else None
        if x is not None and x.run:
            yield i + 1, j, None
        if y is not None and y.run:
            yield i, j + 1, None
        if x is None or y is None or (x.run and y.run):
            return
        ni, nj = (i, j + 1) if x.run else (i + 1, j) if y.run else (i + 1, j + 1)
        for s in texts(x, y, k):
            yield ni, nj, s

    feasible: dict[tuple[int, int], bool] = {}

    def ok(i: int, j: int) -> bool:
        if (i, j) not in feasible:
            feasible[i, j] = (i == na and j == nb) or any(
                ok(ni, nj) for ni, nj, _ in moves(i, j, 1)
            )
        return feasible[i, j]

    if not ok(0, 0):
        return
    found = 0

    def walk(i: int, j: int, acc: list[str]) -> Iterator[list[str]]:
        nonlocal found
        if i == na and j == nb:
            found += 1
            yield list(acc)
            return
        for ni, nj, s in moves(i, j, 2):
            if found >= limit:
                return
            if ok(ni, nj):
                yield from walk(ni, nj, acc if s is None else [*acc, s])

    yield from walk(0, 0, [])


# -- the analysis ---------------------------------------------------------------


@dataclass(frozen=True)
class Witness:
    """A path both expressions render, with a binding of each that does."""

    path: str
    a: dict[str, Any]
    b: dict[str, Any]


@dataclass(frozen=True)
class Overlap:
    verdict: Verdict
    witness: Witness | None = None
    reason: str = ""
    assumptions: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        """True unless the expressions are proved disjoint."""
        return self.verdict != "no"


def _alternatives(x: Any) -> tuple[PathExpr, ...]:
    alts = getattr(x, "alternatives", None)
    if alts is not None:
        return tuple(alts)
    if isinstance(x, PathExpr):
        return (x,)
    from .._expr import P

    return (P(x),)


MAX_RENDER_SEARCH = 4096  # bindings tried when matching cannot verify a path


def _through_operation(e: PathExpr, path: str, limit: int) -> list[dict[str, Any]]:
    """Bindings of a deferred ``e`` (an operation on a base expression) that
    render ``path``, found by matching the base against paths the operation
    could have started from, and kept only if ``e`` renders ``path`` from
    them. Only a search: finding none proves nothing."""
    h = e.head
    if (
        not isinstance(h, Deferred)
        or e.parts
        or h.op
        not in (
            "parent",
            "with_name",
            "with_stem",
            "with_suffix",
        )
    ):
        return []
    p = PurePosixPath(path)
    names = [w for w in _words(h.base) if "/" not in w] + ["w"]
    if h.op == "parent":
        starts = [p / w for w in names]
    elif h.op == "with_suffix":
        suffixes = {""} | {"." + w.rsplit(".", 1)[-1] for w in names if "." in w}
        starts = []
        for x in sorted(suffixes):
            try:
                starts.append(p.with_suffix(x))
            except ValueError:
                pass
    else:
        starts = (
            [p.with_name(w) for w in names if w not in (".", "..")] if p.name else []
        )
    out: list[dict[str, Any]] = []
    for start in starts:
        found = _readings(h.base, str(start), limit)
        for env in found or []:
            if _rendered(e, env) == str(p) and env not in out:
                out.append(env)
        if len(out) >= limit:
            break
    return out


def _readings(e: PathExpr, path: str, limit: int) -> list[dict[str, Any]] | None:
    """Bindings of ``e`` that render ``path``: from ``match_all``, or, where
    it finds none or cannot invert ``e``, by looking ``path`` up among the
    renderings of every binding when every parameter has a small finite
    domain (``match`` does not read every type back from text: an ``Enum``
    field, say), or through an operation of a deferred ``e``. None if none
    of these applies."""
    try:
        found = e.match_all(path, limit=limit)
    except NotInvertibleError:
        found = None
    if found:
        return found
    index = _render_index(e)
    if index is not None:
        return [dict(env) for env in index.get(str(PurePosixPath(path)), ())[:limit]]
    through = _through_operation(e, path, limit)
    if through:
        return through
    return found


def _render_index(e: PathExpr) -> dict[str, list[dict[str, Any]]] | None:
    """Every path ``e`` renders, with the bindings that render it, when every
    parameter has a small finite domain; None otherwise. Built once per
    expression: a search looks many paths up in it."""
    try:
        return _cached_render_index(e)
    except TypeError:  # an unhashable constant inside the expression
        return _build_render_index(e)


@functools.lru_cache(maxsize=256)
def _cached_render_index(e: PathExpr) -> dict[str, list[dict[str, Any]]] | None:
    return _build_render_index(e)


def _build_render_index(e: PathExpr) -> dict[str, list[dict[str, Any]]] | None:
    envs = _environments(e.params.values(), MAX_RENDER_SEARCH)
    if envs is None:
        return None
    index: dict[str, list[dict[str, Any]]] = {}
    for env in envs:
        path = _rendered(e, env)
        if path is not None:
            index.setdefault(path, []).append(env)
    return index


def overlaps(
    a: Any,
    b: Any,
    *,
    shared: bool = False,
    builtin_values: bool = False,
    witnesses: int = 32,
) -> Overlap:
    """Whether ``a`` and ``b`` (expressions or unions) can render one path.

    ``shared=True`` makes a parameter name common to both one variable.
    ``builtin_values=True`` assumes bound values are of builtin types
    (stronger NOs; see the module docstring). ``witnesses`` bounds the candidate paths tried for a YES.
    """
    results = [
        _overlap(x, y, shared, builtin_values, witnesses)
        for x in _alternatives(a)
        for y in _alternatives(b)
    ]
    for r in results:
        if r.verdict == "yes":
            return r
    maybes = [r for r in results if r.verdict == "maybe"]
    if maybes:
        return maybes[0]
    if len(results) == 1:
        return results[0]
    assumptions = frozenset().union(*(r.assumptions for r in results))
    return Overlap(
        "no", reason="every pair of alternatives is disjoint", assumptions=assumptions
    )


MAX_STRUCTURES = 64  # structural alignments enumerated per pair of shapes


def _structures(
    a: Shape, b: Shape, cap: int
) -> tuple[list[list[tuple[int, int]]], bool]:
    """Every structural alignment of ``a`` and ``b``: for each segment of the
    common path, the item of each side that renders it. Pairs of items are
    pruned by their languages' intersection (`_alignments`' moves). Returns
    the alignments and whether the list is complete (not cut at ``cap``)."""
    na, nb = len(a.items), len(b.items)
    pair_ok: dict[tuple[int, int], bool] = {}

    def meets(i: int, j: int) -> bool:
        if (i, j) not in pair_ok:
            pair_ok[i, j] = bool(intersect(a.items[i].lang, b.items[j].lang))
        return pair_ok[i, j]

    def moves(i: int, j: int) -> Iterator[tuple[int, int, tuple[int, int] | None]]:
        x = a.items[i] if i < na else None
        y = b.items[j] if j < nb else None
        if x is not None and x.run:
            yield i + 1, j, None
        if y is not None and y.run:
            yield i, j + 1, None
        if x is None or y is None or (x.run and y.run) or not meets(i, j):
            return
        if x.run:
            yield i, j + 1, (i, j)
        elif y.run:
            yield i + 1, j, (i, j)
        else:
            yield i + 1, j + 1, (i, j)

    reach: dict[tuple[int, int], bool] = {}

    def ok(i: int, j: int) -> bool:
        if (i, j) not in reach:
            reach[i, j] = (i == na and j == nb) or any(
                ok(ni, nj) for ni, nj, _ in moves(i, j)
            )
        return reach[i, j]

    out: list[list[tuple[int, int]]] = []
    complete = True

    def walk(i: int, j: int, acc: list[tuple[int, int]]) -> None:
        nonlocal complete
        if len(out) >= cap:
            complete = False
            return
        if i == na and j == nb:
            out.append(list(acc))
            return
        for ni, nj, seg in moves(i, j):
            if ok(ni, nj):
                walk(ni, nj, acc if seg is None else [*acc, seg])

    if ok(0, 0):
        walk(0, 0, [])
    return out, complete


def _solve(
    a: Shape, b: Shape, segs: list[tuple[int, int]], common: frozenset[str], k: int
) -> list[list[str]] | None:
    """Texts for the segments of one alignment, honouring equal ``var`` keys:
    up to ``k`` choices per group of segments that must be equal, or None if
    some group has no common text (the alignment is impossible)."""
    parent = list(range(len(segs)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[tuple[Any, ...], int] = {}
    for n, (i, j) in enumerate(segs):
        for side, item in (("a", a.items[i]), ("b", b.items[j])):
            if item.var is None:
                continue
            who = "*" if item.var[0] in common else side
            key = (who, *item.var)
            if key in owner:
                parent[find(n)] = find(owner[key])
            else:
                owner[key] = n
    groups: dict[int, list[int]] = {}
    for n in range(len(segs)):
        groups.setdefault(find(n), []).append(n)
    text_of: dict[int, list[str]] = {}
    for root, members in groups.items():
        langs = []
        for n in members:
            i, j = segs[n]
            langs += [a.items[i].lang, b.items[j].lang]
        found = intersect_all(langs, limit=k)
        if not found:
            return None
        text_of[root] = found
    return [text_of[find(n)] for n in range(len(segs))]


def _pools(params: list[Param], words: list[str]) -> list[list[Any]]:
    """Sample values per parameter: its domain when small, else typed
    samples and ``words`` (with pairs of them for a SubPath, whose values
    may have several segments)."""
    pools = []
    for q in params:
        dom = _domain(q)
        if dom is not None:
            pools.append(dom)
        elif q.type is int:
            pools.append([0, 1, 7, 42, 100, 2026, -1, False, True])
        elif q.type is float:
            pools.append([0.5, 1.0, 2.5])
        elif q.kind is Kind.ABSOLUTE:
            pools.append(["/", "/a", *("/" + w for w in words if "/" not in w)])
        elif q.kind is Kind.SUBPATH:
            pairs = [f"{x}/{y}" for x in words[:4] for y in words[:4]]
            pools.append([".", *words, "a", "a/b", *pairs])
        elif q.kind in (Kind.AUTO, Kind.PATH):
            # Possibly a head (absolute or not), possibly untyped: any
            # builtin value formats.
            pools.append([*words, "a", "1", "x.y", "/a", "/", 2.5, True])
        else:
            pools.append([*words, "a", "1", "x.y"])
    return pools


def _samples(
    params: list[Param], words: list[str], limit: int
) -> Iterator[dict[str, Any]]:
    """Up to ``limit`` environments of sample values: the i-th sample of every
    parameter first, then their product."""
    pools = _pools(params, words)
    longest = max((len(x) for x in pools), default=1)
    combos = itertools.chain(
        (tuple(x[i % len(x)] for x in pools) for i in range(longest)),
        itertools.product(*pools),
    )
    for combo in itertools.islice(combos, limit):
        yield {q.name: v for q, v in zip(params, combo, strict=True)}


def _rendered(e: PathExpr, env: dict[str, Any]) -> str | None:
    try:
        return e.render(env)
    except WendError, ValueError:
        return None


def _words(*exprs: PathExpr) -> list[str]:
    """Literal segments and literal fragments of the expressions, as sample
    values: a parameter often takes text the other side spells out."""
    out: list[str] = []

    def add(w: str) -> None:
        if w and w not in out:
            out.append(w)

    for e in exprs:
        for part in e.parts:
            if isinstance(part, Seg):
                for piece in part.pieces:
                    if isinstance(piece, str):
                        add(piece)
                        for bit in piece.replace("-", ".").replace("_", ".").split("."):
                            add(bit)
    return out[:16]


@functools.lru_cache(maxsize=4096)
def _cached_shapes(e: PathExpr, builtin: bool) -> tuple[list[Shape], frozenset[str]]:
    return shapes(e, builtin_values=builtin)


def _shapes_of(e: PathExpr, builtin: bool) -> tuple[list[Shape], frozenset[str]]:
    """`shapes`, cached: a graph compares each expression with many others,
    and shapes depend only on the expression's structure."""
    try:
        return _cached_shapes(e, builtin)
    except TypeError:  # an unhashable constant inside the expression
        return shapes(e, builtin_values=builtin)


def _overlap(
    a: PathExpr, b: PathExpr, shared: bool, builtin: bool, witnesses: int
) -> Overlap:
    sa, used_a = _shapes_of(a, builtin)
    sb, used_b = _shapes_of(b, builtin)
    assumptions = used_a | used_b
    common = a.param_names & b.param_names if shared else frozenset()
    candidates: list[str] = []

    def add(path: str) -> None:
        if path not in candidates:
            candidates.append(path)

    any_shapes_meet = False
    any_structure = False
    all_complete = True
    for x in sa:
        for y in sb:
            anchors = x.anchors & y.anchors
            if not anchors:
                continue
            structures, complete = _structures(x, y, MAX_STRUCTURES)
            all_complete &= complete
            any_structure |= bool(structures)
            for segs in structures:
                choices = _solve(x, y, segs, common, 2)
                if choices is None:
                    continue
                any_shapes_meet = True
                for picked in itertools.islice(itertools.product(*choices), 4):
                    for anchor in sorted(anchors):
                        add((anchor + "/".join(picked)) or ".")
    if not any_shapes_meet and all_complete:
        why = (
            "the shapes intersect only where a repeated parameter would take two values"
            if any_structure
            else "no shapes of the two intersect"
        )
        return Overlap("no", reason=why, assumptions=assumptions)
    # Candidates rendered from sample values carry the binding that renders
    # them, so they need no matching on that side. With shared bindings, both
    # sides rendered from one environment are compared directly.
    words = _words(a, b)
    known: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]] = {}
    params_a = sorted(a.params.values(), key=lambda q: q.name)
    params_b = sorted(b.params.values(), key=lambda q: q.name)
    for env in _samples(params_a, words, 48):
        path = _rendered(a, env)
        if path is not None:
            add(path)
            known.setdefault(path, (env, None))
    for env in _samples(params_b, words, 48):
        path = _rendered(b, env)
        if path is not None:
            add(path)
            ea = known.get(path, (None, None))[0]
            known[path] = (ea, env)
    if shared:
        joint = {q.name: q for q in [*params_a, *params_b]}
        for env in _samples(sorted(joint.values(), key=lambda q: q.name), words, 96):
            pa = _rendered(a, env)
            if pa is not None and pa == _rendered(b, env):
                ua = {k: env[k] for k in a.param_names}
                ub = {k: env[k] for k in b.param_names}
                return Overlap(
                    "yes",
                    Witness(pa, ua, ub),
                    "one binding renders the same path from both",
                )
    # YES needs a verified witness; it does not depend on any assumption.
    inverted = True
    # Sampled candidates first: their texts come from real values, so the
    # witness reads naturally; then the shortest texts the shapes allow.
    ordered = [c for c in candidates if c in known] + [
        c for c in candidates if c not in known
    ]
    for path in ordered[: witnesses * 4]:
        ka, kb = known.get(path, (None, None))
        ra = [ka] if ka is not None else _readings(a, path, 8)
        rb = [kb] if kb is not None else _readings(b, path, 8)
        if ra is None or rb is None:
            inverted = False
            continue
        for u in ra:
            for v in rb:
                if all(u[k] == v[k] and type(u[k]) is type(v[k]) for k in common):
                    return Overlap(
                        "yes", Witness(path, u, v), "a witness renders from both"
                    )
    if not any_shapes_meet:
        reason = "too many alignments to rule out, and none verified"
    elif inverted:
        reason = "the shapes intersect, but no candidate path was verified"
    else:
        reason = "the shapes intersect, and an expression could not be matched to verify a candidate"
    if shared and common:
        reason += " (with the shared parameters agreeing)"
    return Overlap("maybe", reason=reason, assumptions=assumptions)
