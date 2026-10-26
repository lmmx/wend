"""Relations between path families (docs/SEMANTICS.md §15).

`relate(a, b)` says whether two expressions name the same path, one inside
the other, or neither, for every binding, for some, or for none, before any
binding exists. Paths are compared as the strings they render (lexically),
not as filesystem objects: two strings can name one file. Three questions,
each answered ``"always"``, ``"sometimes"``, ``"never"`` or ``"unknown"``:

- ``same``: ``a`` and ``b`` render one path;
- ``inside``: ``a``'s path lies strictly below ``b``'s;
- ``contains``: ``a``'s path lies strictly above ``b``'s.

The proofs, in order:

1. *Anchors*. Paths with different anchors (relative, ``/``, ``//``) never
   meet nor nest.
2. *Views*. A name changed by ``with_name``, ``with_suffix`` or ``with_stem``
   and deferred until binding is its base's parent and one segment, of which
   the operation fixes the name, the suffix or the stem (`_view`). Reasoning
   on the view proves "never" and depth; "sometimes" needs a binding of the
   expressions themselves.
3. *Structure*. Two pieces of normal form that are equal, with parameters
   compared by name, render the same text for one binding: a parameter's
   declaration (type, choices, kind) decides which bindings are accepted,
   never what an accepted one renders. A deferred head is pathlib applied to
   what its base renders, so it is no exception. Under shared bindings a
   common prefix of head and parts therefore renders one string, unless a
   name in it has a different default on each side, and joining it onto a
   relative remainder is injective and keeps "lies above", so ``a`` and
   ``b`` relate exactly as their remainders do. Empty remainders, or one
   empty and the other holding a segment, decide the relation for every
   binding ("always" and "never").
4. *Divergence and depth*. Remainders whose first parts are different
   literal segments never meet and never nest. Remainders of segments alone
   render fixed numbers of segments, one each: different numbers never
   meet, equal numbers never nest.
5. *Overlap*. Otherwise each question is asked of `wend._overlap` about the
   remainders: its NO is "never", its YES a witness ("sometimes"), its MAYBE
   "unknown".

Every "always" and "sometimes" comes with an `Example` when one is found: the
bindings, and the paths each side renders.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal, TypeGuard

from . import _overlap
from ._expr import (
    _NAME_OPS,
    REL,
    Const,
    Deferred,
    Field,
    HeadParam,
    PathExpr,
    Root,
    Seg,
    Splice,
    _norm,
    _Rel,
)
from ._params import Kind as ParamKind
from ._params import Param, SubPath
from .errors import WendError


Certainty = Literal["always", "sometimes", "never", "unknown"]
How = Literal["same", "inside", "contains"]
Summary = Literal["same", "inside", "contains", "disjoint", "overlapping", "unknown"]
_HOWS: tuple[How, ...] = ("same", "inside", "contains")


@dataclass(frozen=True)
class Example:
    """Bindings under which a relation shows, and the paths each side renders
    with them. Under shared bindings the two bindings agree on every common
    name."""

    how: How
    a_path: str
    b_path: str
    a_bindings: dict[str, Any]
    b_bindings: dict[str, Any]

    def __repr__(self) -> str:
        return f"Example({self.how}: {self.a_path!r} ~ {self.b_path!r})"


@dataclass(frozen=True)
class Relation:
    """How two path families relate (docs/SEMANTICS.md §15).

    ``same``, ``inside`` and ``contains`` are each ``"always"`` (for every
    binding under which both render), ``"sometimes"`` (for one at least: see
    ``examples``), ``"never"``, or ``"unknown"`` (neither was proved).
    ``inside`` is ``a`` strictly below ``b``; ``contains``, strictly above.
    Each compares the rendered strings, not the files they may name.
    """

    same: Certainty
    inside: Certainty
    contains: Certainty
    shared: bool = True
    examples: tuple[Example, ...] = ()
    assumptions: frozenset[str] = frozenset()

    def __getitem__(self, how: How) -> Certainty:
        return getattr(self, how)

    @property
    def kind(self) -> Summary:
        """The relation in one word: ``"same"``, ``"inside"`` or ``"contains"``
        when that holds always; ``"disjoint"`` when the paths never meet nor
        nest; ``"overlapping"`` when some binding shows one of the three;
        else ``"unknown"``."""
        for how in _HOWS:
            if self[how] == "always":
                return how
        if all(self[how] == "never" for how in _HOWS):
            return "disjoint"
        if any(self[how] == "sometimes" for how in _HOWS):
            return "overlapping"
        return "unknown"

    @property
    def disjoint(self) -> bool:
        """Whether the two rendered paths never meet nor nest, as strings: no
        path is both, nor one inside the other. Two spellings of one file
        (a symlink, ``..``, a relative and an absolute path) are not seen."""
        return self.kind == "disjoint"

    def __bool__(self) -> bool:
        """True unless the two are proved disjoint: they may meet or nest."""
        return not self.disjoint

    def __repr__(self) -> str:
        return (
            f"Relation({self.kind}: same={self.same!r}, inside={self.inside!r},"
            f" contains={self.contains!r})"
        )


def either(*certainties: Certainty) -> Certainty:
    """The certainty that at least one of several relations holds."""
    if "always" in certainties:
        return "always"
    if all(c == "never" for c in certainties):
        return "never"
    if "sometimes" in certainties:
        return "sometimes"
    return "unknown"


# -- the normal form, compared ---------------------------------------------------


def _same_value(x: Any, y: Any) -> bool:
    if type(x) is not type(y):
        return False
    try:
        return bool(x == y) and repr(x) == repr(y)
    except Exception:  # noqa: BLE001 (an arbitrary value's __eq__)
        return False


def _conflicting_defaults(a: PathExpr, b: PathExpr) -> frozenset[str]:
    """Names both expressions give a default, but not the same one: unbound,
    each renders its own."""
    pa, pb = a.params, b.params
    if len(pa) > len(pb):
        pa, pb = pb, pa
    return frozenset(
        n
        for n, p in pa.items()
        if p.has_default
        and n in pb
        and pb[n].has_default
        and not _same_value(p.default, pb[n].default)
    )


class Memo(dict[int, tuple[Any, Any]]):
    """Keys already computed, by the identity of their piece. ``builtin`` keys
    plain fields by their parameter alone (`_plain_field`)."""

    def __init__(self, builtin: bool = False) -> None:
        super().__init__()
        self.builtin = builtin
        self._names: dict[Any, str] = {}
        self._reserved: set[str] = set()

    def reserve(self, names: Iterable[str]) -> None:
        """Keep ``names`` (the parameters of the expressions compared) from
        being given to a view's text or a parent's SubPath."""
        names = set(names)
        clash = names & set(self._names.values())
        if clash:
            raise ValueError(f"names already given to a view: {sorted(clash)}")
        self._reserved |= names

    def name(self, prefix: str, key: Any) -> str:
        """A parameter name for what ``key`` renders: one name per key, none of
        the reserved ones, and numbered in the order first asked, so answers do
        not depend on string hashing."""
        if (prefix, key) not in self._names:
            n = len(self._names)
            while f"{prefix}{n}" in self._reserved:
                n += 1
            name = f"{prefix}{n}"
            self._reserved.add(name)
            self._names[(prefix, key)] = name
        return self._names[(prefix, key)]


def _plain_field(f: Field) -> bool:
    """Whether ``f`` renders its parameter's value as ``str`` does: a
    segment-valued parameter, or a field with no format spec and no
    conversion other than ``!s``. For a value of a builtin type the two agree:
    ``os.fspath`` of a ``str`` or pathlib path is its ``str``, and
    ``format(v, "")`` is ``str(v)``."""
    return (
        isinstance(f.source, Param)
        and f.conversion in (None, "s")
        and f.static_spec == ""
    )


def _key(x: Any, memo: Memo) -> Any:
    """What decides the text a piece of normal form renders for a binding: its
    structure, with parameters by name. Equal keys render equal text."""
    hit = memo.get(id(x))
    if hit is not None and hit[0] is x:
        return hit[1]
    if isinstance(x, Param):
        key: Any = ("param", x.name)
    elif isinstance(x, Field) and memo.builtin and _plain_field(x):
        # Assuming builtin values, a plain field renders its value's str in
        # either role, wherever it renders (§15.3, 1).
        key = ("plain", _key(x.source, memo))
    elif isinstance(x, PathExpr):
        key = ("expr", _key(x.head, memo), tuple(_key(p, memo) for p in x.parts))
    elif isinstance(x, Const):
        key = ("const", _value_key(x.value))
    elif isinstance(x, tuple):
        key = ("tuple", *(_key(p, memo) for p in x))
    elif dataclasses.is_dataclass(x) and not isinstance(x, type):
        key = (
            type(x),
            *(_key(getattr(x, f.name), memo) for f in dataclasses.fields(x)),
        )
    else:
        key = _value_key(x)
    memo[id(x)] = (x, key)
    return key


def _value_key(v: Any) -> Any:
    """Values render alike when they are of one type, equal, and print alike
    (``0.0`` and ``-0.0`` do not); an unhashable value only as itself."""
    try:
        hash(v)
    except TypeError:
        return ("id", type(v), id(v))
    try:
        return ("value", type(v), v, repr(v))
    except Exception:  # noqa: BLE001 (an arbitrary value's __repr__)
        return ("id", type(v), id(v))


def _fresh_key(x: Any, memo: Memo) -> Any:
    """What decides the text ``x`` renders under shared bindings, unbound
    names included: its key, and each parameter's default. A name wend makes
    up for that text (a view's, a parent's SubPath) is fixed by this, so two
    sides tie it only where they render one text: a name with a different
    default on each side renders each side's own when unbound."""
    params = PathExpr(x).params if isinstance(x, Deferred) else x.params
    defaults = tuple(
        sorted(
            (n, _value_key(p.default) if p.has_default else ("none",))
            for n, p in params.items()
        )
    )
    return _key(x, memo), defaults


