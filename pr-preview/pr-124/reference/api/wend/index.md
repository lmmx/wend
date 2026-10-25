# wend

Symbolic, typed, invertible filesystem paths built from Python t-strings.

A path expression records how a path is built (which parts are literal, which are parameters, how values are formatted) instead of collapsing it to a string. The same expression can be resolved with bindings, partially bound, transformed structurally, matched against concrete paths, used to discover files on disk, and compiled for fast batch resolution.

## Building expressions

### wend.P

```python
P(arg: PathExpr[CA, KA]) -> PathExpr[CA, KA]
```

```python
P(arg: str | PathLike[str] | Param | Template) -> PathExpr
```

Make a path expression from a str, PathLike, Param, t-string, Text or PathExpr.

### wend.T

```python
T(template: Template) -> PathExpr
```

Make a path expression from a t-string.

### wend.PathExpr

```python
PathExpr(head: Head, parts: tuple[Part, ...] = ())
```

Bases: `_Cached`, `Generic[C, K, Q]`

A symbolic path. Build with `P`, `T`, or `Param / ...`.

For a type checker, `C` is what it requires, `K` whether it is declared a File, and `Q` what it ensures (`wend._kinds`).

#### head

```python
head: Head
```

#### parts

```python
parts: tuple[Part, ...] = ()
```

#### derivation

```python
derivation: Derivation | None = None
```

#### conditions

```python
conditions: Conditions | None = None
```

#### tags

```python
tags: Mapping[str, Any] = MappingProxyType({})
```

#### \_\_truediv\_\_

```python
__truediv__(other: Any) -> JoinBelowFile
```

```python
__truediv__(other: PathUnion) -> PathUnion
```

```python
__truediv__(
    other: str | PathLike[str] | Param | PathExpr[Any, Any] | Template,
) -> PathExpr
```

#### \_\_rtruediv\_\_

```python
__rtruediv__(other: str | PathLike[str] | Param) -> PathExpr
```

#### joinpath

```python
joinpath(*others: Any) -> PathExpr
```

#### \_\_or\_\_

```python
__or__(other: Any) -> PathUnion
```

The union of this path and `other`: `a | b` (§11).

#### \_\_ror\_\_

```python
__ror__(other: Any) -> PathUnion
```

#### \_\_sub\_\_

```python
__sub__(other: Any) -> Query
```

A query for the paths this one finds that `other` does not match.

#### \_\_and\_\_

```python
__and__(other: Any) -> Query
```

A query for the paths this one finds that `other` also matches.

#### where

```python
where(*predicates: Any) -> Query
```

A query for the paths this one finds for which every predicate holds.

#### child

```python
child(*parts: Any) -> PathExpr
```

`self / part / ...`, remembering `self` as the base (§9).

#### under

```python
under(base: Any) -> PathExpr
```

`base / self`: place a relative fragment under `base`.

#### base

```python
base: PathExpr | None
```

The path this one was joined onto, or None if it was not built by a join. Bases chain: `(root / "a" / "b").base.base` is `root`.

#### base\_rel

```python
base_rel: PathExpr | None
```

What was joined onto `base`, as an expression in that position.

#### sibling

```python
sibling(name: Any) -> PathExpr
```

`self.parent / name`, remembering that it is defined by `self`: rebasing `self` elsewhere moves the sibling with it (§9).

#### cousin

```python
cousin(path: Any, *names: Any) -> PathExpr
```

A path reached from this one's directory: `path` is relative to `self.parent`, its leading (or any) `..` steps up structurally, and `names` are joined after it. `x.cousin("../out", "y.csv")` is `x.parent.parent / "out" / "y.csv"`, defined by `x` (§9).

#### derived\_from

```python
derived_from(other: Any) -> bool
```

Whether `other` is among the expressions this one was built from.

#### requires

```python
requires() -> PathExpr[C, K]
```

```python
requires(file: FileCondition) -> PathExpr[C | Literal['file'], IsFile]
```

```python
requires(
    file: FileCondition, c1: Condition[X1, Any]
) -> PathExpr[C | Literal["file"] | X1, IsFile]
```

```python
requires(
    file: FileCondition, c1: Condition[X1, Any], c2: Condition[X2, Any]
) -> PathExpr[C | Literal["file"] | X1 | X2, IsFile]
```

```python
requires(
    file: FileCondition,
    c1: Condition[X1, Any],
    c2: Condition[X2, Any],
    c3: Condition[X3, Any],
) -> PathExpr[C | Literal["file"] | X1 | X2 | X3, IsFile]
```

