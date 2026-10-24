"""Reading `PathExpr.pattern` back into an expression (research prototype;
see docs/journal/2026-10-21-typed-path-families.md).

``e.pattern`` prints wend's normal form as a small term language: segments
of literal text and fields (``{name!conv:spec}``, a dynamic spec's
parameters as ``{p}``), ``{name...}`` for a SubPath, and deferred
operations as calls (``join(a, b)``, ``parent(a)``, ``with_suffix(a, '.x')``,
``relative_to(a, b)``; ``{stem(a)}`` for a text operation). The printing
forgets what each parameter was declared as (type, choices, kind, default)
and every declared condition, so it is not injective.

`parse(pattern, params)` builds the normal-form nodes directly:

- with ``params`` (the expression's own declarations, ``e.params``), it is
  meant to invert the printing exactly: ``parse(e.pattern, e.params) == e``;
- without, each name gets the most general declaration its position
  allows (``Param`` at the head, ``SubPath`` for ``{name...}``, ``AnyPath``
  for a path operand of ``join``): the principal expression of that
  structure, which renders whatever ``e`` renders for ``e``'s bindings.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

from .. import AnyPath, Param, SubPath
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
    Text,
    TextOp,
)
from .._params import Kind


__all__ = ["PatternError", "parse"]

DEFERRED = ("join", "parent", "with_name", "with_suffix", "with_stem", "relative_to")
TEXT_OPS = ("name", "stem", "suffix")


class PatternError(ValueError):
    """Text that is not a pattern this module can read."""


class _Reader:
    def __init__(self, text: str, params: Mapping[str, Param] | None) -> None:
        self.s = text
        self.i = 0
        self.given = dict(params or {})
        self.made: dict[str, Param] = {}

    # -- parameters -------------------------------------------------------------

    def param(self, name: str, default: Any = Param) -> Param:
        if name in self.given:
            return self.given[name]
        if name not in self.made:
            self.made[name] = default(name)
        return self.made[name]

    # -- scanning ---------------------------------------------------------------

    def fail(self, why: str) -> PatternError:
        return PatternError(f"{why} at {self.i} in {self.s!r}")

    def peek(self, t: str) -> bool:
        return self.s.startswith(t, self.i)

    def eat(self, t: str) -> None:
        if not self.peek(t):
            raise self.fail(f"expected {t!r}")
        self.i += len(t)

    def ident(self) -> str:
        j = self.i
        while j < len(self.s) and (self.s[j].isalnum() or self.s[j] == "_"):
            j += 1
        if j == self.i:
            raise self.fail("expected a name")
        name, self.i = self.s[self.i : j], j
        return name

    def call_ahead(self, names: tuple[str, ...]) -> str | None:
        for n in names:
            if self.s.startswith(n + "(", self.i):
                return n
        return None

    # -- expressions ------------------------------------------------------------

    def expr(self, stop: str = "") -> PathExpr:
        """An expression up to the end, or to an unnested character of ``stop``."""
        if self.peek(".") and self._at_end(self.i + 1, stop):
            self.i += 1
            return PathExpr(REL)
        op = self.call_ahead(DEFERRED)
        if op is not None:
            head = self.deferred(op)
            parts: list[Any] = []
        elif self.peek("//") and not self.peek("///"):
            self.i += 2
            head, parts = Root("//"), []
        elif self.peek("/"):
            self.i += 1
            head, parts = Root("/"), []
        else:
            head, parts = REL, []
        first = True
        need_slash = isinstance(head, Deferred)  # ``join(a, b)/c``
        while not self._at_end(self.i, stop):
            if need_slash:
                self.eat("/")
            need_slash = True
            seg = self.part(stop)
            if first and head is REL and _is_bare_field(seg) and _at_head(seg):
                head = HeadParam(seg.pieces[0].source)  # type: ignore[union-attr]
            else:
                parts.append(seg)
            first = False
        return PathExpr(head, tuple(parts))

    def _at_end(self, j: int, stop: str) -> bool:
        return j >= len(self.s) or (bool(stop) and self.s[j] in stop)

    def deferred(self, op: str) -> Deferred:
        self.eat(op + "(")
        base = self.expr(stop=",)")
        arg: Any = None
        if self.peek(", "):
            self.i += 2
            if op in ("join", "relative_to"):
                arg = self.expr(stop=")")
                if op == "join" and isinstance(arg.head, HeadParam) and not arg.parts:
                    name = arg.head.param.name
                    arg = PathExpr(HeadParam(self.param(name, AnyPath)))
            elif self.peek("'") or self.peek('"'):
                arg = self.literal()
            else:
                arg = Text(tuple(self.pieces(stop=")")))
        self.eat(")")
        return Deferred(op, base, arg)

    def part(self, stop: str) -> Seg | Splice:
        if self.peek("{"):
            j = self.s.find("...}", self.i)
            k = self.s.find("}", self.i)
            if j != -1 and j + 3 == k:
                name = self.s[self.i + 1 : j]
                if name.isidentifier():
                    self.i = k + 1
                    return Splice(self.param(name, SubPath))
        pieces = self.pieces(stop="/" + stop)
        if not pieces:
            raise self.fail("empty segment")
        return Seg(tuple(pieces))

    # -- segments ---------------------------------------------------------------

    def pieces(self, stop: str) -> list[Any]:
        out: list[Any] = []
        text: list[str] = []
        while self.i < len(self.s) and self.s[self.i] not in stop:
            if self.peek("{{") or self.peek("}}"):
                text.append(self.s[self.i])
                self.i += 2
            elif self.peek("{"):
                if text:
                    out.append("".join(text))
                    text = []
                out.append(self.field())
            elif self.peek("}"):
                raise self.fail("unmatched '}'")
            else:
                text.append(self.s[self.i])
                self.i += 1
        if text:
            out.append("".join(text))
        if len(out) == 1 and isinstance(out[0], Field) and _whole(out[0]):
            out[0] = Field(out[0].source, role="segment")
        return out

    def field(self) -> Field:
        self.eat("{")
        op = self.call_ahead(TEXT_OPS)
        if op is not None:
            self.eat(op + "(")
            source: Any = TextOp(op, self.expr(stop=")"))
            self.eat(")")
        elif self.peek("(") and (self.s[self.i + 1 : self.i + 2] in ("'", '"')):
            self.eat("(")
            source = self.text(self.literal())
            self.eat(")")
        elif self._const_ahead():
            source = Const(self.literal_until("!:}"))
        else:
            source = self.param(self.ident())
        conversion = None
        if self.peek("!"):
            self.i += 1
            conversion = self.s[self.i]
            self.i += 1
        spec: list[Any] = []
        if self.peek(":"):
            self.i += 1
            buf: list[str] = []
            while not self.peek("}"):
                if self.peek("{"):
                    if buf:
                        spec.append("".join(buf))
                        buf = []
                    self.i += 1
                    spec.append(self.param(self.ident()))
                    self.eat("}")
                else:
                    buf.append(self.s[self.i])
                    self.i += 1
            if buf:
                spec.append("".join(buf))
        self.eat("}")
        return Field(source, conversion, tuple(spec))

    def _const_ahead(self) -> bool:
        """A constant's repr, not a name: quotes, digits, a sign, a bracket,
        or True, False, None (which name no parameter)."""
        c = self.s[self.i : self.i + 1]
        if c in ("'", '"', "-", "+", "(", "[", "{") or c.isdigit():
            return True
        j = self.i
        while j < len(self.s) and (self.s[j].isalnum() or self.s[j] == "_"):
            j += 1
        return self.s[self.i : j] in ("True", "False", "None")

    def text(self, pattern: str) -> Text:
        """A `Text` from its own pattern (a field's source prints as its repr),
        sharing this reader's parameters."""
        inner = _Reader(pattern, self.given)
        inner.made = self.made
        return Text(tuple(inner.pieces(stop="")))

    def literal(self) -> Any:
        """A Python string literal (as ``repr`` writes it) at the cursor."""
        q = self.s[self.i]
        j = self.i + 1
        while j < len(self.s):
            if self.s[j] == "\\":
                j += 2
                continue
            if self.s[j] == q:
                break
            j += 1
        text, self.i = self.s[self.i : j + 1], j + 1
        return ast.literal_eval(text)

    def literal_until(self, stops: str) -> Any:
        if self.peek("'") or self.peek('"'):
            return self.literal()
        j = self.i
        while j < len(self.s) and self.s[j] not in stops:
            j += 1
        text, self.i = self.s[self.i : j], j
        return ast.literal_eval(text)


def _whole(f: Field) -> bool:
    return isinstance(f.source, Param) and f.conversion is None and not f.spec


def _at_head(seg: Seg) -> bool:
    """Whether a leading bare field is a head parameter. The normal form keeps
    a Segment parameter in a segment (``P(Segment("x"))`` is relative), so
    only another kind can be one. For an undeclared kind the printing is
    ambiguous: a head parameter and a relative expression whose first
    segment is a whole-segment field (as ``.name`` can leave) both print
    ``{x}``; the head is the reading chosen."""
    return seg.pieces[0].source.kind is not Kind.SEGMENT  # type: ignore[union-attr]


def _is_bare_field(seg: Seg | Splice) -> bool:
    return (
        isinstance(seg, Seg)
        and len(seg.pieces) == 1
        and isinstance(seg.pieces[0], Field)
        and seg.pieces[0].role == "segment"
    )


def parse(pattern: str, params: Mapping[str, Param] | None = None) -> PathExpr:
    """The expression whose `PathExpr.pattern` is ``pattern``, with each
    parameter taken from ``params`` by name, or given the most general
    declaration its position allows."""
    r = _Reader(pattern, params)
    e = r.expr()
    if r.i != len(pattern):
        raise r.fail("unexpected text")
    return e