def _names(x: Any) -> frozenset[str]:
    if isinstance(x, HeadParam):
        return frozenset({x.param.name})
    if isinstance(x, Splice):
        return frozenset({x.param.name})
    if isinstance(x, Seg):
        return x.param_names
    if isinstance(x, Deferred):
        return PathExpr(x).param_names
    return frozenset()


def _roles(*es: PathExpr) -> dict[str, set[str]]:
    """The roles in which a plain field renders each name, over ``es``."""
    found: dict[str, set[str]] = {}
    stack: list[Any] = list(es)
    seen: set[int] = set()
    while stack:
        x = stack.pop()
        if id(x) in seen:
            continue
        seen.add(id(x))
        if isinstance(x, Field) and isinstance(x.source, Param) and _plain_field(x):
            found.setdefault(x.source.name, set()).add(x.role)
        if isinstance(x, tuple):
            stack.extend(x)
        elif dataclasses.is_dataclass(x) and not isinstance(x, type):
            stack.extend(getattr(x, f.name) for f in dataclasses.fields(x))
    return found


def _alike(x: Any, y: Any, bad: frozenset[str], memo: Memo) -> bool:
    """Whether two parts (or heads) render the same text for one binding:
    equal keys, and no name whose defaults differ."""
    return not (_names(x) & bad) and _key(x, memo) == _key(y, memo)


