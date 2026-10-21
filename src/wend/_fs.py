"""Filesystem discovery: find existing paths that match an expression.

The walk follows the expression's structure, one directory level per part: a
literal segment is a single ``lstat``, a templated segment filters directory
entries through the same segment matcher as `match`, and a ``Splice`` recurses
into subdirectories. Every result is verified by rendering its bindings. The
walk reads the tree through a `wend.fs.FileSystem`: the local disk, unless
``fs=`` names another.
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
from .fs import LOCAL, DirEntry, FileSystem, _check_root, _child


def _is_dir(entry: DirEntry, follow: bool) -> bool:
    try:
        return entry.is_dir(follow_symlinks=follow)
    except OSError:
        return False


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
    fs: FileSystem | None = None,
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

    A ``SubPath`` can be empty, so where only ``SubPath`` parameters follow a
    position, a path can end there on a file (or a link, under the rules
    above) as well as on a directory: ``P("srv") / SubPath("rest")`` yields
    the files below ``srv`` as well as its directories, as pathlib's
    ``srv.glob("**")`` with files does.

    This is a traversal policy, not a sandbox. The fixed prefix is resolved
    normally, a yielded link points wherever it points, and the tree can
    change between the walk and any use of its results. Where that matters,
    open results with ``O_NOFOLLOW`` or resolve and check them.

    **Filesystems.** ``fs`` is the `wend.fs.FileSystem` to walk: the local
    disk by default, or a `wend.fs.FsspecFS` for an fsspec filesystem such
    as an object store, where results are the same as for an identical
    local tree. Paths are in that filesystem's namespace: bind the root that
    `wend.fs.url_to_fs` gives (``bucket/data`` for ``s3://bucket/data``). A
    URL bound as a path is refused. Stores have no symlinks, so the symlink
    options change nothing there.
    """
    given = _make_env(mapping, kw)
    options = _options(kind, follow_symlinks, recurse_symlinks, ambiguous, fs)
    _check_option_keywords("glob", expr, given, options)
    return _glob(
        expr,
        given,
        kind,
        follow_symlinks,
        recurse_symlinks,
        _ambiguity_handler(ambiguous),
        fs,
    )


def _options(
    kind: str | None,
    follow_symlinks: bool,
    recurse_symlinks: bool,
    ambiguous: Any,
    fs: FileSystem | None,
) -> list[tuple[str, Any, Any]]:
    """`glob`'s options, with their defaults, for `_check_option_keywords`."""
    return [
        ("kind", kind, None),
        ("follow_symlinks", follow_symlinks, False),
        ("recurse_symlinks", recurse_symlinks, False),
        ("ambiguous", ambiguous, "raise"),
        ("fs", fs, None),
    ]


def _glob(
    expr: PathExpr,
    given: dict[str, Any],
    kind: str | None,
    follow_symlinks: bool,
    recurse_symlinks: bool,
    on_ambiguous: Callable[[AmbiguousMatchError], object] | None,
    fs: FileSystem | None,
) -> Iterator[Match]:
    """`glob`, once its bindings are gathered and its options checked against
    them (a union checks them once, for every alternative)."""
    if kind not in (None, "file", "dir"):
        raise ValueError("kind must be None, 'file' or 'dir'")
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
    # The walk starts below the fixed prefix: the head and the literal
    # segments after it, which are resolved like any other path.
    parts = e.parts
    start = 0
    while start < len(parts):
        part = parts[start]
        if not isinstance(part, Seg) or part.literal is None:
            break
        base = _child(base, part.literal)
        start += 1
    fs = LOCAL if fs is None else fs
    _check_root(fs, base)
    # Given bindings belong to every result, which is a full binding of expr.
    keep = {k: v for k, v in given.items() if k in expr.param_names}
    return _discover(
        e,
        base,
        start,
        keep,
        kind,
        follow_symlinks,
        recurse_symlinks,
        on_ambiguous,
        fs,
    )


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a == b and all(type(v) is type(b[k]) for k, v in a.items())


def _through_link(path: str, base: str, cache: dict[str, bool], fs: FileSystem) -> bool:
    """Whether a directory of ``path`` below ``base`` is a symlink."""
    stop = "" if base == "." else base
    d = os.path.dirname(path)
    while len(d) > len(stop):
        hit = cache.get(d)
        if hit is None:
            hit = cache[d] = fs.kind(d, follow_symlinks=False) == "link"
        if hit:
            return True
        d = os.path.dirname(d)
    return False


