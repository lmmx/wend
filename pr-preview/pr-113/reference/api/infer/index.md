# wend.infer

Filesystem layout inference: from observed paths to wend expressions.

The analogue of JSON schema inference (genson, polars-genson) for directory trees. Observed paths form a tree, which is generalised bottom-up:

- Names are tokenised into ASCII digit runs and the text between them, giving a *skeleton* (`chunk_#-of-#.parquet`). A name holding exactly one UUID, or one hex token of eight or more digits mixing letters and digits, keeps that token as one string token, and the text after it stays literal (`part-#-<uuid>-c000.snappy.parquet`). Siblings with the same skeleton merge; each digit run that varies becomes an `int` field whose format spec (`04d`, `d`) is chosen so that every observed value round-trips, and runs that never vary stay literal. Names whose runs need different specs are split, so a stray `epoch_7` among `epoch_001`... is reported on its own.
- Sibling directories whose contents are structurally similar (Jaccard similarity of their children's skeletons) collapse into one segment field, like genson's record-to-map unification. Files that share an extension collapse into `{stem}.ext` once there are `min_files` of them, and so do empty directories, which have no contents to compare. A map at a position absorbs the similar directories, same-extension files and empty directories beside it, whatever their number.
- Merging directories re-unifies their children. A field whose observed values always equal an earlier field's becomes the same parameter (`n01440764/n01440764_10026.JPEG`).

Opaque families. Directories that hold only files, but whose names share no skeleton (terminfo's `a/att4410`, `b/bvt100`...), are compared by the extensions of their files instead. Like genson-core's map threshold, this coarser comparison needs many siblings: only a group of at least `min_opaque` (8) such directories, joining clusters that did not merge by skeleton, collapses into a map, so a code repository's handful of top-level directories stays a record. An empty directory says nothing about extensions: it neither counts towards `min_opaque` nor keeps a family (`0`...`9` with an empty `9`) from being opaque. Inside such an *opaque* map, a name family seen in only one of its directories is treated like a one-off name, and a `{name}` map takes in the files left over: their names carry no shared structure.

Variable depth. After flattening, a tail `T` (one segment, possibly after literal directory segments such as `__pycache__`, with some literal text) that recurs below a prefix `A` becomes the layout `A/{rel...}/T`. Writing *holders* for the directories that hold an instance of `T` directly, the recursion criterion is:

1. `T` occurs directly in `A` (depth 0);
2. `T` occurs at `min_depths` (3) distinct depths below `A` counting depth 0, each depth other than 0 with at least two observed paths;
3. it branches: at some depth below `A` there are two or more holders, so `T` recurs in sibling directories rather than along one chain;
4. the root looks like what it recurses into: the extensions of the files directly in the depth-0 holders and in the deeper holders are alike (weighted Jaccard of their frequencies at least `similarity`).

The layouts it replaces are those extending `A` whose every path ends in an instance of `T`. Candidates are taken largest first, so the outermost recursion root wins, and a fold below a field segment (`site-packages/{pkg}`) takes in the folds of literal directories beside it that its field matches. A chain of literal directories fails the third condition (`a/{stem}.txt`, `a/b/{stem}.txt`, `a/b/c/{stem}.txt`); a repository root whose few scripts sit among records (`README.md`, `pyproject.toml`) fails the fourth, so its packages fold below it, if at all; and a tail without literal text (`{name}`) is never a candidate.

Kinds. The observed paths are files and observed directories: the empty directories of a walk, or the entries ending in "/" of an iterable. Each layout has one kind and is inferred from paths of that kind only; a directory merged with others keeps its own observed path apart from the files below it, as a `dir` layout of the merged pattern (`{dir}/examples` when some package directories hold an empty `examples/`). A dir layout generalises like a file layout, through merged parents, digit runs, maps and SubPath folds, but a file and a directory never share one, whatever names they share.

Every observed path matches at least one inferred layout of its kind, and each layout's `count` and field statistics come from the paths it was inferred from, so the counts partition the observed paths of each kind. `optional` and `cardinality` are properties of the pattern and the kind: a layout's paths are the observed paths of its kind that it matches; it is optional when some observed directory matching a proper prefix of it contains none of them, and *many* when some directory holds more than one of them directly (every such directory matches the pattern's parent prefix). Statistics record the values seen without constraining new ones.

Field names follow the text before a run (`epoch_{epoch:03d}`), dates (`{year:04d}-{month:02d}-{day:02d}`, `{date:08d}`, a bare four-digit `{year:04d}` directory, and times after a date) and token kinds (`{uuid}`, `{hex}`); a directory field is named after its parent.

## FieldStats

```python
FieldStats(
    name: str,
    type: type,
    count: int,
    distinct: int,
    min: Any = None,
    max: Any = None,
    sample: tuple[Any, ...] = (),
)
```

What was observed for one inferred field.

### name

```python
name: str
```

### type

```python
type: type
```

### count

```python
count: int
```

### distinct

```python
distinct: int
```

### min

```python
min: Any = None
```

### max

```python
max: Any = None
```

### sample

```python
sample: tuple[Any, ...] = ()
```

## Layout

```python
Layout(
    expr: PathExpr,
    kind: str,
    count: int,
    fields: dict[str, FieldStats],
    optional: bool,
    many: bool = False,
)
```

One inferred path pattern, relative to the inferred root.

`kind` is "file" or "dir", and `count` and `fields` describe the observed paths of that kind the layout was inferred from. `optional` is true when some observed directory matching a proper prefix of `expr` contains none of the observed paths of its kind that `expr` matches; `many` is true when some observed directory holds more than one of them directly. `cardinality` combines the two, as the `wend.schema.Cardinality` a schema entry declares.

### expr

```python
expr: PathExpr
```

### kind

```python
kind: str
```

### count

```python
count: int
```

### fields

```python
fields: dict[str, FieldStats]
```

### optional

```python
optional: bool
```

### many

```python
many: bool = False
```

### cardinality

```python
cardinality: Cardinality
```

### match

```python
match(path: Any) -> Match | None
```

### under

```python
under(root: Any) -> PathExpr
```

The layout as an expression rooted at `root`.

### rename

```python
rename(**names: str) -> Layout
```

Rename inferred fields, e.g. `layout.rename(data="split")`.

## Schema

```python
Schema(layouts: list[Layout], total: int)
```

The result of `infer`: layouts that together cover every observed path.

Each observed path is covered by a layout of its own kind: a file by a `file` layout, an observed directory by a `dir` layout. `total` counts the distinct observed paths, which the layouts' counts partition.

### layouts

```python
layouts: list[Layout]
```

### total

```python
total: int
```

### match

```python
match(path: Any, kind: str | None = None) -> list[tuple[Layout, Match]]
```

Every layout of `kind` that matches `path`, with its bindings.

`kind` is "file", "dir" or None. Without it, a string ending in "/" is a directory, as in `infer`, and any other path matches layouts of either kind.

### check

```python
check(paths: Iterable[Any]) -> list[str]
```

Paths that no layout of their kind matches (empty when all are covered).

Each entry is a path or a `(path, is_dir)` pair. A string ending in "/" is a directory, as in `infer`; any other path is checked against layouts of either kind.

## infer

```python
infer(
    source: Any,
    *,
    min_dirs: int = 2,
    min_files: int = 3,
    similarity: float = 0.5,
    include_hidden: bool = False,
    fs: FileSystem | None = None,
) -> Schema
```

Infer layouts from a directory (walked) or an iterable of relative paths.

The observed paths are the files and, in a walk, the empty directories. In an iterable, a trailing "/" marks a directory, which is an observed path of kind `dir` whether or not other paths lie below it; repeated paths count once. `min_dirs` and `min_files` are how many similar siblings it takes to generalise a name into a field (`min_files` also counts empty directories, which have no contents to compare); `similarity` is the Jaccard threshold on directory contents. Hidden entries are skipped unless `include_hidden`.

With `fs` (a `wend.fs.FileSystem`), `source` is a directory in that filesystem, such as the path `wend.fs.url_to_fs` gives for a bucket. An object store has empty directories only as explicit markers.
