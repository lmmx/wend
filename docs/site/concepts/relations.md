---
description: "How an expression keeps the paths it was built from: base, base_rel, child, sibling, cousin, rebase and under."
---

# Relations

```python
from wend import P, Param, T

root, name = Param("root"), Param("name")
data = P(root) / "data" / T(t"{name}.csv")
schema = data.sibling("schema.json")
report = data.cousin("../reports", T(t"{name}.md"))
```

```pycon
>>> schema
PathExpr('{root}/data/schema.json')
>>> report
PathExpr('{root}/reports/{name}.md')
>>> moved = data.rebase(P(root) / "data", P("/archive") / "2026")
>>> moved
PathExpr('/archive/2026/{name}.csv')
>>> schema.rebase(data, moved)
PathExpr('/archive/2026/schema.json')
>>> report.rebase(data, moved)
PathExpr('/archive/reports/{name}.md')
```

`schema` and `report` are defined by `data`. Moving `data` to `/archive/2026` and
rebasing them onto the moved path recomputes them from it: the sibling stays next to the
data file, and the cousin stays one directory up.

## Derivations

Each expression records the public operation that built it and the arguments it was
given: its derivation. The derivation is not part of the path. Equality, hashing,
rendering and matching ignore it:

```pycon
>>> schema == P(root) / "data" / "schema.json"
True
>>> schema.derived_from(data)
True
>>> (P(root) / "data" / "schema.json").derived_from(data)
False
```

[`derived_from`][wend.PathExpr.derived_from] reports whether an expression was built from
another one.

## Base and relative part

A join records its left operand as its [`base`][wend.PathExpr.base] and its right
operand as its [`base_rel`][wend.PathExpr.base_rel]. `x / y`, `x.child(y)` and
`y.under(x)` are all joins. Bases chain, one per join:

```pycon
>>> config = P(root).child("config.yaml")
>>> config.base, config.base_rel
(PathExpr('{root}'), PathExpr('config.yaml'))
>>> data.base
PathExpr('{root}/data')
>>> data.base.base
PathExpr('{root}')
```

## Siblings and cousins

- [`sibling(n)`][wend.PathExpr.sibling] is `parent / n`.
- [`cousin(p, *names)`][wend.PathExpr.cousin] starts at `parent`. Each component of the
  relative path `p` is either `..`, which takes the parent, or a name, which is joined.
  Then each of `names` is joined.

Both are computed from the structure, so they need no bindings. A cousin with an absolute
`p` raises [`PathOperationError`][wend.PathOperationError].

## Rebasing

[`rebase`][wend.PathExpr.rebase] takes one or two arguments:

- `rebase(new)` replaces the base of a join: `config.rebase(P("/etc/app"))` is
  `/etc/app/config.yaml`.
- `rebase(old, new)` rebuilds the expression with `new` in place of every expression in
  its derivation that equals `old`, and applies each recorded operation again. The result
  equals building the expression from scratch with `new` in place of `old`.

```pycon
>>> config.rebase(P("/etc/app"))
PathExpr('/etc/app/config.yaml')
>>> report.rebase(root, P("/srv"))
PathExpr('/srv/reports/{name}.md')
```

If `old` is not in the derivation, it must be a structural prefix of the expression, and
the result is `new` joined with the rest of the path.
[`relative_to`][wend.PathExpr.relative_to] gives that rest:

```pycon
>>> data.relative_to(root)
PathExpr('data/{name}.csv')
```

## One fragment, many bases

[`under`][wend.PathExpr.under] places a relative expression below a base. One fragment
can be placed under several bases, and each result keeps the base it was given:

```pycon
>>> cache = P("cache") / "models"
>>> [cache.under(home) for home in ("/home/a/.app", "/home/b/.app")]
[PathExpr('/home/a/.app/cache/models'), PathExpr('/home/b/.app/cache/models')]
>>> cache.under(root)
PathExpr('{root}/cache/models')
>>> cache.under(root).base
PathExpr('{root}')
```

## Reference

- [`PathExpr.base`][wend.PathExpr.base], [`PathExpr.base_rel`][wend.PathExpr.base_rel],
  [`PathExpr.child`][wend.PathExpr.child], [`PathExpr.under`][wend.PathExpr.under],
  [`PathExpr.sibling`][wend.PathExpr.sibling], [`PathExpr.cousin`][wend.PathExpr.cousin],
  [`PathExpr.rebase`][wend.PathExpr.rebase],
  [`PathExpr.derived_from`][wend.PathExpr.derived_from]
- [SEMANTICS.md §9](https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#9-connectivity)
  (connectivity)
