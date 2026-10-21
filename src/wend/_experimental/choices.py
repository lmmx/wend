"""Prototypes for the semantics of ``choices=`` (experimental; see
`wend._experimental` and docs/journal/2026-10-21-choices-semantics-89.md).

Nothing here changes how wend renders or matches. Two functions simulate,
from outside, the rules the journal entry proposes:

- `match_all` reads a parameter with ``choices`` as each member whose
  rendering is the text, as well as whatever `wend.PathExpr.match_all`
  reads today. A reading equal to a member becomes that member when the
  member renders the same path ("D-canonical").
- `faithful` says whether a binding renders as its representatives
  would: each choice value as the member it equals, each value of a
  builtin declared type as that type's own instance ("E").

`match_all` fixes each choice parameter to each member through
`wend.PathExpr.bind`, so it costs one match per combination of members:
fine for a prototype, not for the matcher. Inside wend the same rule is a
per-field one (the members' renderings are a finite set of texts).
"""

from __future__ import annotations

import itertools
from pathlib import PurePosixPath
from typing import Any

from .._expr import PathExpr
from .._params import Param
from ..errors import NotInvertibleError, WendError


MAX_COMBINATIONS = 4096
BUILTIN_TYPES = (bool, int, float, str)


def member(p: Param, value: Any) -> Any:
    """The member of ``p.choices`` that ``value`` stands for: itself if it
    is one, else the member it equals. Raises KeyError if none."""
    assert p.choices is not None
    for m in p.choices:
        if m is value:
            return m
    for m in p.choices:
        try:
            if m == value:
                return m
        except Exception:  # a value whose comparison fails is no member
            pass
    raise KeyError(value)


def representative(p: Param, value: Any) -> Any:
    """What ``value`` stands for under ``p``'s declaration: the member it
    equals, an instance of the declared builtin type (``int(True)`` for
    ``type=int``), or ``value`` itself."""
    if p.choices is not None:
        return member(p, value)
    t = p.type
    if t in BUILTIN_TYPES and type(value) is not t:
        if t is str:
            return str.__str__(value)
        return t(value)
    return value


def faithful(e: PathExpr, env: dict[str, Any]) -> bool:
    """Whether ``e`` renders ``env`` exactly as it renders the
    representatives of its values (rule E). False if ``env`` does not
    render at all."""
    try:
        path = e.render(env)
    except WendError, ValueError, TypeError:
        return False
    reps = dict(env)
    for name, p in e.params.items():
        if name in env and (p.choices is not None or p.type in BUILTIN_TYPES):
            try:
                reps[name] = representative(p, env[name])
            except KeyError, ValueError, TypeError:
                return False
    try:
        return e.render(reps) == path
    except WendError, ValueError, TypeError:
        return False


def match_all(e: PathExpr, path: str, limit: int = 16) -> list[dict[str, Any]]:
    """Bindings of ``e`` that render ``path``, reading each parameter with
    ``choices`` as its members (rule D-canonical); every binding is
    verified by rendering. Raises NotInvertibleError where wend's matcher
    does and no member reading exists."""
    target = str(PurePosixPath(path))
    choice = {n: p for n, p in e.params.items() if p.choices is not None}
    try:
        today = e.match_all(path, limit=limit)
        error: NotInvertibleError | None = None
    except NotInvertibleError as ex:
        today, error = [], ex
    found: list[dict[str, Any]] = []
    names = sorted(choice)
    pools = [sorted(choice[n].choices or (), key=repr) for n in names]
    for combo in itertools.islice(itertools.product(*pools), MAX_COMBINATIONS):
        fixed = dict(zip(names, combo, strict=True))
        try:
            rest = e.bind(fixed).match_all(path, limit=limit)
        except WendError, ValueError, TypeError:
            continue
        found += [{**r, **fixed} for r in rest]
    out: list[dict[str, Any]] = []
    for env in [*today, *found]:
        env = dict(env)
        for n in choice:
            try:
                m = member(choice[n], env[n])
            except KeyError:
                continue
            if m is not env[n] and _renders(e, {**env, n: m}, target):
                env[n] = m
        if not _renders(e, env, target):
            continue
        if not any(_same(env, o) for o in out):
            out.append(env)
        if len(out) >= limit:
            break
    if not out and error is not None:
        raise error
    return out


def _renders(e: PathExpr, env: dict[str, Any], target: str) -> bool:
    try:
        return e.render(env) == target
    except WendError, ValueError, TypeError:
        return False


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a.keys() == b.keys() and all(
        type(a[k]) is type(b[k]) and (a[k] is b[k] or a[k] == b[k]) for k in a
    )


__all__ = ["faithful", "match_all", "member", "representative"]