def _static(part: Any) -> TypeGuard[Seg]:
    return isinstance(part, Seg) and part.literal is not None


def _may_render_dotdot(e: PathExpr) -> bool:
    """Whether ``e`` may render a ``..`` segment: a literal one, or one from a
    head parameter or deferred head. Formatted segments and SubPaths never
    render one (§3, §4)."""
    if isinstance(e.head, (HeadParam, Deferred)):
        return True
    return any(_static(p) and p.literal == ".." for p in e.parts)


def _plain(e: PathExpr) -> PathExpr:
    """``e`` without its declarations, which never change what it renders."""
    return PathExpr(e.head, e.parts)


def _anchors(e: PathExpr) -> frozenset[str] | None:
    """The anchors ``e`` may render (``""`` for a relative path), or None if
    any: a literal head has one, an absolute parameter ``/`` or ``//``; a
    name changed by ``with_name``, ``with_suffix`` or ``with_stem``, and a
    parent, keep their base's; a path made relative has ``""``; and a join
    has its left side's, or its right side's where that is absolute."""
    h = e.head
    if isinstance(h, _Rel):
        return frozenset({""})
    if isinstance(h, Root):
        return frozenset({h.anchor})
    if isinstance(h, HeadParam) and h.param.kind is ParamKind.ABSOLUTE:
        return frozenset({"/", "//"})
    if isinstance(h, Deferred):
        if h.op in (*_NAME_OPS, "parent"):
            return _anchors(h.base)
        if h.op == "relative_to":
            return frozenset({""})  # pathlib's relative_to is always relative
        if h.op == "join" and isinstance(h.arg, PathExpr):
            # Joining keeps the left side's anchor, unless the right side is
            # absolute, which replaces it with its own.
            left, right = _anchors(h.base), _anchors(h.arg)
            if left is None or right is None:
                return None
            return (right - {""}) | (left if "" in right else frozenset())
    return None


def _depth(e: PathExpr) -> tuple[int, list[Any]] | None:
    """How many segments ``e`` renders, as a count of segments and the parts
    whose own count varies (SubPaths, and heads other than a literal one);
    None where that is not known. A name changed by ``with_name``,
    ``with_suffix`` or ``with_stem`` keeps its base's count: pathlib replaces
    the last segment, and refuses where there is none. A parent has one
    fewer, where its base renders a segment of its own."""
    h = e.head
    n, atoms = 0, list[Any]()
    if isinstance(h, Deferred) and h.op in (*_NAME_OPS, "parent"):
        base = _depth(h.base)
        if base is None or (h.op == "parent" and base[0] < 1):
            return None
        n = base[0] - (h.op == "parent")
        atoms.extend(base[1])
    elif not isinstance(h, (Root, _Rel)):
        atoms.append(h)
    for p in e.parts:
        if isinstance(p, Seg):
            n += 1
        elif isinstance(p, Splice):
            atoms.append(p)
        else:
            return None
    return n, atoms


def _depths_never(a: PathExpr, b: PathExpr, how: How, shared: bool, memo: Memo) -> bool:
    """Whether ``a`` and ``b`` never relate by ``how`` for their depths alone:
    where each part of varying count on one side is alike one on the other
    (§15.3, 1), they render one count on both, so the depths differ by the
    counts of segments. Paths of different depths are never one, nor of
    equal depths one inside the other."""
    da, db = _depth(a), _depth(b)
    if da is None or db is None:
        return False
    (n, xs), (k, ys) = da, db
    if xs or ys:
        bad = _conflicting_defaults(a, b)
        if not shared or any(_names(x) & bad for x in (*xs, *ys)):
            return False
        if Counter(_key(x, memo) for x in xs) != Counter(_key(y, memo) for y in ys):
            return False
    return not {"same": n == k, "inside": n > k, "contains": n < k}[how]


def _view(e: PathExpr, memo: Memo) -> PathExpr:
    """``e`` with a name changed by ``with_name``, ``with_suffix`` or
    ``with_stem`` seen as its base's parent and one segment: the new name for
    ``with_name``; text then the suffix for ``with_suffix``; the new stem then
    text for ``with_stem``. The view renders what ``e`` renders, and more, so
    it proves "never", and nesting by depth. The text's name is fixed by the
    operation and the defaults of its names (`_fresh_key`), so one operation
    viewed twice is alike where it renders one text."""
    h = e.head
    if not (isinstance(h, Deferred) and h.op in _NAME_OPS):
        return e
    base = _view(h.base, memo)
    if not base.parts or not isinstance(base.parts[-1], Seg):
        return e
    text = Field(Param(memo.name("_name_", _fresh_key(h, memo))))
    if h.op == "with_name":
        pieces = list(h.arg.pieces)
    elif h.op == "with_suffix":
        pieces = [text, h.arg]
    elif h.arg.literal in (".", ".."):
        # The stem "..", or "." before the suffix ".", renders the name "..",
        # which no segment of a view does.
        return e
    else:
        pieces = [*h.arg.pieces, text]
    return PathExpr(base.head, base.parts[:-1] + (Seg(_norm(pieces)),) + e.parts)


