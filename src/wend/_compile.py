"""Compilation of path expressions to specialised Python functions.

`compile_expr` generates Python source for one expression: parameter lookups,
validation and formatting are inlined, literal text is pre-joined, and checks
that the expression's static structure makes redundant (segments that cannot
render to "", "." or "..") are omitted.

The generated fast path only has to be right when it succeeds. Any exception
inside it (a missing key, a format error, a failed check) falls back to the
reference interpreter, so errors and messages are identical by construction;
differential tests check that successful results are identical too.

A parameter with a default reads ``env[name]`` when the name is present and
the default otherwise (§3.1), unless the mapping has `Param` keys, which only
the interpreter resolves. An object given in place of a mapping fails the
fast path once, and is converted to its bindings and rendered again.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from . import _expr as X
from ._params import NO_DEFAULT, Kind, Param


class CompiledPath:
    """A compiled expression. Call it like ``resolve``; ``render`` returns a str."""

    __slots__ = ("_fn", "expr", "source")

    def __init__(self, expr: X.PathExpr, fn: Any, source: str) -> None:
        self.expr = expr
        self._fn = fn
        self.source = source

    def __repr__(self) -> str:
        return f"CompiledPath({self.expr.pattern!r})"

    def render(self, mapping: Any = None, /, **kw: Any) -> str:
        # Param keys, objects and symbolic values miss the fast path's lookups
        # or checks and fall back to the interpreter, which handles them.
        if kw:
            mapping = X._make_env(mapping, kw)
        return self._fn(mapping if mapping is not None else {})

    def __call__(self, mapping: Any = None, /, **kw: Any) -> Path:
        return Path(self.render(mapping, **kw))

    def many(self, rows: Iterable[Any]) -> list[str]:
        """Render each mapping in ``rows`` (keys are parameter names), or each
        object (its fields bind by name)."""
        fn = self._fn
        return [fn(r) for r in rows]

    def columns(self, **columns: Iterable[Any]) -> list[str]:
        """Render column-wise: ``columns(idx=range(10), split=["a"] * 10)``."""
        names = list(columns)
        fn = self._fn
        return [
            fn(dict(zip(names, row, strict=True)))
            for row in zip(*columns.values(), strict=True)
        ]


class _Gen:
    """Generates straight-line rendering code for one or more expressions.

    Work that two expressions share (a parameter lookup, a head value, a
    formatted field, a whole segment, a SubPath split) is emitted once and
    reused: `compile_many` renders a set of expressions in one call.
    """

    def __init__(self) -> None:
        self.consts: dict[str, Any] = {}
        self.lines: list[str] = []
        self.vars: dict[str | Param, str] = {}
        self.memo: dict[Any, str] = {}
        self.n = 0

    def const(self, value: Any) -> str:
        name = f"_k{len(self.consts)}"
        self.consts[name] = value
        return name

    def tmp(self) -> str:
        self.n += 1
        return f"_t{self.n}"

    def var(self, p: Param) -> str:
        # Keyed by declaration: two expressions of a set may give one name
        # different defaults (§3.1).
        key = p.name if p.default is NO_DEFAULT else p
        if key not in self.vars:
            v = f"_v{len(self.vars)}"
            self.vars[key] = v
            name = p.name
            if p.default is NO_DEFAULT:
                self.lines.append(f"{v} = env[{name!r}]")
            else:
                self.lines.append(
                    f"{v} = env[{name!r}] if {name!r} in env else "
                    f"_default({self.const(p)}, env)"
                )
        return self.vars[key]

    def field(self, f: X.Field) -> str:
        src = f.source
        if not isinstance(src, Param) or f.static_spec is None:
            return self._memo(
                ("render_field", f), f"_render_field({self.const(f)}, env)"
            )
        key = ("field", src, f.conversion, f.static_spec, f.role)
        if key in self.memo:
            return self.memo[key]
        v = self.var(src)
        if f.role == "segment":
            if src.type is None and src.choices is None:
                # Inline seg_value for plain strings; anything else bails out.
                self.lines.append(
                    f"if type({v}) is not str or '/' in {v} or '\\x00' in {v} "
                    f"or {v} in ('', '.', '..'): raise _Bail"
                )
                self.memo[key] = v
                return v
            t = self.tmp()
            self.lines.append(f"{t} = _seg_value({self.const(src)}, {v})")
            self.memo[key] = t
            return t
        if src.choices is not None:
            self.lines.append(f"{self.const(src)}.check({v})")
        elif src.type is not None:
            self.lines.append(
                f"if not isinstance({v}, {self.const(src.type)}): raise _Bail"
            )
        conv = {None: v, "r": f"repr({v})", "s": f"str({v})", "a": f"ascii({v})"}[
            f.conversion
        ]
        t = self.tmp()
        self.lines.append(f"{t} = format({conv}, {f.static_spec!r})")
        cond = [f"'/' in {t}", f"'\\x00' in {t}"]
        dot_free, non_empty = f.facts
        if dot_free:
            cond.append(f"'.' in {t}")
        if non_empty:
            cond.append(f"not {t}")
        self.lines.append(f"if {' or '.join(cond)}: raise _Bail")
        self.memo[key] = t
        return t

    def _memo(self, key: Any, code: str) -> str:
        """A temporary holding ``code``, evaluated once per key."""
        if key not in self.memo:
            t = self.tmp()
            self.lines.append(f"{t} = {code}")
            self.memo[key] = t
        return self.memo[key]

    def seg(self, s: X.Seg) -> str:
        """An expression for the segment's text; literals become string constants."""
        if s.literal is not None:
            return repr(s.literal)
        key = ("seg", s)
        if key in self.memo:
            return self.memo[key]
        terms = [repr(p) if isinstance(p, str) else self.field(p) for p in s.pieces]
        if len(terms) == 1 and not s.needs_check:
            return terms[0]
        t = self.tmp()
        self.lines.append(f"{t} = {' + '.join(terms)}")
        if s.needs_check:
            self.lines.append(f"if {t} in ('', '.', '..'): raise _Bail")
        self.memo[key] = t
        return t

    def head(self, h: Any) -> tuple[str | None, str]:
        """(a temporary holding the head's text or None, the literal anchor)."""
        if isinstance(h, X._Rel):
            return None, ""
        if isinstance(h, X.Root):
            return None, h.anchor
        if isinstance(h, X.HeadParam):
            key = ("head", h.param)
            if key not in self.memo:
                head = self.tmp()
                p = h.param
                v = self.var(p)
                if p.type is None and p.choices is None and p.kind is not Kind.ABSOLUTE:
                    # Inline canonical() for strings that are already canonical.
                    self.lines.append(
                        f"{head} = {v} if (type({v}) is str and {v} and {v}[-1] != '/' "
                        f"and '//' not in {v}[1:] and '/./' not in {v} and {v}[:2] != './' "
                        f"and {v}[-2:] != '/.' and '\\x00' not in {v}) "
                        f"else _head_value({self.const(p)}, {v})"
                    )
                else:
                    self.lines.append(f"{head} = _head_value({self.const(p)}, {v})")
                self.memo[key] = head
            return self.memo[key], ""
        return self._memo(
            ("deferred", h), f"_render_deferred({self.const(h)}, env)"
        ), ""

    def emit(self, e: X.PathExpr) -> str:
        """Append the statements rendering ``e``; return an expression for its text."""
        head, anchor = self.head(e.head)
        if any(isinstance(p, X.Splice) for p in e.parts):
            segs = self.tmp()
            self.lines.append(f"{segs} = []")
            for part in e.parts:
                if isinstance(part, X.Seg):
                    self.lines.append(f"{segs}.append({self.seg(part)})")
                else:
                    split = self._memo(
                        ("splice", part.param),
                        f"_splice_value({self.const(part.param)}, {self.var(part.param)})",
                    )
                    self.lines.append(f"{segs}.extend({split})")
            tail = f"'/'.join({segs})"
            if head is None:
                return f"({anchor!r} + {tail} if {segs} else {anchor or '.'!r})"
            return f"_combine({head}, {segs})"
        # Join segment terms with "/", folding runs of literal segments into a
        # single string constant.
        terms: list[str] = []
        run: list[str] = []
        for i, part in enumerate(e.parts):
            assert isinstance(part, X.Seg)
            sep = "/" if i else ""
            if part.literal is not None:
                run.append(sep + part.literal)
                continue
            code = self.seg(part)
            if sep:
                run.append(sep)
            if run:
                terms.append(repr("".join(run)))
                run = []
            terms.append(code)
        if run:
            terms.append(repr("".join(run)))
        if not terms:
            return head or repr(anchor or ".")
        tail = " + ".join(terms)
        if head is None:
            return f"{anchor!r} + {tail}" if anchor else tail
        return (
            f"({tail} if {head} == '.' else "
            f"({head} + {tail} if {head}[-1] == '/' else {head} + '/' + {tail}))"
        )

    def function(self, result: str) -> str:
        body = "\n".join("        " + ln for ln in [*self.lines, f"return {result}"])
        return (
            "def _render(env):\n"
            "    try:\n"
            f"{body}\n"
            "    except Exception:\n"
            "        pass\n"
            "    return _slow(env)\n"
        )


