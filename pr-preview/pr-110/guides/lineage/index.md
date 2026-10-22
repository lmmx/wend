# Lineage and caching

A path has two histories. The expression records how the path was built from other paths, and the files record which ones were made from which. This guide reads the first with `explain` and `tags`, records the second with a `Ledger`, uses it to find what is out of date, and names cache entries after the contents of their inputs. It needs Python 3.14 and wend, with no extras. The examples build on each other: run them in order, in an empty directory.

## How an expression was built

A pipeline cleans a day's raw upload and writes a report from the clean copy. Each path is defined from the one before it:

```python
from wend import P, Param, T
from wend.lineage import explain, tags

root, day = Param("root"), Param("day")

raw = (P(root) / "raw" / T(t"{day}.csv")).tag(source="upload")
clean = raw.cousin("../clean", T(t"{day}.csv")).tag(stage="clean")
report = clean.cousin("../reports", T(t"{day}.md"))
```

Each expression records the operation that built it and its arguments: its derivation ([Relations](<https://lmmx.github.io/wend/pr-preview/pr-110/concepts/relations/#derivations>)). `explain` writes the derivation out, one operation per line, sources first:

```pycon
>>> print(explain(report))
{root}/raw = join({root}, 'raw')
{root}/raw/{day}.csv = join({root}/raw, {day}.csv)
{root}/clean/{day}.csv = cousin({root}/raw/{day}.csv, '../clean', {day}.csv)
{root}/reports/{day}.md = cousin({root}/clean/{day}.csv, '../reports', {day}.md)
```

`tag` attaches metadata to one expression, which keeps it in `PathExpr.tags`. `tags` collects the tags of an expression and of every expression it was built from. Where two set the same name, the nearer one wins.

```pycon
>>> dict(clean.tags), dict(report.tags)
({'stage': 'clean'}, {})
>>> tags(report)
{'source': 'upload', 'stage': 'clean'}
```

Like conditions, the derivation and the tags are not part of the path. `report` equals the same path built directly, and `bind` keeps the tags:

```pycon
>>> report == P(root) / "reports" / T(t"{day}.md")
True
>>> tags(report.bind(root="data"))
{'source': 'upload', 'stage': 'clean'}
```

## Record what each step made

Each step is a `Step` whose conditions say which paths it reads and which it creates ([Pipeline steps](<https://lmmx.github.io/wend/pr-preview/pr-110/guides/pipelines/index.md>)):

```python
from pathlib import Path

from wend import Absent, Creatable, Exists, File, Readable, Step
from wend.lineage import Ledger

clean_step = Step(
    raw=raw.requires(File, Exists, Readable),
    clean=clean.requires(Absent, Creatable).ensures(File, Exists),
)
report_step = Step(
    clean=clean.requires(File, Exists, Readable),
    report=report.requires(Absent, Creatable).ensures(File, Exists),
)

Path("data/raw").mkdir(parents=True)
Path("data/raw/mon.csv").write_text("id,value\n1,3\n2,4\n")
ledger = Ledger("data/lineage.jsonl")
```

A `Ledger` is an append-only file of JSON lines. `run` runs a step as `with step(...)` does. When the step succeeds, it records each path the step declares it creates, writes or deletes as made from the paths it declares it reads, with a digest of each file's contents:

```python
with ledger.run(clean_step, root="data", day="mon") as p:
    p["clean"].parent.mkdir(exist_ok=True)
    p["clean"].write_text(p["raw"].read_text().replace(",", "\t"))

with ledger.run(report_step, root="data", day="mon") as p:
    p["report"].parent.mkdir(exist_ok=True)
    rows = p["clean"].read_text().splitlines()[1:]
    p["report"].write_text(f"{len(rows)} rows\n")
```

```pycon
>>> len(ledger.records())
2
```

## Ask where a file came from

The ledger stores absolute paths. `rel` shortens them for display:

```python
import os


def rel(paths):
    return [os.path.relpath(p) for p in paths]
```

`provenance` gives a file's latest `Record`: its inputs, the step, the bindings it used, and the tags of the expression it was rendered from.

```pycon
>>> record = ledger.provenance("data/reports/mon.md")
>>> rel(path for path, digest in record.inputs)
['data/clean/mon.csv']
>>> record.operation
"Step(clean='{root}/clean/{day}.csv', report='{root}/reports/{day}.md')"
>>> record.bindings
{'root': 'data', 'day': 'mon'}
>>> record.tags
{'source': 'upload', 'stage': 'clean'}
```

`upstream` follows the records back to every file a file was made from, nearest first. `downstream` follows them forward to every file made from a file:

```pycon
>>> rel(ledger.upstream("data/reports/mon.md"))
['data/clean/mon.csv', 'data/raw/mon.csv']
>>> rel(ledger.downstream("data/raw/mon.csv"))
['data/clean/mon.csv', 'data/reports/mon.md']
```

## Find what is stale

The upload is corrected:

```python
Path("data/raw/mon.csv").write_text("id,value\n1,3\n2,5\n")
```

`stale` reads the inputs of a file's latest record now, and lists those whose contents no longer match the recorded digests, or that are gone:

```pycon
>>> rel(ledger.stale("data/clean/mon.csv"))
['data/raw/mon.csv']
>>> ledger.stale("data/reports/mon.md")
[]
```

The report is not stale by itself: its one input, the clean file, has not changed yet. `stale` looks at direct inputs only. `downstream` gives everything that depends on the changed file, which is what to build again:

```pycon
>>> rel(ledger.downstream("data/raw/mon.csv"))
['data/clean/mon.csv', 'data/reports/mon.md']
```

wend records the relations. The order to build in, and the building, are left to the caller or to a workflow tool.

## Name a cache entry after its input

A content-addressed path is named after what it was computed from. `content_key` reads files and returns a short digest of their contents. The key is bound to an ordinary parameter, so `render` stays pure:

```python
import json

from wend.lineage import content_key

key = Param("key")
summary = P(root) / "cache" / key / "summary.json"


def cached_summary(src):
    out = summary.resolve(root="data", key=content_key(src))
    if not out.exists():
        print("computing", out)
        rows = Path(src).read_text().splitlines()[1:]
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({"rows": len(rows)}))
    return out
```

The first call computes the summary. The second call, with the same input, finds it:

```pycon
>>> first = cached_summary("data/raw/mon.csv")
computing data/cache/28c614b91d6d0aec/summary.json
>>> cached_summary("data/raw/mon.csv") == first
True
```

`match` reads the key back out of a cached path. Whether the entry still names its input is a check made now, by computing the key again:

```pycon
>>> summary.match(first)["key"] == content_key("data/raw/mon.csv")
True
```

After another change to the upload, the key differs, and the next call computes a new entry:

```python
Path("data/raw/mon.csv").write_text("id,value\n1,3\n2,5\n3,8\n")
```

```pycon
>>> summary.match(first)["key"] == content_key("data/raw/mon.csv")
False
>>> cached_summary("data/raw/mon.csv")
computing data/cache/df0124d58739da13/summary.json
PosixPath('data/cache/df0124d58739da13/summary.json')
```

`values_key` gives a key for values, such as the settings a result depends on. It reads no files, and the order of the keywords does not change it:

```pycon
>>> from wend.lineage import values_key
>>> values_key(model="tiny", epochs=3)
'74341c5f7f50e110'
>>> values_key(epochs=3, model="tiny")
'74341c5f7f50e110'
```

## See also

- [Relations](<https://lmmx.github.io/wend/pr-preview/pr-110/concepts/relations/index.md>): derivations, and how `rebase` uses them.
- [Pipeline steps](<https://lmmx.github.io/wend/pr-preview/pr-110/guides/pipelines/index.md>): conditions and `Step`.
- [SEMANTICS.md §13](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#13-lineage>) (lineage).
- API reference: `wend.lineage`, `Ledger`, `explain`, `tags`, `content_key`, `values_key`.
