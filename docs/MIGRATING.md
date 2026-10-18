# Migrating from wend 0.1.x

wend 0.1.x was a proof of concept: a class per operation, with simplifications
applied when nodes were built. The rebuild keeps the 0.1 entry points (`Param`,
`P`, `T`, `/`, `resolve(mapping)`, `required_params()`, `parent`,
`with_suffix`, `with_name`) but changes what several of them mean. Where a
meaning changed, it is either a correctness fix or a deliberate tightening, and
both are listed here.

## Removed names

| 0.1.x | replacement |
|---|---|
| `LiteralExpr`, `ParamExpr`, `TemplateExpr`, `JoinExpr`, `ParentExpr`, `WithNameExpr`, `WithSuffixExpr` | one `PathExpr` type; inspect it with `.pattern`, `.params`, `.is_static`, `.is_absolute()` |
| `RelativePath(base, relative)` | `expr.base` and `expr.base_rel` for a path built by a join; `expr.rebase(new_base)`, `expr.rebase(base, new_base)`, `expr.relative_to(base)`, or `expr.bind(root=new_root_expr)` |
| `isinstance(e, JoinExpr)` and similar structural checks | `e.pattern`, `e.parts` |

## Behaviour changes

| change | 0.1.x | now | why |
|---|---|---|---|
| A parameter after the head of an expression | joined with any value (`dataset="a/b"`, `"../x"`, `"/etc"` all accepted) | a single segment; such values raise `InvalidBindingError` | static segment structure, and traversal safety for untrusted values; declare `SubPath("dataset")` to bind multi-segment paths |
| `(root / "a/b").parent` | `{root}` (wrong) | `{root}/a` | literal text is split into segments |
| `(root / dataset).parent` with `dataset="train/v2"` | `{root}` (wrong) | `dataset` must be a single segment; with `SubPath`, the parent is deferred and equals pathlib | the old rewrite assumed one segment without checking |
| `.with_suffix(a).with_suffix(b)` | collapsed to `.with_suffix(b)` (wrong for `""` and multi-dot suffixes) | same result as pathlib | suffix chains are no longer collapsed |
| `t"{x!r}"` and other conversions | ignored | applied | t-string semantics (PEP 750) |
| A template segment that formats to `""`, `.` or `..`, or a field that formats to a `/` | silently changed the path's structure | `InvalidBindingError` | see docs/SEMANTICS.md §4 |
| `t"{root}/x"` with `root=""` | `/x` (f-string semantics) | `x` | a whole-segment interpolation is joined like `/` |
| `P("data") / x` with `x=3` | `TypeError` from pathlib | `data/3`, as `t"data/{x}"` already gave | a segment formats a non-path value like `f"{x}"`; head and `SubPath` positions still require `str` or `os.PathLike` (docs/SEMANTICS.md §3) |
| `glob` and symlinks | (no `glob`) | not followed below the expression's literal prefix unless `follow_symlinks=True` | following links out of a tree is opt-in |
| `repr(expr)` | nested dataclasses | `PathExpr('{root}/data/{dataset}')` | readable patterns |
| Using a `Param` inside an f-string (`f"chunk_{idx}"`) | produced a string containing the Param's repr | `TypeError` pointing to t-strings | catches a silent bug |
| `resolve(...)` | mapping only | mapping and/or keyword arguments; `cls=` chooses the result type | |

## New, with no 0.1 counterpart

- `render` (to `str`), `bind` (partial binding, rebasing, renaming), `rebase`,
  `relative_to`, `name`/`stem`/`suffix` as symbolic text, `with_stem`,
  `parents`;
- `match`/`match_all`, `glob`, `Lens`, `compile`, `wend.frame`, `wend.infer`;
- parameter kinds (`Segment`, `SubPath`, `AnyPath`, `Absolute`), `type=` and
  `choices=`.

## Untrusted input

Safety applies to **parameter bindings**. A string joined directly is a literal
path with pathlib semantics, so `root / "../../etc"` is `root/../../etc`, and
`root / "/etc"` is `/etc`. Bind untrusted values to a parameter instead:

```py
safe = P("/srv/static") / Param("name")
safe.resolve(name=user_input)  # raises InvalidBindingError for traversal
```
