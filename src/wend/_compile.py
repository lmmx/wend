"""Compilation of path expressions to specialised Python functions.

`compile_expr` generates Python source for one expression: parameter lookups,
validation and formatting are inlined, literal text is pre-joined, and checks
that the expression's static structure makes redundant (segments that cannot
render to "", "." or "..") are omitted.

The generated fast path only has to be right when it succeeds. Any exception
inside it (a missing key, a format error, a failed check) falls back to the
reference interpreter, so errors and messages are identical by construction;
differential tests check that successful results are identical too.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from . import _expr as X
from ._params import Kind, Param


class CompiledPath:
    """A compiled expression. Call it like ``resolve``; ``render`` returns a str."""

    __slots__ = ("_fn", "expr", "source")

    def __init__(self, expr: X.PathExpr, fn: Any, source: str) -> None:
        self.expr = expr
        self._fn = fn
        self.source = source

    def __repr__(self) -> str:
        return f"CompiledPath({self.expr.pattern!r})"

    def render(self, mapping: Mapping[Any, Any] | None = None, /, **kw: Any) -> str:
        # Param keys and symbolic values miss the fast path's lookups or checks
        # and fall back to the interpreter, which handles them.
        if kw:
            mapping = X._make_env(mapping, kw)
        return self._fn(mapping if mapping is not None else {})

    def __call__(self, mapping: Mapping[Any, Any] | None = None, /, **kw: Any) -> Path:
        return Path(self.render(mapping, **kw))

    def many(self, rows: Iterable[Mapping[str, Any]]) -> list[str]:
        """Render each mapping in ``rows`` (keys are parameter names)."""
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
    def __init__(self, expr: X.PathExpr) -> None:
        self.expr = expr
        self.consts: dict[str, Any] = {}
        self.lines: list[str] = []
        self.vars: dict[str, str] = {}
        self.n = 0

    def const(self, value: Any) -> str:
        name = f"_k{len(self.consts)}"
        self.consts[name] = value
        return name

    def tmp(self) -> str:
        self.n += 1
        return f"_t{self.n}"

    def var(self, name: str) -> str:
        if name not in self.vars:
            v = f"_v{len(self.vars)}"
            self.vars[name] = v
            self.lines.append(f"{v} = env[{name!r}]")
        return self.vars[name]

    def field(self, f: X.Field) -> str:
        src = f.source
        if not isinstance(src, Param) or f.static_spec is None:
            return f"_render_field({self.const(f)}, env)"
        v = self.var(src.name)
        if f.role == "segment":
            if src.type is None and src.choices is None:
                # Inline seg_value for plain strings; anything else bails out.
                self.lines.append(
                    f"if type({v}) is not str or '/' in {v} or '\\x00' in {v} "
                    f"or {v} in ('', '.', '..'): raise _Bail"
                )
                return v
            t = self.tmp()
            self.lines.append(f"{t} = _seg_value({self.const(src)}, {v})")
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
        return t

    def seg(self, s: X.Seg) -> str:
        """An expression for the segment's text; literals become string constants."""
        if s.literal is not None:
            return repr(s.literal)
        terms = [repr(p) if isinstance(p, str) else self.field(p) for p in s.pieces]
        if len(terms) == 1 and not s.needs_check:
            return terms[0]
        t = self.tmp()
        self.lines.append(f"{t} = {' + '.join(terms)}")
        if s.needs_check:
            self.lines.append(f"if {t} in ('', '.', '..'): raise _Bail")
        return t

    def build(self) -> str:
        e = self.expr
        h = e.head
        if isinstance(h, X._Rel):
            head: str | None = None
            anchor = ""
        elif isinstance(h, X.Root):
            head, anchor = None, h.anchor
        elif isinstance(h, X.HeadParam):
            head, anchor = self.tmp(), ""
            p = h.param
            v = self.var(p.name)
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
        else:
            head, anchor = self.tmp(), ""
            self.lines.append(f"{head} = _render_deferred({self.const(h)}, env)")

        has_splice = any(isinstance(p, X.Splice) for p in e.parts)
        if has_splice:
            segs = self.tmp()
            self.lines.append(f"{segs} = []")
            for part in e.parts:
                if isinstance(part, X.Seg):
                    self.lines.append(f"{segs}.append({self.seg(part)})")
                else:
                    v = self.var(part.param.name)
                    self.lines.append(
                        f"{segs}.extend(_splice_value({self.const(part.param)}, {v}))"
                    )
            tail = f"'/'.join({segs})"
            if head is None:
                self.lines.append(
                    f"return {anchor!r} + {tail} if {segs} else {anchor or '.'!r}"
                )
            else:
                self.lines.append(f"return _combine({head}, {segs})")
        else:
            # Join segment terms with "/", folding runs of literal segments
            # into a single string constant.
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
                self.lines.append(f"return {(head or repr(anchor or '.'))}")
            else:
                tail = " + ".join(terms)
                if head is None:
                    self.lines.append(
                        f"return {anchor!r} + {tail}" if anchor else f"return {tail}"
                    )
                else:
                    self.lines.append(
                        f"return {tail} if {head} == '.' else "
                        f"({head} + {tail} if {head}[-1] == '/' else {head} + '/' + {tail})"
                    )
        body = "\n".join("        " + ln for ln in self.lines)
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


def compile_expr(expr: X.PathExpr) -> CompiledPath:
    expr.params  # noqa: B018 - surface declaration conflicts now
    gen = _Gen(expr)
    source = gen.build()
    ns: dict[str, Any] = {
        "_Bail": _Bail,
        "_slow": expr.render,
        "_seg_value": X.seg_value,
        "_head_value": X.head_value,
        "_splice_value": X.splice_value,
        "_render_field": X._render_field,
        "_render_deferred": X._render_deferred,
        "_combine": X._combine,
        **gen.consts,
    }
    exec(compile(source, f"<wend {expr.pattern}>", "exec"), ns)  # noqa: S102
    return CompiledPath(expr, ns["_render"], source)