def _discover(
    e: PathExpr,
    base: str,
    start: int,
    keep: dict[str, Any],
    kind: str | None,
    follow_symlinks: bool,
    recurse_symlinks: bool,
    on_ambiguous: Callable[[AmbiguousMatchError], object] | None,
    fs: FileSystem,
) -> Iterator[Match]:
    parts = e.parts
    n = len(parts)
    # A SubPath can be empty ("."), so a path can end at position i when every
    # part from i on is a SubPath: any entry there, not only a directory, can
    # be the path's last component (#82).
    ends_here = [True] * (n + 1)
    for j in range(n - 1, -1, -1):
        ends_here[j] = ends_here[j + 1] and isinstance(parts[j], Splice)

    def ends(
        path: str, j: int, env: dict[str, Any]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """``path`` with the SubPaths from position ``j`` on all empty."""
        for part in parts[j:]:
            if not isinstance(part, Splice) or not _accept(part.param, "."):
                return
            bound = _unify(env, part.param.name, ".")
            if bound is None:
                return
            env = bound
        yield path, env

    on_entry = False
    if start < n:
        # One view of the tree below the fixed prefix serves the whole walk,
        # so an object store can list it with one request.
        fs = fs.subtree(base)
        if fs.kind(base) != "dir":
            if not ends_here[start] or fs.kind(base, follow_symlinks=False) is None:
                return
            on_entry = True
    elif fs.kind(base, follow_symlinks=False) is None:
        return
    scandir, kind_of, dir_key = fs.scandir, fs.kind, fs.dir_key

    def walk(
        d: str, i: int, env: dict[str, Any]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        if i == n:
            yield d, env
            return
        part = parts[i]
        last = i == n - 1
        # Whether the parts after this one can all be empty.
        empty_after = ends_here[i + 1]
        if isinstance(part, Seg):
            lit = part.literal
            if lit is not None:
                child = _child(d, lit)
                if last:
                    if kind_of(child, follow_symlinks=False) is not None:
                        yield from walk(child, i + 1, env)
                elif kind_of(child, follow_symlinks=follow_symlinks) == "dir":
                    yield from walk(child, i + 1, env)
                elif empty_after and kind_of(child, follow_symlinks=False) is not None:
                    yield from ends(child, i + 1, env)
                return
            plan = seg_plan(part)
            for entry in scandir(d):
                descend = last or _is_dir(entry, follow_symlinks)
                if not descend and not empty_after:
                    continue
                go = walk if descend else ends
                if plan is not None:
                    env2 = _seg_fast(plan, entry.name, env)
                    if env2 is not None:
                        yield from go(_child(d, entry.name), i + 1, env2)
                    continue
                for env2 in _match_seg(part, entry.name, env):
                    yield from go(_child(d, entry.name), i + 1, env2)
            return
        param = part.param

        # Only where nothing after this SubPath needs a directory can an entry
        # it does not descend into end the path. A regular file is never a
        # directory, so with kind="dir" only links are considered.
        links_only = kind == "dir"

        def end_on(
            d: str, acc: list[str], entry: DirEntry
        ) -> Iterator[tuple[str, dict[str, Any]]]:
            """``entry``, not descended into, as the SubPath's last segment."""
            value = "/".join([*acc, entry.name])
            if _accept(param, value):
                env2 = _unify(env, param.name, value)
                if env2 is not None:
                    yield from ends(_child(d, entry.name), i + 1, env2)

        def splice(
            d: str, acc: list[str], seen: frozenset[Any]
        ) -> Iterator[tuple[str, dict[str, Any]]]:
            value = "/".join(acc) or "."
            if _accept(param, value):
                env2 = _unify(env, param.name, value)
                if env2 is not None:
                    yield from walk(d, i + 1, env2)
            for entry in scandir(d):
                if not _is_dir(entry, recurse_symlinks):
                    if empty_after and (not links_only or entry.is_symlink()):
                        yield from end_on(d, acc, entry)
                    continue
                child = _child(d, entry.name)
                if recurse_symlinks:
                    try:
                        key = dir_key(child)
                    except OSError:
                        continue
                    if key is None:
                        # Nothing to detect a cycle with: descend only
                        # directories that are not links.
                        if entry.is_symlink():
                            if empty_after:
                                yield from end_on(d, acc, entry)
                            continue
                        yield from splice(child, [*acc, entry.name], seen)
                    elif key not in seen:
                        yield from splice(child, [*acc, entry.name], seen | {key})
                    elif empty_after:
                        # A link back to a directory on this path: not
                        # descended, so that the walk terminates.
                        yield from end_on(d, acc, entry)
                else:
                    yield from splice(child, [*acc, entry.name], seen)

        top = None
        if recurse_symlinks:
            try:
                top = dir_key(d)
            except OSError:
                pass
        yield from splice(d, [], frozenset() if top is None else frozenset({top}))

    render = e._compiled.render
    found: dict[str, dict[str, Any]] = {}
    clashes: dict[str, list[dict[str, Any]]] = {}
    walked = ends(base, start, {}) if on_entry else walk(base, start, {})
    for path, env in walked:
        # Unless links are followed, a link is neither a file nor a directory.
        if kind is not None and kind_of(path, follow_symlinks=follow_symlinks) != kind:
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
            if not _through_link(path, base, links, fs):
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
