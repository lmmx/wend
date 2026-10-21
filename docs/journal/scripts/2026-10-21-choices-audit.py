"""Compatibility audit for the semantics of ``choices=`` and ``type=``
(journal entry 2026-10-21-choices-semantics-89).

For every declaration, form and value in a corpus (each choice, and
values equal to it that format differently), it measures, under the
current rules and under each option, three guarantees:

- acceptance: the binding is accepted and renders a path;
- path completeness: ``match_all`` reads that path back at all;
- value recovery: some reading equals the bound value (``==``), and
  with the same type.

Options (none changes wend; each is simulated from outside):

- A: a choice accepts only values of a member's exact type, and ``type=``
  only exact instances;
- B: rendering a choice renders the member it equals, and a typed value
  its builtin representative (``int(v)``...);
- D: ``match`` reads a choice parameter as each member whose rendering is
  the text. Three variants: ``union`` (today's readings and the members'),
  ``members`` (members only, for choice parameters), and ``fallback``
  (members only where today's ``match`` finds nothing);
- E: a value is accepted only if it renders exactly as its
  representative (the member it equals, or ``int(v)``...) would, in
  every field it fills. Rendering is unchanged for what is accepted.

    uv run python docs/journal/scripts/2026-10-21-choices-audit.py
"""

from __future__ import annotations

import collections
import enum
import itertools
import math
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import PurePosixPath as PP
from typing import Any

from wend import AnyPath, P, Param, SubPath, T, _expr
from wend.errors import NotInvertibleError, WendError


class S(enum.StrEnum):
    TRAIN = "train"


class One(enum.IntEnum):
    ONE = 1


class Colour(enum.Enum):
    RED = 1


class Loud(str):
    """A str subclass with its own formatting."""

    __hash__ = str.__hash__

    def __format__(self, spec: str) -> str:
        return self.upper()


class Odd(int):
    """An int subclass with its own formatting."""

    def __format__(self, spec: str) -> str:
        return "abcd"


class Quiet(int):
    """An int subclass that formats as an int."""


NAN = float("nan")

# (label, choices, type, kind): kind "seg" for segment parameters, "sub" for
# a SubPath, "head" for a head.
DECLS: list[tuple[str, Any, Any, str]] = [
    ("{1}", {1}, None, "seg"),
    ("{1, 2}", {1, 2}, None, "seg"),
    ("{1.5}", {1.5}, None, "seg"),
    ("{True}", {True}, None, "seg"),
    ("{None}", {None}, None, "seg"),
    ("{'1', 1}", {"1", 1}, None, "seg"),
    ("{'a', 'b'}", {"a", "b"}, None, "seg"),
    ("{'train'}", {"train"}, None, "seg"),
    ("{S.TRAIN}", {S.TRAIN}, None, "seg"),
    ("{One.ONE}", {One.ONE}, None, "seg"),
    ("{Colour.RED}", {Colour.RED}, None, "seg"),
    ("{Decimal('1.0')}", {Decimal("1.0")}, None, "seg"),
    ("{0.0}", {0.0}, None, "seg"),
    ("{nan}", {NAN}, None, "seg"),
    ("int {1}", {1}, int, "seg"),
    ("float {1.5}", {1.5}, float, "seg"),
    ("str {'a'}", {"a"}, str, "seg"),
    ("bool {True}", {True}, bool, "seg"),
    ("Colour {RED}", {Colour.RED}, Colour, "seg"),
    ("int|str {1, '1'}", {1, "1"}, int | str, "seg"),
    ("int", None, int, "seg"),
    ("float", None, float, "seg"),
    ("str", None, str, "seg"),
    ("bool", None, bool, "seg"),
    ("SubPath {PP('a/b')}", {PP("a/b")}, None, "sub"),
    ("SubPath {'a/b'}", {"a/b"}, None, "sub"),
    ("head {PP('/a')}", {PP("/a")}, None, "head"),
    ("head {'/a'}", {"/a"}, None, "head"),
]