Case = tuple[str | None, PathExpr]


def _cases(e: PathExpr, memo: Memo) -> list[PathExpr] | None:
    """``e`` written out as cases (`_tagged_cases`), without their tags."""
    tagged = _tagged_cases(e, memo)
    return None if tagged is None else [x for _, x in tagged]


def _tagged_cases(e: PathExpr, memo: Memo) -> list[Case] | None:
    """``e`` written out as cases, each rendering under the same binding what
    ``e`` renders where the case holds; None where there are none.

    - A parent, or a changed name, of a base ending in a SubPath: the case
      where the SubPath renders a segment or more (tagged ``"longer"``), and
      the case where it renders none (``"shorter"``), by `_parents` and
      `_renamed`.
    - A suffix or stem changed while its base's name is unknown, as the ways
      pathlib may split that name, each written out with the base's own
      pieces (untagged). pathlib takes the suffix from the name less its
      leading dots. Where the name ends in literal text ``L`` whose last dot
      is at ``k``, that dot starts the suffix, ``L[k:]``, unless every
      character before it is a dot, and then there is no suffix."""
    h = e.head
    if isinstance(h, Deferred) and h.op == "parent":
        return _parents(e, h, memo)
    if isinstance(h, Deferred) and h.op in _NAME_OPS:
        renamed = _renamed(e, h, memo)
        if renamed is not None:
            return renamed
    if not (isinstance(h, Deferred) and h.op in ("with_suffix", "with_stem")):
        return None
    split = _suffix_cases(e, h)
    if split is None and _dot_stem(h):
        return _dot_stems(e, h, memo)
    return split


def _suffix_cases(e: PathExpr, h: Deferred) -> list[Case] | None:
    """A suffix or stem changed while its base's name ends in literal text
    with a dot, written out by how pathlib splits that name (`_tagged_cases`)."""
    base = h.base
    if isinstance(base.head, Deferred) or not base.parts:
        return None
    last = base.parts[-1]
    if not isinstance(last, Seg) or not last.pieces:
        return None
    *before, tail = last.pieces
    if not isinstance(tail, str) or "." not in tail:
        return None
    if h.op == "with_stem" and h.arg.literal == "":
        return None
    k = tail.rfind(".")
    if h.op == "with_suffix":
        split = [*before, tail[:k], h.arg]
        whole = [*last.pieces, h.arg]
    else:
        split = [*h.arg.pieces, tail[k:]]
        whole = list(h.arg.pieces)

    def written(pieces: list[Any]) -> PathExpr:
        return PathExpr(base.head, base.parts[:-1] + (Seg(_norm(pieces)),) + e.parts)

    cases: list[Case] = [(None, written(split))]
    # No suffix only if every character before the dot is a dot: the fields
    # may render dots alone, so any literal character before it decides.
    # pathlib refuses the stem "." of a name without a suffix.
    literal = "".join(p for p in before if isinstance(p, str)) + tail[:k]
    if set(literal) <= {"."} and whole and whole != ["."]:
        cases.append((None, written(whole)))
    return cases


def _dot_stem(h: Deferred) -> bool:
    return h.op == "with_stem" and h.arg.literal in (".", "..")


def _dot_stems(e: PathExpr, h: Deferred, memo: Memo) -> list[Case] | None:
    """The stem ``.`` or ``..`` given to a name of unknown suffix, written
    out: the stem then the suffix, a dot and text, where that is not ``..``;
    and the name ``..``, which the stem ``..`` gives a name without a suffix
    and the stem ``.`` a name whose suffix is ``.``. Neither has a view, as
    no segment of one renders ``..`` (§15.3, 3). The suffix's text is named
    as a view's would be."""
    base = _view(h.base, memo)
    if not base.parts or not isinstance(base.parts[-1], Seg):
        return None
    text = Field(Param(memo.name("_name_", _fresh_key(h, memo))))

    def written(seg: Seg) -> PathExpr:
        return PathExpr(base.head, base.parts[:-1] + (seg,) + e.parts)

    return [
        (None, written(Seg(_norm([*h.arg.pieces, ".", text])))),
        (None, written(Seg(("..",)))),
    ]


def _split_base(e: PathExpr) -> PathExpr | None:
    """The base whose last SubPath ``e``'s cases split, if they do: that of a
    parent or a changed name."""
    h = e.head
    if not (isinstance(h, Deferred) and h.op in ("parent", *_NAME_OPS)):
        return None
    base = h.base
    if isinstance(base.head, Deferred) or not base.parts:
        return None
    return base if isinstance(base.parts[-1], Splice) else None


def _split(base: PathExpr, memo: Memo) -> tuple[Splice, Seg]:
    """A base's last SubPath, where it renders a segment or more, as a SubPath
    of all but the last segment, and that segment. The names are the base's
    (`_fresh_key`), so every operation on one base splits it alike."""
    key = _fresh_key(base, memo)
    rest = Splice(Param(memo.name("_rest_", key), ParamKind.SUBPATH))
    last = Seg((Field(Param(memo.name("_seg_", key)), role="segment"),))
    return rest, last