```python
requires(
    file: FileCondition,
    c1: Condition[X1, Any],
    c2: Condition[X2, Any],
    c3: Condition[X3, Any],
    c4: Condition[X4, Any],
) -> PathExpr[C | Literal["file"] | X1 | X2 | X3 | X4, IsFile]
```

```python
requires(
    file: FileCondition,
    c1: Condition[X1, Any],
    c2: Condition[X2, Any],
    c3: Condition[X3, Any],
    c4: Condition[X4, Any],
    c5: Condition[X5, Any],
) -> PathExpr[C | Literal["file"] | X1 | X2 | X3 | X4 | X5, IsFile]
```

```python
requires(c1: Condition[X1, Any]) -> PathExpr[C | X1, K]
```

```python
requires(
    c1: Condition[X1, Any], c2: Condition[X2, Any]
) -> PathExpr[C | X1 | X2, K]
```

```python
requires(
    c1: Condition[X1, Any], c2: Condition[X2, Any], c3: Condition[X3, Any]
) -> PathExpr[C | X1 | X2 | X3, K]
```

```python
requires(
    c1: Condition[X1, Any],
    c2: Condition[X2, Any],
    c3: Condition[X3, Any],
    c4: Condition[X4, Any],
) -> PathExpr[C | X1 | X2 | X3 | X4, K]
```

```python
requires(
    c1: Condition[X1, Any],
    c2: Condition[X2, Any],
    c3: Condition[X3, Any],
    c4: Condition[X4, Any],
    c5: Condition[X5, Any],
) -> PathExpr[C | X1 | X2 | X3 | X4 | X5, K]
```

```python
requires(
    c1: Condition[X1, Any],
    c2: Condition[X2, Any],
    c3: Condition[X3, Any],
    c4: Condition[X4, Any],
    c5: Condition[X5, Any],
    c6: Condition[X6, Any],
) -> PathExpr[C | X1 | X2 | X3 | X4 | X5 | X6, K]
```

```python
requires(*conds: Condition[Any, Any]) -> PathExpr[C, K]
```

This path, declaring conditions that must hold before it is used (checked by `check`): `e.requires(File, Exists, Readable)`. See `wend.conditions`. The path, its equality and its derivation are unchanged.

#### ensures

```python
ensures() -> PathExpr[C, K]
```

```python
ensures(file: FileCondition) -> PathExpr[C | Literal['post_file'], IsFile]
```

```python
ensures(
    file: FileCondition, c1: Condition[Any, X1]
) -> PathExpr[C | Literal["post_file"] | X1, IsFile]
```

```python
ensures(
    file: FileCondition, c1: Condition[Any, X1], c2: Condition[Any, X2]
) -> PathExpr[C | Literal["post_file"] | X1 | X2, IsFile]
```

```python
ensures(
    file: FileCondition,
    c1: Condition[Any, X1],
    c2: Condition[Any, X2],
    c3: Condition[Any, X3],
) -> PathExpr[C | Literal["post_file"] | X1 | X2 | X3, IsFile]
```

```python
ensures(
    file: FileCondition,
    c1: Condition[Any, X1],
    c2: Condition[Any, X2],
    c3: Condition[Any, X3],
    c4: Condition[Any, X4],
) -> PathExpr[C | Literal["post_file"] | X1 | X2 | X3 | X4, IsFile]
```

```python
ensures(
    file: FileCondition,
    c1: Condition[Any, X1],
    c2: Condition[Any, X2],
    c3: Condition[Any, X3],
    c4: Condition[Any, X4],
    c5: Condition[Any, X5],
) -> PathExpr[C | Literal["post_file"] | X1 | X2 | X3 | X4 | X5, IsFile]
```

```python
ensures(c1: Condition[Any, X1]) -> PathExpr[C | X1, K]
```

```python
ensures(
    c1: Condition[Any, X1], c2: Condition[Any, X2]
) -> PathExpr[C | X1 | X2, K]
```

```python
ensures(
    c1: Condition[Any, X1], c2: Condition[Any, X2], c3: Condition[Any, X3]
) -> PathExpr[C | X1 | X2 | X3, K]
```

```python
ensures(
    c1: Condition[Any, X1],
    c2: Condition[Any, X2],
    c3: Condition[Any, X3],
    c4: Condition[Any, X4],
) -> PathExpr[C | X1 | X2 | X3 | X4, K]
```

