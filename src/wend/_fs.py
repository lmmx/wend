"""Filesystem discovery: find existing paths that match an expression.

The walk follows the expression's structure, one directory level per part: a
literal segment is a single ``lstat``, a templated segment filters directory
entries through the same segment matcher as `match`, and a ``Splice`` recurses
into subdirectories. Every result is verified by rendering its bindings.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from typing import Any

from ._expr import (
    Deferred,
    HeadParam,
    PathExpr,
    Root,
    Seg,
    _make_env,
    _Rel,
    _render_deferred,
)
from ._match import Match, _accept, _match_seg, _seg_fast, _unify, seg_plan
from .errors import AmbiguousMatchError, NotStaticError, WendError


def _child(d: str, name: str) -> str:
    if d == ".":
        return name
    if d.endswith("/"):
        return d + name
    return d + "/" + name


def _entries(d: str) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(d) as it:
            return sorted(it, key=lambda e: e.name)
    except OSError:
        return []


def _is_dir(entry: os.DirEntry[str], follow: bool) -> bool:
    try:
        return entry.is_dir(follow_symlinks=follow)
    except OSError:
        return False


def _dir_key(d: str) -> tuple[int, int] | None:
    try:
        st = os.stat(d)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def glob(
    expr: PathExpr,
    mapping: Mapping[Any, Any] | None = None,
    /,
    *,
    kind: str | None = None,
    follow_symlinks: bool = False,
    recurse_symlinks: bool = False,
    **kw: Any,
) -> Iterator[Match]:
    """Yield a `Match` for every existing path that ``expr`` can render.

    Keyword bindings fix parameters before the walk (the head of the
    expression must be bound or literal). ``kind`` restricts results to
    ``"file"`` or ``"dir"``.

    The walk starts at the expression's fixed prefix (its head and the
    literal segments that follow it), which is resolved like any path. Below
    that, symlinks are not followed by default: a symlinked directory is not
    descended into at any position, and ``kind`` judges a link as itself
    (neither a file nor a directory), so a link can only be yielded as the
    final component with ``kind=None``. ``follow_symlinks=True`` descends
    symlinked directories at segment positions and classifies links by
    their targets, as pathlib's glob does. ``recurse_symlinks=True``
    descends them while recursing through a ``SubPath``, skipping any
    directory already on the current path so that link cycles terminate.

    This is a traversal policy, not a sandbox. The fixed prefix is resolved
    normally, a yielded link points wherever it points, and the tree can
    change between the walk and any use of its results. Where that matters,
    open results with ``O_NOFOLLOW`` or resolve and check them.
    """
    if kind not in (None, "file", "dir"):
        raise ValueError("kind must be None, 'file' or 'dir'")
    given = _make_env(mapping, kw)
    e = expr.bind(given) if given else expr
    h = e.head
    if isinstance(h, _Rel):
        base = "."
    elif isinstance(h, Root):
        base = h.anchor
    elif isinstance(h, HeadParam):
        raise NotStaticError(
            f"Bind {h.param.name!r} (the root of {e.pattern!r}) before globbing"
        )
    else:
        assert isinstance(h, Deferred)
        if PathExpr(h).param_names:
            raise NotStaticError(
                f"The start of {e.pattern!r} depends on unbound parameters"
            )
        base = _render_deferred(h, {})

    parts = e.parts
    n = len(parts)
    # The walk starts below the fixed prefix: the head and the literal
    # segments after it, which are resolved like any other path.
    start = 0
    while start < n:
        part = parts[start]
        if not isinstance(part, Seg) or part.literal is None:
            break
        base = _child(base, part.literal)
        start += 1
    if not (os.path.isdir(base) if start < n else os.path.lexists(base)):
        return

    def walk(
        d: str, i: int, env: dict[str, Any]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        if i == n:
            yield d, env
            return
        part = parts[i]
        last = i == n - 1
        if isinstance(part, Seg):
            lit = part.literal
            if lit is not None:
                child = _child(d, lit)
                if last:
                    ok = os.path.lexists(child)
                else:
                    ok = os.path.isdir(child) and (
                        follow_symlinks or not os.path.islink(child)
                    )
                if ok:
                    yield from walk(child, i + 1, env)
                return
            plan = seg_plan(part)
            for entry in _entries(d):
                if not last and not _is_dir(entry, follow_symlinks):
                    continue
                if plan is not None:
                    env2 = _seg_fast(plan, entry.name, env)
                    if env2 is not None:
                        yield from walk(_child(d, entry.name), i + 1, env2)
                    continue
                for env2 in _match_seg(part, entry.name, env):
                    yield from walk(_child(d, entry.name), i + 1, env2)
            return
        param = part.param

        def splice(
            d: str, acc: list[str], seen: frozenset[tuple[int, int]]
        ) -> Iterator[tuple[str, dict[str, Any]]]:
            value = "/".join(acc) or "."
            if _accept(param, value):
                env2 = _unify(env, param.name, value)
                if env2 is not None:
                    yield from walk(d, i + 1, env2)
            for entry in _entries(d):
                if not _is_dir(entry, recurse_symlinks):
                    continue
                child = _child(d, entry.name)
                if recurse_symlinks:
                    key = _dir_key(child)
                    if key is None or key in seen:
                        continue
                    yield from splice(child, [*acc, entry.name], seen | {key})
                else:
                    yield from splice(child, [*acc, entry.name], seen)

        start = _dir_key(d) if recurse_symlinks else None
        yield from splice(d, [], frozenset() if start is None else frozenset({start}))

    render = e._compiled.render
    found: dict[str, dict[str, Any]] = {}
    clashes: dict[str, list[dict[str, Any]]] = {}
    for path, env in walk(base, start, {}):
        if kind is not None and not follow_symlinks and os.path.islink(path):
            continue
        if kind == "file" and not os.path.isfile(path):
            continue
        if kind == "dir" and not os.path.isdir(path):
            continue
        try:
            if render(env) != path:
                continue
        except WendError, ValueError:
            continue
        prev = found.setdefault(path, env)
        if prev != env:
            clashes.setdefault(path, [prev]).append(env)
    if clashes:
        path, cands = next(iter(clashes.items()))
        raise AmbiguousMatchError(path, cands)
    keep = {k: v for k, v in given.items() if k in expr.param_names}
    for path in sorted(found):
        yield Match(path, {**keep, **found[path]})