class _Bail(Exception):
    pass


def _default(p: Param, env: Any) -> Any:
    """``p``'s default, for a mapping that does not bind ``p``'s name. A
    mapping keyed by `Param` may bind it under its declaration, which only the
    interpreter looks up."""
    for k in env:
        if isinstance(k, Param):
            raise _Bail
    return p.default


def compile_expr(expr: X.PathExpr) -> CompiledPath:
    expr.params  # noqa: B018 - surface declaration conflicts now
    gen = _Gen()
    source = gen.function(gen.emit(expr))
    interpret = expr.render

    def slow(env: Any) -> str:
        if type(env) is not dict and not isinstance(env, Mapping):
            # An object: render its bindings through the fast path.
            from ._bindings import object_bindings

            return ns["_render"](object_bindings(env))
        return interpret(env)

    ns: dict[str, Any] = {
        "_Bail": _Bail,
        "_default": _default,
        "_slow": slow,
        "_seg_value": X.seg_value,
        "_head_value": X.head_value,
        "_splice_value": X.splice_value,
        "_render_field": X._render_field,
        "_render_deferred": X._render_deferred,
        "_combine": X._combine,
        **gen.consts,
    }
    exec(compile(source, f"<wend {expr.pattern}>", "exec"), ns)  # noqa: S102
    fn = ns["_render"]
    if expr.conditions is not None and expr.conditions.bases:
        from .conditions import guarded

        fn = guarded(expr, fn)
    return CompiledPath(expr, fn, source)


