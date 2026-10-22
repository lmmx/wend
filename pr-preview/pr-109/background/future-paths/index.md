# Future Paths and wend

wend grew out of [Future Paths](<https://cog.spin.systems/future-paths>), five essays written in January 2026 on what Python paths could keep track of beyond a concrete value. This page maps each essay to the library as it is now. Using wend does not require reading them.

The essays share one distinction, stated in the first: describing a path is different from realising it as a concrete value. Most of what they propose, and most of what wend does, follows from keeping the description.

## Part 1: Semantic types

[The essay](<https://cog.spin.systems/future-paths-types>) asks for paths that carry what the programmer means by them: that a path must exist or must not, is a file or a directory, is a fragment to be placed under a root, or must stay inside a directory. It then sketches lenses, lineage, content addressing, directory schemas, schema inference, an algebra of path sets, late binding and virtual filesystems.

Its fragment and late-binding sketches work as written, with wend's names:

```pycon
>>> from wend import P, Param
>>> leaf = P("bar")
>>> [p.render() for p in map(leaf.under, ["foo1", "foo2"])]
['foo1/bar', 'foo2/bar']
>>> ROOT = Param("root")
>>> CONFIG = ROOT / "config.yaml"
>>> CONFIG.resolve(root="/actual/root")
PosixPath('/actual/root/config.yaml')
```

| the essay's sketch | in wend |
| --- | --- |
| `Path.fragment(...)`, `leaf.under(parent)` | an expression and `under` |
| `PathVar("root")`, `CONFIG.collect(paths)` | `Param`, `resolve`, and bindings from objects |
| `FilePath`, `DirectoryPath`, `NewPath` | the conditions `File`, `Dir`, `Exists` and `Absent` |
| `Path[Readable]`, `Path[Writable, MayCreate]` | `Readable`, `Writable`, `Creatable` and `Listable` |
| `Path[Under[STATIC_ROOT]]` | `Under`, and segment parameters, which cannot traverse |
| pre- and postconditions on pipeline steps | `requires`, `ensures` and `Step` |
| `PathLens(forward=..., backward=...)` | `Lens`, built from two expressions instead of two functions |
| `.tag(...)`, `provenance`, `trace_lineage()` | `tag`, `explain` and `Ledger` |
| content-addressed paths, as in Nix | `content_key` |
| `@directory_schema class MLProject` | `wend.schema.Tree`, with `validate` and `scaffold` |
| schema inference, after genson | `wend.infer.infer` and `from_inferred` |
| a union of `UserConfig`, `SystemConfig` and `DefaultConfig`, tried in order; `&`, `-` and `PathQ` | unions with `first`, and queries |
| `XDG.CACHE_HOME` | `wend.anchors` |
| fsspec and other filesystems | `wend.fs.FsspecFS`, for `glob` and `infer` |

**What changed on the way.**

- **The capabilities are runtime checks, not types.** `Path[Readable]` in a signature is something a type checker could verify. wend's conditions are declared on an expression and checked by `check` and `Step` when the program runs; a type checker sees a `PathExpr`. The [conditions journal entry](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-conditions-49.md>) records what static checking could add.
- **The lens is derived, not written.** The essay's lens takes a forward and a backward function. wend's takes two expressions, and derives both directions by matching one and rendering the other, so the two directions cannot disagree.
- **The schema is a class of entries,** with cardinality per directory and a report of every difference at once, rather than typed attribute access alone.

## Part 2: Connectivity

[The essay](<https://cog.spin.systems/future-paths-connectivity>) observes that after `config = project_root / "config.yaml"`, the fact that `config` was built from `project_root` is gone. It asks for a relation type, base tracking, rebasing, sibling and cousin relations, composition rules, and some integration with types.

All but the last are in wend ([Relations](<https://lmmx.github.io/wend/pr-preview/pr-109/concepts/relations/index.md>)):

```pycon
>>> Root = Param("Root")
>>> csv_in = Root / "data" / "input.csv"
>>> schema = csv_in.sibling("schema.json")
>>> schema.render(Root="/tmp/proj")
'/tmp/proj/data/schema.json'
>>> moved = schema.rebase(csv_in, P("/archive/input.csv"))
>>> moved.render()
'/archive/schema.json'
```

Composition preserves the chain: a path derived from a derived path keeps both steps, so rebasing any path in the chain moves everything derived from it. Type-level connectivity (`config: Path[Under[root]]`) needs dependent types, which Python does not have; `Under` is checked at runtime instead, lexically by `render` and with symlinks resolved by `check`.

## Part 3: Deferred path-ification

[The essay](<https://cog.spin.systems/future-paths-template-strings>) builds a proof of concept on Python 3.14's t-strings: parameters stay symbolic inside a template, joins build a tree, and `resolve` substitutes values, with `parent`, `with_suffix` and `with_name` working before any value is known. wend keeps all of it, and the essay's examples run as written:

```pycon
>>> from pathlib import Path
>>> from wend import T
>>> root, idx, total = Param("root"), Param("idx"), Param("total")
>>> chunk_file_t = root / "chunks" / T(t"chunk_{idx:03}-of-{total:03}.parquet")
>>> chunk_file_t.resolve({"root": Path("/data"), "idx": 1, "total": 10})
PosixPath('/data/chunks/chunk_001-of-010.parquet')
>>> chunk_file_t.parent.resolve({"root": Path("/data")})
PosixPath('/data/chunks')
>>> chunk_file_t.with_suffix(".json").resolve(
...     {"root": Path("/data"), "idx": 5, "total": 10}
... )
PosixPath('/data/chunks/chunk_005-of-010.json')
```

What changed is the structure underneath. The proof of concept was a tree of join nodes. wend keeps every expression in a normal form, a head followed by segments, so the number of segments is known before binding. That one change is what makes the rest sound:

- an operation is computed from the structure only when the structure decides it, and is deferred to pathlib otherwise ([Operations](<https://lmmx.github.io/wend/pr-preview/pr-109/concepts/operations/index.md>));
- a value bound to a segment parameter cannot add segments, so it cannot traverse ([Parameters](<https://lmmx.github.io/wend/pr-preview/pr-109/concepts/parameters/index.md>));
- an expression can be matched back against a path ([Rendering and matching](<https://lmmx.github.io/wend/pr-preview/pr-109/concepts/matching/index.md>)). None of the essays has matching; it came with the normal form.

## Part 4: Compilation theory

[The essay](<https://cog.spin.systems/future-paths-compilation-theory>) frames path expressions as term rewriting, with three rules: parent–join cancellation, constant folding and suffix-chain collapse. It then sketches a register machine for executing them, and concludes that Python, not a parser, should build the expression tree.

The conclusion holds: the expression tree is built by Python's own operators. The three rules hold too, with the condition the essay did not state. Parent–join cancellation is valid only when the right operand is exactly one segment, so wend applies it only then:

```pycon
>>> from wend import SubPath
>>> (Root / "a/b").parent
PathExpr('{Root}/a')
>>> (Root / SubPath("rel")).parent
PathExpr('parent({Root}/{rel...})')
```

wend 0.1 applied the rule by the type of a node rather than its number of segments, and gave `/x` for `(root / "a/b").parent` where pathlib gives `/x/a`. The [retrospective](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-17-retrospective-17.md>) records this. The current rules are not a rewrite system applied afterwards: they are what the normal form computes when an expression is built, and the [contract](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md>) states the result they must agree with, which the tests check against an eager pathlib oracle.

The register machine was not built. Its main benefit, computing a shared sub-path once, appears as `compile_many`, which looks up, checks and formats each parameter once for a whole set of expressions.

## Part 5: Lazy execution

[The essay](<https://cog.spin.systems/future-paths-lazy-execution>) describes a Rust implementation behind pyo3: an arena of nodes, an optimiser, and a slot-based executor, with `compile_path(expr).resolve(...)` from Python.

**wend has no Rust backend.** Its goal, compiling once and resolving many times without walking the tree, is met in Python:

- `compile` generates a specialised Python function per expression, with validation and formatting inlined;
- `compile().many` and `compile().columns` render in bulk;
- `wend.frame.resolve_frame` renders whole Polars columns.

The essay's API also differs: its `T("chunk_{idx}.parquet", ["idx"])` took formatting out of the template and had the caller format each value, which wend's t-string templates keep in place. Whether a native backend is worth building is open, to be decided on measurements: [issue \#37](<https://github.com/lmmx/wend/issues/37>) tracks it, and the [journal](<https://github.com/lmmx/wend/tree/master/docs/journal>) records what a backend would need to beat.

## What is still open

- **Static checking.** Capabilities, containment and connectivity as types that a type checker verifies, rather than conditions checked at runtime.
- **A native backend,** only where measurements justify one (\#37).
- **Effects as data.** Parts 2 and 5 suggest reporting every filesystem effect a program can have. `Step.effects()` lists what each path of a step declares, but nothing collects them across a program.

[Project history](<https://lmmx.github.io/wend/pr-preview/pr-109/background/history/index.md>) lists the journal entries that record how each part was built, including the [trajectory entry](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-17-trajectory-40.md>), which tells the same story in more detail.
