# wend.query

Queries: discovery plans that filter what a pattern finds (SEMANTICS.md §11).

A query starts from an expression or a union and adds filters::

```text
src = P("src") / SubPath("rel") / T(t"{stem}.py")
tests = P("src") / SubPath("rel") / T(t"{stem}_test.py")
recent = (src - tests).where(File, modified_after(yesterday))
for m in recent.glob():
    ...
```

- `q - pattern` drops paths that `pattern` matches;
- `q & pattern` keeps paths that `pattern` also matches, adding its bindings (a parameter both patterns bind must agree);
- `q.where(*predicates)` keeps paths for which every predicate holds. A predicate is a condition (`File`, `Readable`, `Under(base)`...), a filesystem test such as `modified_after`, or any callable taking the `Match`.

Nothing runs until `glob` (or `match`) is called, and results stream as they are found. Filters are a conjunction: wend runs the pattern filters first, then pure callables, then the predicates that touch the filesystem, which is the cheapest order and gives the same results.

## FsPredicate

```python
FsPredicate(description: str, test: Callable[[stat_result], bool])
```

A test on the filesystem entry at a matched path (an effect).

### description

```python
description = description
```

### test

```python
test = test
```

### \_\_call\_\_

```python
__call__(m: Match) -> bool
```

## Query

```python
Query(
    source: Any,
    drop: tuple[Any, ...] = (),
    keep: tuple[Any, ...] = (),
    where: tuple[Any, ...] = (),
)
```

A lazy discovery plan: a source pattern and filters (see the module).

### source

```python
source = _pattern(source)
```

### drop

```python
drop = drop
```

### keep

```python
keep = keep
```

### predicates

```python
predicates = where
```

### \_\_sub\_\_

```python
__sub__(other: Any) -> Query
```

### \_\_and\_\_

```python
__and__(other: Any) -> Query
```

### where

```python
where(*predicates: Any) -> Query
```

### glob

```python
glob(
    mapping: Any = None,
    /,
    *,
    ambiguous: Literal["raise", "skip"]
    | Callable[[AmbiguousMatchError], object] = "raise",
    **kw: Any,
) -> Iterator[Match]
```

Discover the source's paths and yield those every filter admits, as they are found (see `wend.glob` for the options). Conditions are checked on the filesystem the walk reads (`fs=`); a condition that cannot be determined raises `IndeterminateError`.

`ambiguous` decides, as for `wend.glob`, what happens to a path with more than one reading: one the source reads two ways, which the source's `glob` reports before its first match, or one a `&` pattern reads two ways, reported when the stream reaches it (as `wend.Lens.map` reports). Neither is yielded.

### match

```python
match(path: Any, *, fs: Any = None) -> Match | None
```

The source's reading of `path`, if every filter admits it. The filesystem predicates look at `path` now, on `fs`.

## larger\_than

```python
larger_than(size: int) -> FsPredicate
```

The path's size in bytes is more than `size`.

## modified\_after

```python
modified_after(when: datetime | float) -> FsPredicate
```

The path was modified after `when` (a datetime or a POSIX timestamp).

## modified\_before

```python
modified_before(when: datetime | float) -> FsPredicate
```

The path was modified before `when`.

## smaller\_than

```python
smaller_than(size: int) -> FsPredicate
```

The path's size in bytes is less than `size`.