def _parents(e: PathExpr, h: Deferred, memo: Memo) -> list[Case] | None:
    """A parent deferred because its base ends in a SubPath, written out: the
    base with a SubPath of what precedes the last segment in place of its
    own, where that renders a segment or more; and the parent of what
    precedes it, where it renders none. Each keeps the base's prefix."""
    base = _split_base(e)
    if base is None:
        return None
    rest, _ = _split(base, memo)
    longer = PathExpr(base.head, base.parts[:-1] + (rest,) + e.parts)
    prefix = base.parts[:-1]
    if prefix and isinstance(prefix[-1], Seg):
        shorter = PathExpr(base.head, prefix[:-1] + e.parts)
    elif not prefix and isinstance(base.head, (Root, _Rel)):
        shorter = PathExpr(base.head, e.parts)  # "/" and "." are their own parents
    else:
        shorter = PathExpr(Deferred("parent", PathExpr(base.head, prefix)), e.parts)
    return [("longer", longer), ("shorter", shorter)]


def _renamed(e: PathExpr, h: Deferred, memo: Memo) -> list[Case] | None:
    """A name changed while its base ends in a SubPath, written out: the
    change of the base's last segment, where the SubPath renders one or more
    (the change then has a view, §15.3, 3); and the change of what precedes
    the SubPath, where it renders none."""
    base = _split_base(e)
    if base is None:
        return None
    rest, last = _split(base, memo)
    prefix = base.parts[:-1]
    cases: list[Case] = []
    for tag, parts in (("longer", prefix + (rest, last)), ("shorter", prefix)):
        # Built as wend builds it: the change is made now where the name is
        # known, and a change pathlib refuses (of "/", say) renders nothing.
        try:
            changed = getattr(PathExpr(base.head, parts), h.op)(h.arg)
        except WendError, ValueError:
            continue
        case = PathExpr(changed.head, changed.parts + e.parts)
        dots = None
        if isinstance(changed.head, Deferred) and _dot_stem(changed.head):
            dots = _dot_stems(case, changed.head, memo)
        cases.extend([(tag, x) for _, x in dots] if dots else [(tag, case)])
    return cases


def _split_alike(y: PathExpr, base: PathExpr, memo: Memo) -> list[Case] | None:
    """``y``, where it begins with ``base``, split as ``base``'s cases split
    it: where its last SubPath renders a segment or more, and where it renders
    none. None unless ``y`` begins with ``base``, defaults included, so that
    under shared bindings the two render one text there."""
    n = len(base.parts)
    if isinstance(y.head, Deferred) or len(y.parts) < n:
        return None
    if _fresh_key(PathExpr(y.head, y.parts[:n]), memo) != _fresh_key(base, memo):
        return None
    rest, last = _split(base, memo)
    return [
        ("longer", PathExpr(y.head, base.parts[:-1] + (rest, last) + y.parts[n:])),
        ("shorter", PathExpr(y.head, base.parts[:-1] + y.parts[n:])),
    ]


def _common(a: PathExpr, b: PathExpr, shared: bool, memo: Memo) -> int | None:
    """How many leading parts render alike for every binding, after heads
    that do; None if the heads may not."""
    if not shared and not isinstance(a.head, (Root, _Rel)):
        return None
    bad = _conflicting_defaults(a, b) if shared else frozenset()
    if not _alike(a.head, b.head, bad, memo):
        return None
    i = 0
    while i < min(len(a.parts), len(b.parts)):
        pa, pb = a.parts[i], b.parts[i]
        if not shared and not (_static(pa) and _static(pb)):
            break
        if not _alike(pa, pb, bad, memo):
            break
        i += 1
    return i


# -- examples ----------------------------------------------------------------------


def _segments(path: str) -> tuple[str, tuple[str, ...]]:
    p = PurePosixPath(path)
    parts = p.parts
    if p.anchor:
        return p.anchor, parts[1:]
    return "", parts


def lexically(a_path: str, b_path: str) -> How | None:
    """How two rendered paths relate as strings: the same, ``a`` strictly
    below ``b``, strictly above, or None."""
    (aa, sa), (ab, sb) = _segments(a_path), _segments(b_path)
    if aa != ab:
        return None
    if sa == sb:
        return "same"
    if len(sa) > len(sb) and sa[: len(sb)] == sb:
        return "inside"
    if len(sb) > len(sa) and sb[: len(sa)] == sa:
        return "contains"
    return None


def _render(e: PathExpr, env: dict[str, Any]) -> str | None:
    try:
        return e.render(env)
    except WendError, ValueError, TypeError:
        return None


def _name(p: Param) -> str:
    return p.name


