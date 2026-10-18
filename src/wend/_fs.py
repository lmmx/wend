"""Filesystem discovery: find existing paths that match an expression.

The walk follows the expression's structure, one directory level per part: a
literal segment is a single ``lstat``, a templated segment filters directory
entries through the same segment matcher as `match`, and a ``Splice`` recurses
into subdirectories. Every result is verified by rendering its bindings.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any, Literal

from ._expr import (
    Deferred,
    HeadParam,
    PathExpr,
    Root,
    Seg,
    Splice,
    _make_env,
    _Rel,
    _render_deferred,
)
from ._match import (
    Match,
    _accept,
    _match_seg,
    _seg_fast,
    _unify,
    match_all,
    seg_plan,
)
from .errors import (
    AmbiguousMatchError,
    NotInvertibleError,
    NotStaticError,
    WendError,
    _ambiguity_handler,
    _check_option_keywords,
)


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
    mapping: Any = None,
    /,
    *,
    kind: str | None = None,
    follow_symlinks: bool = False,
    recurse_symlinks: bool = False,
    ambiguous: Literal["raise", "skip"]
    | Callable[[AmbiguousMatchError], object] = "raise",
    **kw: Any,
) -> Iterator[Match]:
    """Yield a `Match` for every existing path that ``expr`` can render.

    Bindings in ``mapping`` and keyword bindings fix parameters before the
    walk (the head of the expression must be bound or literal). ``kind``
    restricts results to ``"file"`` or ``"dir"``. Matches are yielded in
    path order. Argument errors are raised by the call; the walk runs as the
    result is iterated.

    **Options and bindings.** Options are keyword-only. A parameter that
    shares an option's name (``kind``, say) is bound through ``mapping``:
    ``glob(e, {"kind": "raw"}, kind="file")`` binds the parameter and sets
    the option. A ``kind=`` keyword without ``"kind"`` in ``mapping`` could
    mean either, so it raises `TypeError`. To set the option and leave such
    a parameter free, rename the parameter first: ``e.bind(kind=Param("k"))``.

    **Ambiguity.** A path that the expression renders under more than one
    binding has no single `Match`. ``ambiguous`` decides what happens to it:

    - ``"raise"`` (default): raise `AmbiguousMatchError` for the first such
      path, before any match is yielded;
    - ``"skip"``: leave it out and yield the other matches;
    - a callable: call it with an `AmbiguousMatchError` for each such path,
      then yield the other matches. ``ambiguous=report.append`` collects
      them; a callable that raises aborts the walk, as ``"raise"`` does.

    An ambiguous path is never yielded. Its error carries the path and all
    its readings, each a verified binding of ``expr`` (given bindings
    included) that renders to the path. A path reached through a followed
    symlink is also checked with `match_all`, so a reading that the link
    policy kept the walk from still counts. Errors are reported in path
    order, before the first match is yielded.

    A callback rather than a returned report object keeps ``glob`` an
    iterator of matches, makes ``"raise"`` the special case of a callback
    that raises (as with ``os.walk``'s ``onerror``), and means a report is
    never read before the walk has filled it.

    **Symlinks.** The walk starts at the expression's fixed prefix (its head
    and the literal segments that follow it), which is resolved like any
    path. Below that, symlinks are not followed by default: a symlinked
    directory is not descended into at any position, and ``kind`` judges a
    link as itself (neither a file nor a directory), so a link can only be
    yielded as the final component with ``kind=None``.
    ``follow_symlinks=True`` descends symlinked directories at segment
    positions and classifies links by their targets, as pathlib's glob
    does. ``recurse_symlinks=True`` descends them while recursing through a
    ``SubPath``, skipping any directory already on the current path so that
    link cycles terminate.

    This is a traversal policy, not a sandbox. The fixed prefix is resolved
    normally, a yielded link points wherever it points, and the tree can
    change between the walk and any use of its results. Where that matters,
    open results with ``O_NOFOLLOW`` or resolve and check them.
    """
    given = _make_env(mapping, kw)
    options = [
        ("kind", kind, None),
        ("follow_symlinks", follow_symlinks, False),
        ("recurse_symlinks", recurse_symlinks, False),
        ("ambiguous", ambiguous, "raise"),
    ]
    _check_option_keywords("glob", expr, given, options)
    if kind not in (None, "file", "dir"):
        raise ValueError("kind must be None, 'file' or 'dir'")
    on_ambiguous = _ambiguity_handler(ambiguous)
    e = expr.bind(given) if given else expr
    h = e.head
    if isinstance(h, _Rel):
        base = "."
    elif isinstance(h, Root):
        base = h.anchor
    elif isinstance(h, HeadParam):
        hint = (
            " (glob does not apply defaults; e.bind(e.defaults) does)"
            if h.param.has_default
            else ""
        )
        raise NotStaticError(
            f"Bind {h.param.name!r} (the root of {e.pattern!r}) before globbing{hint}"
        )
    else:
        assert isinstance(h, Deferred)
        if PathExpr(h).param_names:
            raise NotStaticError(
                f"The start of {e.pattern!r} depends on unbound parameters"
            )
        base = _render_deferred(h, {})
    # Given bindings belong to every result, which is a full binding of expr.
    keep = {k: v for k, v in given.items() if k in expr.param_names}
    return _discover(
        e, base, keep, kind, follow_symlinks, recurse_symlinks, on_ambiguous
    )


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a == b and all(type(v) is type(b[k]) for k, v in a.items())


def _through_link(path: str, base: str, cache: dict[str, bool]) -> bool:
    """Whether a directory of ``path`` below ``base`` is a symlink."""
    stop = "" if base == "." else base
    d = os.path.dirname(path)
    while len(d) > len(stop):
        hit = cache.get(d)
        if hit is None:
            hit = cache[d] = os.path.islink(d)
        if hit:
            return True
        d = os.path.dirname(d)
    return False


def _discover(
    e: PathExpr,
    base: str,
    keep: dict[str, Any],
    kind: str | None,
    follow_symlinks: bool,
    recurse_symlinks: bool,
    on_ambiguous: Callable[[AmbiguousMatchError], object] | None,
) -> Iterator[Match]:
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
        if prev is not env and not _same(prev, env):
            readings = clashes.setdefault(path, [prev])
            if not any(_same(env, r) for r in readings):
                readings.append(env)
    if (follow_symlinks or recurse_symlinks) and any(
        isinstance(p, Splice) for p in parts
    ):
        # Where a path passes through a linked directory, the symlink policy
        # (which differs between segment and SubPath positions, and prunes
        # cycles relative to where a SubPath starts) may have kept the walk
        # from one of its readings. Count those paths' readings by matching.
        links: dict[str, bool] = {}
        for path in found:
            if not _through_link(path, base, links):
                continue
            try:
                if len(match_all(e, path, limit=2)) > 1:
                    clashes[path] = match_all(e, path)
            except NotInvertibleError:
                pass
    for path in sorted(clashes):
        del found[path]
        error = AmbiguousMatchError(path, [{**keep, **r} for r in clashes[path]])
        if on_ambiguous is None:
            raise error
        on_ambiguous(error)
    for path in sorted(found):
        yield Match(path, {**keep, **found[path]})