def forms(p: Param, kind: str) -> list[tuple[str, Any]]:
    if kind == "sub":
        return [("r/{s...}", P("r") / p)]
    if kind == "head":
        return [("{h}/x", P(p) / "x")]
    return [
        ("x/{c}.txt", P("x") / T(t"{p}.txt")),
        ("x/{c}", P("x") / p),
        ("x/{c:>4}", P("x") / T(t"{p:>4}")),
        ("x/{c!r}", P("x") / T(t"{p!r}")),
        ("x/{c:d}", P("x") / T(t"{p:d}")),
    ]


def twins(m: Any) -> list[Any]:
    """``m``, and values equal to it (or of its type) that may format
    differently."""
    out = [m]
    if isinstance(m, bool) or (
        isinstance(m, (int, float, Decimal)) and not isinstance(m, enum.Enum)
    ):
        try:
            f = float(m)
        except TypeError, ValueError:
            f = None
        if f is not None and not math.isnan(f):
            out += [f, complex(f), Decimal(str(f)), Fraction(f)]
            if f.is_integer():
                out += [int(f), Odd(int(f)), Quiet(int(f))]
                if f in (0.0, 1.0):
                    out.append(bool(f))
                if f == 1.0:
                    out.append(One.ONE)
            if f == 0.0:
                out.append(-0.0)
        elif f is not None:
            out.append(float("nan"))  # a different NaN object
    if isinstance(m, str) and not isinstance(m, PP):
        out += [Loud(m), str(m)]
        if m == "train":
            out.append(S.TRAIN)
    if isinstance(m, PP):
        out += [str(m)]
    if isinstance(m, enum.Enum):
        out.append(m.value)
    seen: list[Any] = []
    for v in out:
        if not any(type(v) is type(s) and (v == s or v is s) for s in seen):
            seen.append(v)
    return seen


TYPE_POOLS = {
    int: [3, True, Odd(3), Quiet(3), One.ONE],
    float: [1.5, -0.0, 0.0, NAN],
    str: ["a", Loud("a"), S.TRAIN],
    bool: [True, False],
}


def canon(path: str) -> str:
    return str(PP(path))