```python
ensures(
    c1: Condition[Any, X1],
    c2: Condition[Any, X2],
    c3: Condition[Any, X3],
    c4: Condition[Any, X4],
    c5: Condition[Any, X5],
) -> PathExpr[C | X1 | X2 | X3 | X4 | X5, K]
```

```python
ensures(
    c1: Condition[Any, X1],
    c2: Condition[Any, X2],
    c3: Condition[Any, X3],
    c4: Condition[Any, X4],
    c5: Condition[Any, X5],
    c6: Condition[Any, X6],
) -> PathExpr[C | X1 | X2 | X3 | X4 | X5 | X6, K]
```

```python
ensures(*conds: Condition[Any, Any]) -> PathExpr[C, K]
```

This path, declaring conditions that must hold after it has been produced (checked by `confirm`): `e.ensures(File, Exists)`.

#### declares

```python
declares: Declarations
```

What this expression declares, as atoms per phase and the bases it is declared `Under` (docs/SEMANTICS.md §10.1): an obligation the runtime checks, not a fact about the filesystem.

#### tag

```python
tag(**tags: Any) -> PathExpr[C, K]
```

This path, tagged with metadata (`source="upload"`): what it is for or where it came from. Tags take no part in equality; `bind` and `rebase` keep them, other operations do not, and `wend.lineage` collects them through a path's derivation (§13).

#### check

```python
check(mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> Checked[C, K]
```

Render, check every precondition against the filesystem now, and return the path. Raises a `ConditionError` for the first that fails: `IndeterminateError` when the filesystem cannot say. `fs` is a `wend.fs` filesystem (the local disk by default). The path carries no evidence of the check; `checked` returns the evidence.

#### confirm

```python
confirm(mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> Path
```

Render, check every postcondition against the filesystem now, and return the path. Raises a `ConditionError` for the first that fails, as `check` does; `confirmed` returns the evidence.

#### checked

```python
checked(mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> Checked[C, K]
```

`check`, returning the evidence instead of the path (SEMANTICS.md §10.2): a `Checked` recording the path, the atoms this expression requires and the bases it was found under, each found true by a lookup of the path during this call. Raises as `check` does, so there is no evidence of a check that failed. Its type carries what this expression requires and nothing it ensures. It records the past: a later change does not update it.

#### confirmed

```python
confirmed(mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> Confirmed[Q, K]
```

`confirm`, returning the evidence (SEMANTICS.md §10.2): a `Confirmed` recording the path and the atoms this expression ensures, found true during this call. Its type carries what it ensures and nothing it requires.

#### param\_names

```python
param_names: frozenset[str]
```

#### params

```python
params: Mapping[str, Param]
```

Free parameters by name. Raises ParamConflictError on clashing declarations.

#### required\_params

```python
required_params() -> set[str]
```

Names of the parameters rendering needs a binding for: every free parameter without a default (§3.1).

#### defaults

```python
defaults: dict[str, Any]
```

The defaults of the free parameters that declare one, by name. Rendering uses them for names it is not given; `e.bind(e.defaults)` applies them explicitly (§3.1).

#### is\_static

```python
is_static: bool
```

True if the expression has no free parameters.

#### is\_absolute

```python
is_absolute() -> bool | None
```

True/False when known from structure, None when it depends on bindings.

#### pattern

```python
pattern: str
```

A t-string-like rendering of the expression's structure.

#### parent

```python
parent: PathExpr
```

#### parents

```python
parents: tuple[PathExpr, ...]
```

#### name

```python
name: Text
```

#### suffix

```python
suffix: Text
```

#### stem

```python
stem: Text
```

#### suffixes

```python
suffixes: tuple[Text, ...]
```

#### with\_name

```python
with_name(name: Any) -> PathExpr
```

#### with\_suffix

```python
with_suffix(suffix: Any) -> PathExpr
```

#### with\_stem

```python
with_stem(stem: Any) -> PathExpr
```

#### relative\_to

```python
relative_to(other: Any) -> PathExpr
```

The path of self relative to other.

Static when other is structurally a prefix of self, so a relation between unbound paths (`config.relative_to(root)`) needs no bindings.

#### is\_relative\_to

```python
is_relative_to(other: Any) -> bool
```

True if structurally a prefix; raises NotStaticError if it depends on bindings.

#### bind

```python
bind(mapping: Any = None, /, **kw: Any) -> PathExpr[C, K]
```

Substitute some parameters, folding whatever becomes static.

Values may be concrete (str, PathLike, ints for fields...) or symbolic: another PathExpr (rebasing), a Text, or a Param (renaming). Bindings come from a mapping, an object's fields (see `wend.bindings`) and keywords. Defaults are not applied: a parameter left unbound stays free, with its default (§3.1).