def _search(
    a: PathExpr,
    b: PathExpr,
    how: How,
    shared: bool,
    seeds: Iterable[tuple[dict[str, Any], dict[str, Any]]] = (),
    limit: int = 64,
) -> Example | None:
    """Bindings that render both and show ``how``: each seed completed with
    sample values for the names it lacks, then samples alone."""
    words = _overlap._words(a, b)
    params: dict[str, Param] | None = {**a.params, **b.params} if shared else None
    each = limit if shared else 16

    def tries(missing: list[Param]) -> Iterable[dict[str, Any]]:
        if not missing:
            return [{}]
        return _readable(missing, words, each)

    # Sample values first, which read better than a witness's; then each
    # witness, completed.
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = [({}, {}), *seeds]
    for sa, sb in candidates:
        if shared:
            assert params is not None
            base = {**sa, **sb}
            missing = [p for n, p in params.items() if n not in base]
            missing.sort(key=_name)
            for extra in tries(missing):
                env = {**base, **extra}
                ea = {n: v for n, v in env.items() if n in a.params}
                eb = {n: v for n, v in env.items() if n in b.params}
                ex = _example(a, b, ea, eb, how)
                if ex is not None:
                    return ex
        else:
            ma = sorted((p for n, p in a.params.items() if n not in sa), key=_name)
            mb = sorted((p for n, p in b.params.items() if n not in sb), key=_name)
            for xa in tries(ma):
                ea = {**{n: v for n, v in sa.items() if n in a.params}, **xa}
                for xb in tries(mb):
                    eb = {**{n: v for n, v in sb.items() if n in b.params}, **xb}
                    ex = _example(a, b, ea, eb, how)
                    if ex is not None:
                        return ex
    return None


_FRIENDLY: dict[str, list[Any]] = {
    "int": [1, 2, 3, 7],
    "float": [0.5, 1.5, 2.5],
    "absolute": ["/data", "/srv", "/tmp"],
    "subpath": ["a/b", "c", "d/e"],
    "head": ["data", "out", "work"],
    "segment": ["a", "b", "c", "d"],
}


def _friendly(q: Param, k: int, avoid: frozenset[str] = frozenset()) -> Any:
    """A value for ``q`` that reads well in an example, the ``k``-th of its
    kind (so two names rarely share one), and none of the words in ``avoid``
    (the expressions' own, so ``{root}/out`` does not read ``out/out``)."""
    domain = _overlap._domain(q)
    if domain:
        return domain[k % len(domain)]
    if q.type is bool:
        return True
    if q.type is int:
        key = "int"
    elif q.type is float:
        key = "float"
    elif q.kind is ParamKind.ABSOLUTE:
        key = "absolute"
    elif q.kind is ParamKind.SUBPATH:
        key = "subpath"
    elif q.kind in (ParamKind.AUTO, ParamKind.PATH):
        key = "head"
    else:
        key = "segment"
    pool = [v for v in _FRIENDLY[key] if v not in avoid] or _FRIENDLY[key]
    return pool[k % len(pool)]


def _readable(
    params: list[Param], words: list[str], limit: int
) -> Iterable[dict[str, Any]]:
    """Sample bindings: friendly values first, leaving parameters with
    defaults unbound (each side then renders its own default), then binding
    them too; then each parameter starting at a different sample of the
    engine's (so two names rarely share a value); then the engine's order."""
    avoid = frozenset(words)
    if any(q.has_default for q in params):
        yield {
            q.name: _friendly(q, k, avoid)
            for k, q in enumerate(params)
            if not q.has_default
        }
    yield {q.name: _friendly(q, k, avoid) for k, q in enumerate(params)}
    pools = _overlap._pools(params, words)
    longest = max((len(x) for x in pools), default=1)
    for i in range(longest):
        yield {
            q.name: pool[(i + k) % len(pool)]
            for k, (q, pool) in enumerate(zip(params, pools, strict=True))
        }
    yield from itertools.islice(_overlap._samples(params, words, limit), limit)


def _example(
    a: PathExpr, b: PathExpr, ea: dict[str, Any], eb: dict[str, Any], how: How
) -> Example | None:
    pa, pb = _render(a, ea), _render(b, eb)
    if pa is None or pb is None or lexically(pa, pb) != how:
        return None
    return Example(how, pa, pb, ea, eb)


# -- the analysis ------------------------------------------------------------------


def _fresh(e: PathExpr, *others: PathExpr) -> tuple[str, str]:
    taken = set(e.param_names).union(*(o.param_names for o in others))
    names = []
    for stem in ("_inside", "_below"):
        name = stem
        while name in taken:
            name += "_"
        taken.add(name)
        names.append(name)
    return names[0], names[1]


def _strictly_below(e: PathExpr, *others: PathExpr) -> tuple[PathExpr, set[str]]:
    """Every path strictly below ``e``'s: one segment or more."""
    seg, rest = _fresh(e, *others)
    return _plain(e) / Param(seg) / SubPath(rest), {seg, rest}