def key(env: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(sorted((k, type(v).__name__, repr(v)) for k, v in env.items()))


def current(e: Any, path: str) -> list[dict[str, Any]] | None:
    try:
        return e.match_all(path, limit=16)
    except NotInvertibleError:
        return None


def by_members(e: Any, path: str) -> list[dict[str, Any]]:
    """Readings with each choice parameter fixed to each member in turn:
    option D's readings of the choice parameters."""
    params = [p for p in e.params.values() if p.choices is not None]
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    pools = [sorted(p.choices, key=repr) for p in params]
    for combo in itertools.islice(itertools.product(*pools), 4096):
        fixed = {p.name: v for p, v in zip(params, combo, strict=True)}
        try:
            rest = e.bind(fixed).match_all(path, limit=16)
        except WendError, ValueError, TypeError:
            continue
        for r in rest:
            env = {**r, **fixed}
            try:
                if e.render(env) == canon(path):
                    out.setdefault(key(env), env)
            except WendError, ValueError, TypeError:
                pass
    return list(out.values())


def d_variants(e: Any, path: str) -> dict[str, list[dict[str, Any]] | None]:
    cur = current(e, path)
    mem = by_members(e, path)
    choice = {p.name for p in e.params.values() if p.choices is not None}
    if cur is None:
        union = mem
        members = mem
        fallback = mem
    else:
        u = {key(x): x for x in cur}
        for x in mem:
            u.setdefault(key(x), x)
        union = list(u.values())
        # Members only: today's readings, with every choice parameter's
        # value replaced by a member (keeping those that are members).
        members = mem if choice else cur
        fallback = cur if cur else mem
    # Canonical: today's readings and the members', where a reading of a
    # choice parameter becomes the member it equals if that member renders
    # the same path; otherwise it stays as read. A member need not render
    # what an equal value renders (choices={1}: 1.0 renders 1.0 under !r,
    # 1 renders 1), and every reading must still render the path.
    canon_out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for x in [*(cur or []), *mem]:
        env = dict(x)
        for name in choice:
            m = _member(e.params[name], env[name])
            if m is _NONE or m is env[name]:
                continue
            trial = {**env, name: m}
            try:
                if e.render(trial) == canon(path):
                    env = trial
            except WendError, ValueError, TypeError:
                pass
        canon_out.setdefault(key(env), env)
    return {
        "D-union": union,
        "D-members": members,
        "D-fallback": fallback,
        "D-canonical": list(canon_out.values()),
    }


_NONE = object()


def _member(p: Param, v: Any) -> Any:
    """The member of ``p.choices`` that ``v`` stands for: the one it is, or
    else the one it equals."""
    assert p.choices is not None
    for m in p.choices:
        if m is v:
            return m
    for m in p.choices:
        try:
            if m == v:
                return m
        except Exception:
            pass
    return _NONE


def representative(p: Param, v: Any) -> Any:
    """The value v stands for: the member it equals, or for a type the
    builtin of that type it converts to."""
    if p.choices is not None:
        for m in p.choices:
            try:
                if m == v or m is v:
                    return m
            except Exception:
                pass
        return v
    t = p.type
    if t in (int, float, str, bool):
        try:
            return t(v) if t is not str else str.__str__(v) if isinstance(v, str) else v
        except Exception:
            return v
    return v


def render(e: Any, name: str, v: Any) -> tuple[str | None, str]:
    try:
        return e.render({name: v}), ""
    except (WendError, ValueError, TypeError) as ex:
        return None, type(ex).__name__


def recovers(rs: list[dict[str, Any]] | None, name: str, v: Any) -> tuple[bool, bool]:
    if not rs:
        return False, False
    eq = any(r.get(name) == v or r.get(name) is v for r in rs)
    same = any(
        (r.get(name) == v or r.get(name) is v) and type(r.get(name)) is type(v)
        for r in rs
    )
    return eq, same


def main() -> None:
    rows = []
    for label, choices, typ, kind in DECLS:
        # Param equality treats choices={1}, {True} and {1.0} as equal, and
        # the template cache then returns an earlier declaration's Param
        # (journal entry, finding 1). Each declaration starts from an empty
        # cache so that it is measured as declared.
        _expr._TEMPLATES.clear()
        if kind == "sub":
            p = SubPath("s", choices=choices)
        elif kind == "head":
            p = AnyPath("h", choices=choices)
        else:
            p = Param("c", type=typ, choices=choices)
        values = (
            [v for m in sorted(choices, key=repr) for v in twins(m)]
            if choices is not None
            else TYPE_POOLS[typ]
        )
        for fname, e in forms(p, kind):
            for v in values:
                path, err = render(e, p.name, v)
                if path is None:
                    rows.append(
                        dict(decl=label, form=fname, value=v, accepted=False, err=err)
                    )
                    continue
                cur = current(e, path)
                ds = d_variants(e, path)
                rep = representative(p, v)
                path_b, _ = render(e, p.name, rep)
                exact = (
                    any(type(m) is type(v) and m == v for m in choices)
                    if choices is not None
                    else type(v) is typ
                )
                r_key = len(rows)
                is_member = choices is not None and any(
                    type(m) is type(v) and (m == v or m is v) for m in choices
                )
                rows.append(
                    dict(
                        member=is_member,
                        decl=label,
                        form=fname,
                        value=v,
                        accepted=True,
                        path=path,
                        cur=cur,
                        ds=ds,
                        rep=rep,
                        path_b=path_b,
                        a_accepts=exact,
                        e_accepts=path_b == path,
                        b_cur=current(e, path_b) if path_b else None,
                        b_ds=d_variants(e, path_b) if path_b else None,
                    )
                )
                r_expr[id(rows[r_key])] = e
    report(rows)


r_expr: dict[int, Any] = {}


def report(rows: list[dict[str, Any]]) -> None:
    acc = [r for r in rows if r["accepted"]]
    print(f"cases: {len(rows)}; accepted and rendered: {len(acc)}\n")

    def complete(rs: Any) -> bool:
        return bool(rs)

    print("## Path completeness and value recovery, by option\n")

    def line(name: str, keep, readings, path_of, changed=0) -> None:
        kept = [r for r in acc if keep(r)]
        miss = [r for r in kept if not complete(readings(r))]
        noeq = [r for r in kept if not recovers(readings(r), r_name(r), r["value"])[0]]
        nosame = [
            r for r in kept if not recovers(readings(r), r_name(r), r["value"])[1]
        ]
        refused = len(acc) - len(kept)
        print(
            f"| {name} | {len(kept)} | {len(miss)} | {len(noeq)} | {len(nosame)} | {changed} | {refused} |"
        )
        return miss

    def r_name(r: dict[str, Any]) -> str:
        return (
            "s"
            if r["form"].startswith("r/")
            else "h"
            if r["form"].startswith("{h}")
            else "c"
        )

    print("### Declared members only (the value is a member, of the member's type)\n")
    print(
        "| option | accepted | path not read back | value not recovered (==) | not recovered with its type | outputs changed | accepted today, refused |"
    )
    print("|---|---|---|---|---|---|---|")
    members = [r for r in acc if r.get("member")]
    for name, readings in [
        ("today", lambda r: r["cur"]),
        ("D-union", lambda r: r["ds"]["D-union"]),
        ("D-members", lambda r: r["ds"]["D-members"]),
        ("D-fallback", lambda r: r["ds"]["D-fallback"]),
        ("D-canonical", lambda r: r["ds"]["D-canonical"]),
    ]:
        miss = [r for r in members if not readings(r)]
        noeq = [
            r for r in members if not recovers(readings(r), r_name(r), r["value"])[0]
        ]
        nosame = [
            r for r in members if not recovers(readings(r), r_name(r), r["value"])[1]
        ]
        print(
            f"| {name} | {len(members)} | {len(miss)} | {len(noeq)} | {len(nosame)} | 0 | 0 |"
        )
        if name in ("today", "D-union"):
            for r in miss:
                print(f"|  ↳ `{r['decl']}` {r['form']} ← {r['value']!r} | | | | | | |")
    print("\n### All accepted values\n")
    print(
        "| option | accepted | path not read back | value not recovered (==) | not recovered with its type | outputs changed | accepted today, refused |"
    )
    print("|---|---|---|---|---|---|---|")
    miss_today = line("today", lambda r: True, lambda r: r["cur"], None)
    for d in ("D-union", "D-members", "D-fallback", "D-canonical"):
        line(d, lambda r: True, lambda r, d=d: r["ds"][d], None)
    line("A", lambda r: r["a_accepts"], lambda r: r["cur"], None)
    line("A + D-union", lambda r: r["a_accepts"], lambda r: r["ds"]["D-union"], None)
    changed_b = sum(1 for r in acc if r["path_b"] != r["path"])
    print(
        f"| B | {len(acc)} | {sum(1 for r in acc if not r['b_cur'])} | (n/a: renders the representative) | | {changed_b} | 0 |"
    )
    print(
        f"| B + D-union | {len(acc)} | {sum(1 for r in acc if not (r['b_ds'] or {}).get('D-union'))} | | | {changed_b} | 0 |"
    )
    line("E", lambda r: r["e_accepts"], lambda r: r["cur"], None)
    miss_ed = line(
        "E + D-union", lambda r: r["e_accepts"], lambda r: r["ds"]["D-union"], None
    )
    line(
        "E + D-fallback",
        lambda r: r["e_accepts"],
        lambda r: r["ds"]["D-fallback"],
        None,
    )
    line(
        "E + D-canonical",
        lambda r: r["e_accepts"],
        lambda r: r["ds"]["D-canonical"],
        None,
    )
    line(
        "A + D-canonical",
        lambda r: r["a_accepts"],
        lambda r: r["ds"]["D-canonical"],
        None,
    )
    print(
        f"| B + D-canonical | {len(acc)} | {sum(1 for r in acc if not (r['b_ds'] or {}).get('D-canonical'))} | | | {changed_b} | 0 |"
    )

    print("\n## Today: accepted bindings whose path is not read back\n")
    groups = collections.defaultdict(list)
    for r in miss_today:
        groups[r["decl"]].append(
            f"{r['form']} ← {r['value']!r} ({type(r['value']).__name__}) = {r['path']}"
        )
    for decl, items in groups.items():
        print(f"- `{decl}`: {len(items)}")
        for it in items[:4]:
            print(f"    - {it}")

    print("\n## D: what changes where today's match already reads the path\n")
    for d in ("D-union", "D-members", "D-fallback", "D-canonical"):
        amb = []
        diff = []
        for r in acc:
            cur = r["cur"]
            if not cur:
                continue
            new = r["ds"][d] or []
            ck = {key(x) for x in cur}
            nk = {key(x) for x in new}
            if ck != nk:
                (amb if len(nk) > len(ck) else diff).append(r)
        print(f"- {d}: {len(amb)} newly ambiguous, {len(diff)} with different readings")
        for r in (amb + diff)[:6]:
            print(
                f"    - `{r['decl']}` {r['form']} ← {r['value']!r}: today {r['cur']}, {d} {r['ds'][d]}"
            )

    print("\n## Checks on every D variant\n")
    for d in ("D-union", "D-members", "D-fallback", "D-canonical"):
        unsound = 0
        lost = []
        for r in acc:
            name = r_name(r)
            for b in r["ds"][d] or []:
                env = dict(b)
                try:
                    ok = r_expr[id(r)].render(env) == canon(r["path"])
                except Exception:
                    ok = False
                unsound += not ok
            if r["cur"] and not r["ds"][d]:
                lost.append(r)
        print(
            f"- {d}: {unsound} readings that do not render their path; {len(lost)} paths read today and not by {d}"
        )
    print("\n### D-canonical: readings that differ from today's (not ambiguity)\n")
    for r in acc:
        cur = r["cur"]
        new = r["ds"]["D-canonical"] or []
        if (
            cur
            and len(new) == len(cur)
            and {key(x) for x in cur} != {key(x) for x in new}
        ):
            n = r_name(r)
            print(
                f"- `{r['decl']}` {r['form']} ← {r['value']!r}: "
                f"{[f'{type(x[n]).__name__} {x[n]!r}' for x in cur]} → {[f'{type(x[n]).__name__} {x[n]!r}' for x in new]}"
            )

    print("\n## E: accepted today, refused (renders unlike its representative)\n")
    groups = collections.defaultdict(list)
    for r in acc:
        if not r["e_accepts"]:
            groups[r["decl"]].append(
                f"{r['form']} ← {r['value']!r}: {r['path']} vs {r['path_b']}"
            )
    for decl, items in groups.items():
        print(f"- `{decl}`: {len(items)}")
        for it in items[:3]:
            print(f"    - {it}")

    print("\n## E + D-union: accepted, but the path is still not read back\n")
    for r in miss_ed:
        print(f"- `{r['decl']}` {r['form']} ← {r['value']!r} = {r['path']}")

    print("\n## A: accepted today, refused\n")
    groups = collections.defaultdict(list)
    for r in acc:
        if not r["a_accepts"]:
            groups[r["decl"]].append(f"{r['value']!r} ({type(r['value']).__name__})")
    for decl, items in groups.items():
        print(f"- `{decl}`: {', '.join(sorted(set(items)))}")

    print("\n## B: outputs that change\n")
    groups = collections.defaultdict(list)
    for r in acc:
        if r["path_b"] != r["path"]:
            groups[r["decl"]].append(
                f"{r['form']} ← {r['value']!r}: {r['path']} → {r['path_b']}"
            )
    for decl, items in groups.items():
        print(f"- `{decl}`: {len(items)}")
        for it in items[:3]:
            print(f"    - {it}")


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    main()