#### rebase

```python
rebase(*args: Any) -> PathExpr[Under[str], K]
```

```python
rebase(*args: Any) -> PathExpr[C, K]
```

Move this path to a new base (§9).

`rebase(new)` replaces the `base` this path was joined onto. `rebase(old, new)` replaces `old` wherever this path was built from it (a base, a path it is a sibling or cousin of, any expression in its derivation), re-applying the operations that built it; if this path was not built from `old`, `old` must be a structural prefix.

#### render

```python
render(mapping: Any = None, /, **kw: Any) -> str
```

Resolve to a canonical path string (equal to `str(self.resolve(...))`).

Bindings come from a mapping (keyed by name or `Param`), an object's fields (see `wend.bindings`) and keywords, which take precedence. A parameter given no binding takes its default, if it declares one (§3.1); otherwise it is a `MissingBindingError`.

#### resolve

```python
resolve(mapping: Any = None, /, *, cls: type = Path, **kw: Any) -> Resolved[C, K]
```

Resolve to a concrete path (`pathlib.Path` unless `cls` is given).

A parameter named `cls` is bound in `mapping`; a `cls=` keyword is then the result type. Without it in `mapping`, a `cls=` keyword on such an expression is ambiguous and raises `TypeError`.

#### match

```python
match(path: Any) -> Any
```

Bindings that resolve to `path`, None if none, AmbiguousMatchError if several.

#### match\_all

```python
match_all(path: Any, *, limit: int = 1000, fast: bool = True) -> list[dict[str, Any]]
```

All distinct verified bindings that render to `path` (up to `limit`).

#### glob

```python
glob(mapping: Any = None, /, **kw: Any) -> Any
```

Discover existing paths matching this expression (see `wend.glob` for the options, including `ambiguous=`).

#### compile

```python
compile() -> Any
```

Compile to a specialised Python function, cached on the expression.

### wend.Text

```python
Text(pieces: tuple[Piece, ...])
```

Bases: `_Cached`

A symbolic string: literal text and formatted fields.

Produced by `PathExpr.name`, `.stem` and `.suffix`; usable in `with_name`, `with_stem`, as a path operand, and inside t-strings.

#### pieces

```python
pieces: tuple[Piece, ...]
```

#### literal

```python
literal: str | None
```

#### param\_names

```python
param_names: frozenset[str]
```

#### pattern

```python
pattern: str
```

#### \_\_add\_\_

```python
__add__(other: Any) -> Text
```

#### \_\_radd\_\_

```python
__radd__(other: Any) -> Text
```

#### render

```python
render(mapping: Any = None, /, **kw: Any) -> str
```

#### bind

```python
bind(mapping: Any = None, /, **kw: Any) -> Text
```

### wend.bindings

```python
bindings(source: Any = None, /, **overrides: Any) -> dict[str, Any]
```

The bindings `source` gives, as a dict keyed by parameter name, with `overrides` taking precedence.