class CompiledSet:
    """Several expressions compiled into one function (see `compile_many`).

    ``render`` returns each expression's rendering, in order (a dict when the
    expressions were given by name); it equals rendering them one by one, and
    raises what the first failing expression raises.
    """

    __slots__ = ("_fn", "exprs", "names", "source")

    def __init__(
        self,
        exprs: tuple[X.PathExpr, ...],
        names: tuple[str, ...] | None,
        fn: Any,
        source: str,
    ) -> None:
        self.exprs = exprs
        self.names = names
        self._fn = fn
        self.source = source

    def __repr__(self) -> str:
        return f"CompiledSet({', '.join(repr(e.pattern) for e in self.exprs)})"

    def render(self, mapping: Any = None, /, **kw: Any) -> Any:
        if kw:
            mapping = X._make_env(mapping, kw)
        out = self._fn(mapping if mapping is not None else {})
        return out if self.names is None else dict(zip(self.names, out, strict=True))

    def many(self, rows: Iterable[Any]) -> list[tuple[str, ...]]:
        """Render every expression for each mapping (or object) in ``rows``,
        as tuples."""
        fn = self._fn
        return [fn(r) for r in rows]


def compile_many(exprs: Mapping[str, X.PathExpr] | Iterable[X.PathExpr]) -> CompiledSet:
    """Compile a set of expressions into one function that renders them all.

    Work the expressions share is done once per call: each parameter is looked
    up, validated and formatted once however many expressions use it, a head
    or a SubPath is canonicalised or split once, and an identical segment is
    built once. Results and errors equal rendering each expression in turn.
    """
    if isinstance(exprs, Mapping):
        named = cast("Mapping[str, X.PathExpr]", exprs)
        names: tuple[str, ...] | None = tuple(named)
        items = tuple(named.values())
    else:
        names, items = None, tuple(exprs)
    for e in items:
        e.params  # noqa: B018 - surface declaration conflicts now
    gen = _Gen()
    results = [gen.emit(e) for e in items]
    source = gen.function("(" + "".join(f"{r}, " for r in results) + ")")

    def slow(env: Any) -> tuple[str, ...]:
        if type(env) is not dict and not isinstance(env, Mapping):
            # An object: render its bindings through the fast path.
            from ._bindings import object_bindings

            return ns["_render"](object_bindings(env))
        return tuple(e.render(env) for e in items)

    ns: dict[str, Any] = {
        "_Bail": _Bail,
        "_default": _default,
        "_slow": slow,
        "_seg_value": X.seg_value,
        "_head_value": X.head_value,
        "_splice_value": X.splice_value,
        "_render_field": X._render_field,
        "_render_deferred": X._render_deferred,
        "_combine": X._combine,
        **gen.consts,
    }
    label = ", ".join(e.pattern for e in items)
    exec(compile(source, f"<wend set {label}>", "exec"), ns)  # noqa: S102
    fn = ns["_render"]
    guarded_ = [
        (i, e)
        for i, e in enumerate(items)
        if e.conditions is not None and e.conditions.bases
    ]
    if guarded_:
        from .conditions import guard

        def fn(env: Any, _fn: Any = fn) -> tuple[str, ...]:
            # The fast path succeeds only when every expression renders, so
            # checking containment afterwards, in order, raises what
            # rendering them one by one would raise first.
            out = _fn(env)
            for i, e in guarded_:
                guard(e, out[i], X._make_env(env, {}))
            return out

    return CompiledSet(items, names, fn, source)