class Analysis:
    """The relation of ``a`` to ``b``, one question at a time (each is asked
    only when wanted, and remembered)."""

    def __init__(
        self,
        a: Any,
        b: Any,
        *,
        shared: bool = True,
        builtin_values: bool = False,
        memo: Memo | None = None,
    ) -> None:
        self.shared = shared
        self.builtin_values = builtin_values
        self.memo: Memo = Memo(builtin_values) if memo is None else memo
        self.pairs = [
            (x, y) for x in _overlap._alternatives(a) for y in _overlap._alternatives(b)
        ]
        self.memo.reserve(
            n for x, y in self.pairs for n in x.param_names | y.param_names
        )
        self.single = len(self.pairs) == 1
        self._answers: dict[How, Certainty] = {}
        self._examples: dict[How, Example | None] = {}
        self.assumptions: set[str] = set()
        # A name a plain field renders in both roles: its keys agree only
        # because of builtin_values, which an answer may then rely on.
        if self.memo.builtin and any(
            len(roles) > 1 for x, y in self.pairs for roles in _roles(x, y).values()
        ):
            self.assumptions.add("builtin_values")

    def __call__(self, how: How) -> Certainty:
        """The certainty of one relation (``same``, ``inside`` or
        ``contains``)."""
        if how not in self._answers:
            answers: list[Certainty] = [self._pair(x, y, how) for x, y in self.pairs]
            self._answers[how] = self._combine(how, answers)
        return self._answers[how]

    def example(self, how: How) -> Example | None:
        """Bindings showing ``how``, when it holds always or sometimes."""
        if self(how) not in ("always", "sometimes"):
            return None
        if how not in self._examples:
            self._examples[how] = _search(*self.pairs[0], how, self.shared)
        return self._examples[how]

    def relation(self) -> Relation:
        certainties: dict[How, Certainty] = {how: self(how) for how in _HOWS}
        examples = (self.example(how) for how in _HOWS)
        return Relation(
            certainties["same"],
            certainties["inside"],
            certainties["contains"],
            shared=self.shared,
            examples=tuple(ex for ex in examples if ex is not None),
            assumptions=frozenset(self.assumptions),
        )

    def _combine(self, how: How, answers: list[Certainty]) -> Certainty:
        if self.single:
            return answers[0]
        # Unions: the path may be any alternative's, so "always" is not kept,
        # and "sometimes" needs an example from one pair.
        if all(c == "never" for c in answers):
            return "never"
        for (a, b), c in zip(self.pairs, answers, strict=True):
            if c in ("always", "sometimes"):
                ex = self._examples.get(how) or _search(a, b, how, self.shared)
                if ex is not None:
                    self._examples[how] = ex
                    return "sometimes"
        return "unknown"

    def _pair(self, a: PathExpr, b: PathExpr, how: How) -> Certainty:
        # Paths with different anchors are never one, nor nested.
        aa, ab = _anchors(a), _anchors(b)
        if aa is not None and ab is not None and not aa & ab:
            return "never"
        if _depths_never(a, b, how, self.shared, self.memo):
            return "never"
        va, vb = _view(a, self.memo), _view(b, self.memo)
        answer = self._decide(a, b, va, vb, how)
        if answer == "unknown" and (va is not a or vb is not b):
            # The views prove more "never"s, but a witness of them binds a
            # name's text, which the expressions do not take: the expressions
            # themselves may still be shown, or ruled out, as before.
            answer = self._decide(a, b, a, b, how)
        if answer == "unknown":
            # A changed suffix or stem, written out by how its base's name
            # splits: never if no case of one meets a case of the other.
            if self._cases_never(a, b, va, vb, how):
                return "never"
        return answer

    def _cases_never(
        self, a: PathExpr, b: PathExpr, va: PathExpr, vb: PathExpr, how: How
    ) -> bool:
        """Whether no case of ``a`` meets a case of ``b`` (§15.3, 3). Under
        shared bindings, where both split one base, or one splits a base the
        other begins with, the base's SubPath renders one text on both
        sides, so only cases of one branch are paired."""
        ca, cb = _tagged_cases(a, self.memo), _tagged_cases(b, self.memo)
        base = _split_base(a) or _split_base(b)
        if self.shared and base is not None:
            if ca is None:
                ca = _split_alike(a, base, self.memo)
            if cb is None:
                cb = _split_alike(b, base, self.memo)
        if ca is None and cb is None:
            return False
        xs = ca or [(None, va)]
        ys = cb or [(None, vb)]
        ba = _split_base(a) or (base if ca and _split_base(a) is None else None)
        bb = _split_base(b) or (base if cb and _split_base(b) is None else None)
        correlated = (
            self.shared
            and ba is not None
            and bb is not None
            and _fresh_key(ba, self.memo) == _fresh_key(bb, self.memo)
        )
        return all(
            self._decide(a, b, _view(x, self.memo), _view(y, self.memo), how) == "never"
            for (s, x), (t, y) in itertools.product(xs, ys)
            if not (correlated and s is not None and t is not None and s != t)
        )

    def _decide(
        self, a: PathExpr, b: PathExpr, va: PathExpr, vb: PathExpr, how: How
    ) -> Certainty:
        """The answer for ``a`` and ``b``, reasoned on ``va`` and ``vb`` (each
        the expression or its view)."""
        common = _common(va, vb, self.shared, self.memo)
        ra, rb = va, vb
        if common is not None:
            ra = PathExpr(REL, va.parts[common:])
            rb = PathExpr(REL, vb.parts[common:])
            bad = _conflicting_defaults(va, vb) if self.shared else frozenset()
            decided = _structurally(ra, rb, how, self.shared, bad, self.memo)
            if decided is not None:
                return decided
        answer = self._overlap(a, b, ra, rb, how)
        if answer == "unknown" and common is not None and isinstance(va.head, Deferred):
            # The engine is not monotone: it may rule out the whole expressions
            # where it cannot rule out what follows their deferred head.
            answer = self._overlap(a, b, va, vb, how)
        return answer

    def _overlap(
        self, a: PathExpr, b: PathExpr, ra: PathExpr, rb: PathExpr, how: How
    ) -> Certainty:
        if how == "same":
            x, y, fresh = ra, rb, set()
        elif how == "inside":
            x, (y, fresh) = ra, _strictly_below(rb, ra)
        else:
            x, (y, fresh) = rb, _strictly_below(ra, rb)
        r = _overlap.overlaps(
            x, y, shared=self.shared, builtin_values=self.builtin_values
        )
        self.assumptions |= r.assumptions
        if r.verdict == "no":
            # "Strictly below" is built from a segment parameter and a SubPath,
            # neither of which renders "..": a path whose extra segments hold
            # one escapes it, so a NO is a proof only without one.
            if how != "same" and _may_render_dotdot(x):
                return "unknown"
            return "never"
        seeds = []
        if r.witness is not None:
            wa = {k: v for k, v in r.witness.a.items() if k not in fresh}
            wb = {k: v for k, v in r.witness.b.items() if k not in fresh}
            seeds.append((wa, wb) if how != "contains" else (wb, wa))
        # A witness of the remainders proves nothing about ``a`` and ``b``
        # until a full binding confirms it.
        ex = _search(a, b, how, self.shared, seeds)
        if ex is None:
            return "unknown"
        if self.single:
            self._examples[how] = ex
        return "sometimes"