`source` is what every rendering and binding method takes: a mapping (keyed by name or by `Param`), or an object whose fields bind by name (a dataclass, attrs or Pydantic instance, a named tuple, or any object's instance attributes; see `object_bindings`)::

```text
@dataclass
class Run:
    root: Path
    split: str

shard.render(Run("/mnt", "train"), idx=7)  # the same as
shard.render(bindings(Run("/mnt", "train"), idx=7))
```

The result is a snapshot. It includes fields no expression uses; those are ignored where it is used.

## Relations between families

### wend.relate

```python
relate(
    a: Any, b: Any, *, shared: bool = True, builtin_values: bool = False
) -> Relation
```

How the paths `a` and `b` render relate, before any binding.

The paths are compared as strings (lexically), not as filesystem objects: `"never"` means never the same string, and a symlink or a `..` can still make two strings name one file.

`a` and `b` are expressions, unions or path strings. With `shared=True` (the default) a parameter name common to both takes one value, as the paths of one run of a pipeline do; `shared=False` relates every binding of `a` to every binding of `b`. `builtin_values=True` assumes bound values are of builtin types, which proves more paths apart (docs/SEMANTICS.md §15).

> > > from wend import P, Param, T root, day = Param("root"), Param("day") raw = P(root) / "raw" / T(t"{day}.csv") relate(raw, P(root) / "clean" / T(t"{day}.csv")).kind 'disjoint' relate(raw, P(root) / "raw").inside 'always'

### wend.Relation

```python
Relation(
    same: Certainty,
    inside: Certainty,
    contains: Certainty,
    shared: bool = True,
    examples: tuple[Example, ...] = (),
    assumptions: frozenset[str] = frozenset(),
)
```

How two path families relate (docs/SEMANTICS.md §15).

`same`, `inside` and `contains` are each `"always"` (for every binding under which both render), `"sometimes"` (for one at least: see `examples`), `"never"`, or `"unknown"` (neither was proved). `inside` is `a` strictly below `b`; `contains`, strictly above. Each compares the rendered strings, not the files they may name.

#### same

```python
same: Certainty
```

#### inside

```python
inside: Certainty
```

#### contains

```python
contains: Certainty
```

#### shared

```python
shared: bool = True
```

#### examples

```python
examples: tuple[Example, ...] = ()
```

#### assumptions

```python
assumptions: frozenset[str] = frozenset()
```

#### \_\_getitem\_\_

```python
__getitem__(how: How) -> Certainty
```

#### kind

```python
kind: Summary
```

The relation in one word: `"same"`, `"inside"` or `"contains"` when that holds always; `"disjoint"` when the paths never meet nor nest; `"overlapping"` when some binding shows one of the three; else `"unknown"`.

#### disjoint

```python
disjoint: bool
```

Whether the two rendered paths never meet nor nest, as strings: no path is both, nor one inside the other. Two spellings of one file (a symlink, `..`, a relative and an absolute path) are not seen.

## Parameters

### wend.Param

```python
Param(
    name: str,
    kind: Kind = AUTO,
    type: Any = None,
    choices: frozenset[Any] | None = None,
    *,
    default: Any = NO_DEFAULT,
)
```

A named slot filled at resolution time.

`type` constrains the bound value (`isinstance` check) and tells `match` how to parse text back into a value. `choices` restricts the accepted values. `default` is the value rendering uses when no binding is given for the name (docs/SEMANTICS.md §3.1); `bind` and `match` leave it alone.

#### name

```python
name: str
```

#### kind

```python
kind: Kind = Kind.AUTO
```

#### type

```python
type: Any = None
```

#### choices

```python
choices: frozenset[Any] | None = None
```

#### default

```python
default: Any = field(default=NO_DEFAULT, kw_only=True)
```

#### has\_default

```python
has_default: bool
```

Whether the parameter declares a default.

#### \_\_truediv\_\_

```python
__truediv__(other: Any) -> PathExpr
```

#### \_\_rtruediv\_\_

```python
__rtruediv__(other: Any) -> PathExpr
```

#### check

```python
check(value: Any) -> None
```

Raise InvalidBindingError if `value` violates the declared type or choices.

### wend.Segment

```python
Segment(
    name: str, *, type: Any = None, choices: Any = None, default: Any = NO_DEFAULT
) -> Param
```

A parameter binding exactly one path segment.

### wend.SubPath

```python
SubPath(name: str, *, choices: Any = None, default: Any = NO_DEFAULT) -> Param
```

A parameter binding a relative path of zero or more segments.

### wend.AnyPath

```python
AnyPath(name: str, *, choices: Any = None, default: Any = NO_DEFAULT) -> Param
```

A parameter binding any path, with pathlib join semantics wherever it is used.

### wend.Absolute

```python
Absolute(name: str, *, choices: Any = None, default: Any = NO_DEFAULT) -> Param
```

A parameter binding an absolute path.

### wend.Kind

Bases: `Enum`

What a parameter may bind to when used as a path operand.

AUTO PATH at the head of an expression, SEGMENT anywhere else. PATH Any path, absolute or relative (pathlib join semantics). ABSOLUTE An absolute path; joining one replaces everything before it. SEGMENT Exactly one segment: no separator, not "", "." or "..". SUBPATH A relative path of zero or more segments, without "..".

Inside a t-string field with a conversion or format spec, a parameter is a formatted value rather than a path operand, and its kind does not apply.

#### AUTO

```python
AUTO = 'auto'
```

#### PATH

```python
PATH = 'path'
```

#### ABSOLUTE

```python
ABSOLUTE = 'absolute'
```

#### SEGMENT

```python
SEGMENT = 'segment'
```

#### SUBPATH

```python
SUBPATH = 'subpath'
```

## Unions

### wend.U

```python
U(*items: Any) -> PathUnion
```

A union: `U(a, b, c)` is `a | b | c`; `U(t"...{Alt(x, y)}...")` expands a t-string's alternatives.

### wend.Alt

```python
Alt(*options: Any)
```

Alternatives for one interpolation of a t-string given to `U`.

Each option is text (a str), a t-string (which may hold parameters and nested alternatives) or a `Param`. It is spliced into the template as if written there, so an option may hold separators. `Alt("", x)` makes `x` optional.

#### options

```python
options = options
```

### wend.PathUnion

```python
PathUnion(alternatives: tuple[PathExpr, ...])
```

An ordered union of path expressions (docs/SEMANTICS.md §11).

#### alternatives

```python
alternatives: tuple[PathExpr, ...]
```

#### \_\_or\_\_

```python
__or__(other: Any) -> PathUnion
```

#### \_\_ror\_\_

```python
__ror__(other: Any) -> PathUnion
```

#### \_\_truediv\_\_

```python
__truediv__(other: Any) -> PathUnion
```

#### \_\_rtruediv\_\_

```python
__rtruediv__(other: Any) -> PathUnion
```

#### joinpath

```python
joinpath(*others: Any) -> PathUnion
```

#### child

```python
child(*parts: Any) -> PathUnion
```

#### under

```python
under(base: Any) -> PathUnion
```

#### parent

```python
parent: PathUnion
```

#### with\_name

```python
with_name(name: Any) -> PathUnion
```

#### with\_suffix

```python
with_suffix(suffix: str) -> PathUnion
```

#### with\_stem

```python
with_stem(stem: Any) -> PathUnion
```

#### relative\_to

```python
relative_to(other: Any) -> PathUnion
```

#### bind

```python
bind(mapping: Any = None, /, **kw: Any) -> PathUnion
```

#### requires

```python
requires(*conditions: Any) -> PathUnion
```

#### ensures

```python
ensures(*conditions: Any) -> PathUnion
```

#### declares

```python
declares: Declarations
```

What every alternative declares: a path the union describes comes from one of them, so only their common declarations hold of it.

#### param\_names

```python
param_names: frozenset[str]
```

#### pattern

```python
pattern: str
```

#### render

```python
render(mapping: Any = None, /, **kw: Any) -> str
```

The rendering of the only alternative. A union of several has no single rendering: use `renderings`, or `first` to pick by existence.

#### resolve

```python
resolve(mapping: Any = None, /, *, cls: type = Path, **kw: Any) -> Any
```

#### renderings

```python
renderings(mapping: Any = None, /, **kw: Any) -> tuple[str, ...]
```

Every alternative rendered with the same bindings, in order.

#### first

```python
first(mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> Path
```

The first alternative that exists and meets its own preconditions, checked now against the filesystem (an effect, unlike `render`), on `fs` (a `wend.fs` filesystem; the local disk by default).

Every alternative must render: a missing or invalid binding is an error, not a reason to skip it. Raises `NoAlternativeError` (a `FileNotFoundError`) listing what was tried when none qualifies. An alternative whose conditions cannot be determined raises `IndeterminateError` rather than being skipped: a later alternative is not chosen over one that could not be checked.

#### match\_all

```python
match_all(path: Any, *, limit: int = 1000) -> list[AltMatch]
```

Every verified reading of `path`, by each alternative in order.

#### match

```python
match(path: Any) -> AltMatch | None
```

The one reading of `path`: None if no alternative reads it, and `AmbiguousMatchError` if two readings exist, by one alternative or by two.

#### glob

```python
glob(
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
) -> Iterator[AltMatch]
```

Discover existing paths that any alternative matches, in path order.

The options, and the rule for a parameter named like one, are those of `wend.glob`. A path is ambiguous when two alternatives find it, or when one finds it under two readings. `ambiguous` decides what happens to it, as for `wend.glob`: it is never yielded, and its error, reported in path order before the first match, lists every reading as an `AltMatch`.

#### \_\_sub\_\_

```python
__sub__(other: Any) -> Query
```

#### \_\_and\_\_

```python
__and__(other: Any) -> Query
```

#### where

```python
where(*predicates: Any) -> Query
```

## Matching and discovery

### wend.Match

```python
Match(path: str, bindings: dict[str, Any])
```

Bases: `Mapping[str, Any]`

A matched path and its bindings (a read-only mapping of name to value).

#### path

```python
path = path
```

#### bindings

```python
bindings = bindings
```

#### \_\_getitem\_\_

```python
__getitem__(key: str) -> Any
```

### wend.Lens

```python
Lens(source: Any, target: Any)
```

Map paths matching `source` to the corresponding `target` paths.

> > > src = P("src") / SubPath("rel") / T(t"{stem}.py") lens = Lens(src, P("build") / SubPath("rel") / T(t"{stem}.pyc")) lens("src/pkg/mod.py") PosixPath('build/pkg/mod.pyc')

Target parameters that the source does not provide are bound per call, by keyword or after the path, in a mapping or an object whose fields bind by name (see `wend.bindings`): `lens(path, run="r1")`, `lens(path, {"run": "r1"})` or `lens(path, job)`. The path is positional-only, so a parameter may have any name.

#### source

```python
source: PathExpr = P(source)
```

#### target

```python
target: PathExpr = P(target)
```

#### lossless

```python
lossless: bool
```

True if both sides have the same parameters, so neither direction needs extra bindings.

Mapping forward through a lossless lens also checks that the result maps back uniquely: where two source paths would share a target (`{a}/{b}` to `{a}-{b}`), it raises `AmbiguousMatchError`.

#### bind

```python
bind(mapping: Any = None, /, **kw: Any) -> Lens
```

#### inverse

```python
inverse() -> Lens
```

#### bindings

```python
bindings(path: Any) -> dict[str, Any]
```

#### render

```python
render(path: Any, mapping: Any = None, /, **extra: Any) -> str
```

#### \_\_call\_\_

```python
__call__(path: Any, mapping: Any = None, /, **extra: Any) -> Path
```

#### forward

```python
forward = __call__
```

#### backward

```python
backward(path: Any, mapping: Any = None, /, **extra: Any) -> Path
```

#### map

```python
map(
    paths: Iterable[Any],
    mapping: Any = None,
    /,
    *,
    ambiguous: Literal["raise", "skip"]
    | Callable[[AmbiguousMatchError], object] = "raise",
    **extra: Any,
) -> Iterator[tuple[Any, Path]]
```

Pairs `(path, mapped)`, in order, for each path that matches the source; other paths are skipped.

`mapping` and keyword arguments bind target parameters, as for `render`. A target parameter named `ambiguous` is bound through `mapping`; as a keyword it raises `TypeError` (see `wend.glob`).

`ambiguous` decides what happens to a path that cannot be mapped uniquely: one that matches the source more than one way, or, through a lossless lens, one whose target reads back more than one way (another source path would map to the same target). `"raise"` (default) raises `AmbiguousMatchError` when that path is reached; `"skip"` leaves it out; a callable is called with the `AmbiguousMatchError` and the path is left out, so `ambiguous=report.append` collects them. The error names the path that reads more than one way (the source path, or the target path for a collision) and every verified reading of it. As with `wend.glob`, a callback keeps `map` an iterator of pairs.

### wend.NoMatchError

Bases: `WendError`, `ValueError`

The path does not match the lens's source expression.

### wend.glob

```python
glob(
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
) -> Iterator[Match]
```

Yield a `Match` for every existing path that `expr` can render.

Bindings in `mapping` and keyword bindings fix parameters before the walk (the head of the expression must be bound or literal). `kind` restricts results to `"file"` or `"dir"`. Matches are yielded in path order. Argument errors are raised by the call; the walk runs as the result is iterated.

**Options and bindings.** Options are keyword-only. A parameter that shares an option's name (`kind`, say) is bound through `mapping`: `glob(e, {"kind": "raw"}, kind="file")` binds the parameter and sets the option. A `kind=` keyword without `"kind"` in `mapping` could mean either, so it raises `TypeError`. To set the option and leave such a parameter free, rename the parameter first: `e.bind(kind=Param("k"))`.

**Ambiguity.** A path that the expression renders under more than one binding has no single `Match`. `ambiguous` decides what happens to it:

- `"raise"` (default): raise `AmbiguousMatchError` for the first such path, before any match is yielded;
- `"skip"`: leave it out and yield the other matches;
- a callable: call it with an `AmbiguousMatchError` for each such path, then yield the other matches. `ambiguous=report.append` collects them; a callable that raises aborts the walk, as `"raise"` does.

An ambiguous path is never yielded. Its error carries the path and all its readings, each a verified binding of `expr` (given bindings included) that renders to the path. A path reached through a followed symlink is also checked with `match_all`, so a reading that the link policy kept the walk from still counts. Errors are reported in path order, before the first match is yielded.

A callback rather than a returned report object keeps `glob` an iterator of matches, makes `"raise"` the special case of a callback that raises (as with `os.walk`'s `onerror`), and means a report is never read before the walk has filled it.

**Symlinks.** The walk starts at the expression's fixed prefix (its head and the literal segments that follow it), which is resolved like any path. Below that, symlinks are not followed by default: a symlinked directory is not descended into at any position, and `kind` judges a link as itself (neither a file nor a directory), so a link can only be yielded as the final component with `kind=None`. `follow_symlinks=True` descends symlinked directories at segment positions and classifies links by their targets, as pathlib's glob does. `recurse_symlinks=True` descends them while recursing through a `SubPath`, skipping any directory already on the current path so that link cycles terminate.

A `SubPath` can be empty, so where only `SubPath` parameters follow a position, a path can end there on a file (or a link, under the rules above) as well as on a directory: `P("srv") / SubPath("rest")` yields the files below `srv` as well as its directories, as pathlib's `srv.glob("**")` with files does.

This is a traversal policy, not a sandbox. The fixed prefix is resolved normally, a yielded link points wherever it points, and the tree can change between the walk and any use of its results. Where that matters, open results with `O_NOFOLLOW` or resolve and check them.

**Filesystems.** `fs` is the `wend.fs.FileSystem` to walk: the local disk by default, or a `wend.fs.FsspecFS` for an fsspec filesystem such as an object store, where results are the same as for an identical local tree. Paths are in that filesystem's namespace: bind the root that `wend.fs.url_to_fs` gives (`bucket/data` for `s3://bucket/data`). A URL bound as a path is refused. Stores have no symlinks, so the symlink options change nothing there.

## Batch resolution

### wend.compile\_many

```python
compile_many(exprs: Mapping[str, PathExpr] | Iterable[PathExpr]) -> CompiledSet
```

Compile a set of expressions into one function that renders them all.

Work the expressions share is done once per call: each parameter is looked up, validated and formatted once however many expressions use it, a head or a SubPath is canonicalised or split once, and an identical segment is built once. Results and errors equal rendering each expression in turn.

### wend.CompiledSet

```python
CompiledSet(
    exprs: tuple[PathExpr, ...], names: tuple[str, ...] | None, fn: Any, source: str
)
```

Several expressions compiled into one function (see `compile_many`).

`render` returns each expression's rendering, in order (a dict when the expressions were given by name); it equals rendering them one by one, and raises what the first failing expression raises.

#### exprs

```python
exprs = exprs
```

#### names

```python
names = names
```

#### source

```python
source = source
```

#### render

```python
render(mapping: Any = None, /, **kw: Any) -> Any
```

#### many

```python
many(rows: Iterable[Any]) -> list[tuple[str, ...]]
```

Render every expression for each mapping (or object) in `rows`, as tuples.

## Kinds and evidence

The type parameters that track what an expression declares (see `PathExpr`), and the evidence that `checked` and `confirmed` return: a record of what one check found of one rendered path, at the moment it ran, which is not a path and carries nothing to paths derived from it.

### wend.IsFile

Bases: `Unspecified`

`File` declared, in `requires` or `ensures`: nothing can be joined below the path (the runtime raises).

### wend.NotFile

Bases: `Unspecified`

`File` known not to be declared: disjoint from `IsFile`.

### wend.Unspecified

`File` not declared, or not known to be.

### wend.JoinBelowFile

What joining below a declared File gives, for a type checker: not a path (the runtime raises `PathOperationError`).

### wend.Checked

```python
Checked(
    path: Path,
    atoms: frozenset[str] = frozenset(),
    epoch: int | None = None,
    bases: tuple[Path, ...] = (),
)
```

Bases: `_Evidence`, `Generic[C, K]`

Evidence that a path's preconditions held when it was checked (a step's entry): `C` is what was required, and so what was checked.

### wend.Confirmed

```python
Confirmed(
    path: Path,
    atoms: frozenset[str] = frozenset(),
    epoch: int | None = None,
    bases: tuple[Path, ...] = (),
)
```

Bases: `_Evidence`, `Generic[Q, K]`

Evidence that a path's postconditions held when it was confirmed (a step's exit): `Q` is what was ensured. Not a `Checked`.

## Also exported from `wend`

`Query` (from [wend.query](<https://lmmx.github.io/wend/pr-preview/pr-124/reference/api/query/index.md>)), `counter` (from [wend.templates](<https://lmmx.github.io/wend/pr-preview/pr-124/reference/api/templates/index.md>)), the conditions of [wend.conditions](<https://lmmx.github.io/wend/pr-preview/pr-124/reference/api/conditions/index.md>) and the exceptions of [wend.errors](<https://lmmx.github.io/wend/pr-preview/pr-124/reference/api/errors/index.md>).
