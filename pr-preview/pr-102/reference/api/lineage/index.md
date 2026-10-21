# wend.lineage

Lineage: where a path came from, before and after it exists (SEMANTICS.md §13).

A path has two pasts.

- **As a plan**, an expression records how it was built (§9): `upstream` lists the expressions it derives from, `explain` writes the chain out, and `tags` collects the tags (`e.tag(source="upload")`) found along it.
- **As an artefact**, a file was produced from other files by some operation. A `Ledger` records that, with the inputs' content digests, so later you can ask what a file was made from (`provenance`, `upstream`), what was made from it (`downstream`) and whether it is out of date (`stale`). `Ledger.run` records a `Step` automatically.

Content addressing names a path after what it holds: `content_key(*paths)` digests files (an effect), `values_key(**values)` digests plain values (pure), and either is bound to an ordinary parameter, so `render` stays pure and `match` reads the key back::

```text
cache = P(root) / "cache" / T(t"{key}") / "features.parquet"
out = cache.render(root="/data", key=content_key(raw))
cache.match(out)["key"] == content_key(raw)   # still true while raw is unchanged
```

wend records relations; scheduling (what to rebuild, in which order) is left to the caller or a workflow tool.

## Ledger

```python
Ledger(path: Any, *, digests: bool = True)
```

An append-only record of which files were made from which, kept as JSON lines in `path`. Paths are stored absolute and normalised; the latest record for a path is its provenance.

### path

```python
path = Path(path)
```

### digests

```python
digests = digests
```

### record

```python
record(
    output: Any,
    inputs: Iterable[Any] = (),
    *,
    operation: str = "",
    bindings: Mapping[str, Any] | None = None,
    tags: Mapping[str, Any] | None = None,
) -> Record
```

Record that `output` was made from `inputs` (an effect: digests the files that exist, then appends to the ledger).

### run

```python
run(step: Step, mapping: Any = None, /, **bindings: Any) -> Iterator[dict[str, Path]]
```

Run `step` like `with step(...)` and, when it succeeds, record each path it declares it creates, writes or deletes as made from the paths it declares it reads (its `effects`). The bindings are given as to the step: a mapping or an object whose fields bind by name, and keywords. The operation is the step's repr; tags are each output expression's lineage tags.

### records

```python
records() -> list[Record]
```

### provenance

```python
provenance(path: Any) -> Record | None
```

The latest record for `path`, or None if it was never recorded.

### upstream

```python
upstream(path: Any) -> list[str]
```

Every path `path` was made from, directly or not, nearest first.

### downstream

```python
downstream(path: Any) -> list[str]
```

Every recorded path made from `path`, directly or not, nearest first: what to invalidate when `path` changes or is corrupt.

### stale

```python
stale(path: Any) -> list[str]
```

The inputs of `path`'s latest record whose content is not what it was when `path` was made (changed, or gone), checked now. Empty when `path` is up to date, or was never recorded.

## Record

```python
Record(
    path: str,
    inputs: tuple[tuple[str, str | None], ...] = (),
    operation: str = "",
    bindings: Mapping[str, Any] = dict(),
    tags: Mapping[str, Any] = dict(),
    digest: str | None = None,
    time: float = 0.0,
)
```

That `path` was produced from `inputs` by `operation`.

`inputs` pairs each input path with its digest when recorded (None if it was not digested); `digest` is the output's own.

### path

```python
path: str
```

### inputs

```python
inputs: tuple[tuple[str, str | None], ...] = ()
```

### operation

```python
operation: str = ''
```

### bindings

```python
bindings: Mapping[str, Any] = field(default_factory=dict)
```

### tags

```python
tags: Mapping[str, Any] = field(default_factory=dict)
```

### digest

```python
digest: str | None = None
```

### time

```python
time: float = 0.0
```

### to\_json

```python
to_json() -> str
```

### from\_json

```python
from_json(line: str) -> Record
```

## content\_key

```python
content_key(*paths: Any, length: int = 16, algorithm: str = 'sha256') -> str
```

A key naming the contents of `paths` (in order): the first `length` hex digits of a digest of their digests. An effect: reads the files.

## digest\_file

```python
digest_file(path: Any, algorithm: str = 'sha256') -> str
```

`"<algorithm>:<hex>"` of a file's bytes (an effect: reads the file).

## explain

```python
explain(e: PathExpr) -> str
```

How `e` was built, one operation per line, sources first.

## tags

```python
tags(e: PathExpr) -> dict[str, Any]
```

The tags on `e` and on every expression it was built from; a nearer expression's tag wins over a source's.

## upstream

```python
upstream(e: PathExpr) -> list[PathExpr]
```

The expressions `e` was built from, sources first, each once.

## values\_key

```python
values_key(length: int = 16, algorithm: str = 'sha256', **values: Any) -> str
```

A key naming a set of values (build parameters, say): a digest of their canonical JSON, with keys sorted. Pure.