def _tokens(seg: Seg) -> list[Any]:
    """A segment's pieces with its literal text split into characters."""
    return [c for p in seg.pieces for c in (p if isinstance(p, str) else (p,))]


def _apart_segments(
    a: Seg, b: Seg, shared: bool, bad: frozenset[str], memo: Memo
) -> bool:
    """Whether two segments render different text for every binding under
    which both render: what remains once equal leading and trailing pieces
    cancel (a field only under shared bindings, by (1)) must differ in a
    character, or one side must be empty and the other hold one."""

    def alike(x: Any, y: Any) -> bool:
        if isinstance(x, str) or isinstance(y, str):
            return x == y
        return shared and not (x.param_names & bad) and _key(x, memo) == _key(y, memo)

    ta, tb = _tokens(a), _tokens(b)
    i = 0
    while i < min(len(ta), len(tb)) and alike(ta[i], tb[i]):
        i += 1
    ta, tb = ta[i:], tb[i:]
    j = 0
    while j < min(len(ta), len(tb)) and alike(ta[-1 - j], tb[-1 - j]):
        j += 1
    ta, tb = ta[: len(ta) - j], tb[: len(tb) - j]
    if not ta or not tb:
        # One renders "" here: the other differs if it holds a character.
        return any(isinstance(t, str) for t in (*ta, *tb))
    # Cancellation stopped at a pair that is not alike: two characters differ.
    first = isinstance(ta[0], str) and isinstance(tb[0], str)
    last = isinstance(ta[-1], str) and isinstance(tb[-1], str)
    return first or last


def _structurally(
    ra: PathExpr,
    rb: PathExpr,
    how: How,
    shared: bool = True,
    bad: frozenset[str] = frozenset(),
    memo: Memo | None = None,
) -> Certainty | None:
    """The answer from the remainders' structure alone, or None."""
    if not ra.parts and not rb.parts:
        return "always" if how == "same" else "never"
    if not ra.parts and any(isinstance(p, Seg) for p in rb.parts):
        return "always" if how == "contains" else "never"
    if not rb.parts and any(isinstance(p, Seg) for p in ra.parts):
        return "always" if how == "inside" else "never"
    # Divergence: the remainders start at one position, so while both hold
    # segments their k-th parts render their k-th segments, which must be one
    # for any of the three relations.
    for fa, fb in zip(ra.parts, rb.parts, strict=False):
        if not (isinstance(fa, Seg) and isinstance(fb, Seg)):
            break
        if _apart_segments(fa, fb, shared, bad, Memo() if memo is None else memo):
            return "never"
    # Depth: a segment renders exactly one segment (never "", "." or a
    # separator), so remainders of segments alone render a fixed count of
    # them, and paths of different depths are never one, nor of equal depths
    # one inside the other.
    if all(isinstance(p, Seg) for p in (*ra.parts, *rb.parts)):
        n, m = len(ra.parts), len(rb.parts)
        if not {"same": n == m, "inside": n > m, "contains": n < m}[how]:
            return "never"
    return None


def relate(
    a: Any, b: Any, *, shared: bool = True, builtin_values: bool = False
) -> Relation:
    """How the paths ``a`` and ``b`` render relate, before any binding.

    The paths are compared as strings (lexically), not as filesystem
    objects: ``"never"`` means never the same string, and a symlink or a
    ``..`` can still make two strings name one file.

    ``a`` and ``b`` are expressions, unions or path strings. With
    ``shared=True`` (the default) a parameter name common to both takes one
    value, as the paths of one run of a pipeline do; ``shared=False`` relates
    every binding of ``a`` to every binding of ``b``. ``builtin_values=True``
    assumes bound values are of builtin types, which proves more paths apart
    (docs/SEMANTICS.md §15).

    >>> from wend import P, Param, T
    >>> root, day = Param("root"), Param("day")
    >>> raw = P(root) / "raw" / T(t"{day}.csv")
    >>> relate(raw, P(root) / "clean" / T(t"{day}.csv")).kind
    'disjoint'
    >>> relate(raw, P(root) / "raw").inside
    'always'
    """
    return Analysis(a, b, shared=shared, builtin_values=builtin_values).relation()


__all__ = ["Certainty", "Example", "Relation", "relate"]
