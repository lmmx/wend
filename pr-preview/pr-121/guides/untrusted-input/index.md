# Untrusted input

A web service stores the files that users upload, an import job unpacks the archives they send, and a configuration file names extra files to read. Each of these puts text from outside the program into a path. This guide declares where each value may go, so that a value that would lead elsewhere is rejected. It needs Python 3.14 and wend, with no extras. The examples build on each other: run them in order, in an empty directory.

## Bind, never join

pathlib joins a value as it is written, `..` included:

```pycon
>>> from pathlib import Path
>>> name = "../../../etc/passwd"
>>> Path("srv/uploads") / "ada" / name
PosixPath('srv/uploads/ada/../../../etc/passwd')
```

In wend, a value goes into a path by being bound to a parameter:

```python
from wend import P, Param

root, user, filename = Param("root"), Param("user"), Param("filename")
upload = P(root) / "uploads" / user / filename
```

```pycon
>>> upload.render(root="srv", user="ada", filename="cv.pdf")
'srv/uploads/ada/cv.pdf'
>>> upload.render(root="srv", user="ada", filename=name)
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: filename='../../../etc/passwd' is not a single path segment; declare 'filename' with SubPath('filename') to bind multi-segment paths
```

A `str` joined with `/` is different: it becomes part of the expression's literal text, with pathlib's rules, as the program's own text does:

```pycon
>>> P("srv/uploads") / "ada" / name
PathExpr('srv/uploads/ada/../../../etc/passwd')
```

Literal text is trusted. Bind every value from outside the program to a parameter, and never join it.

## One directory entry: segments

`user` and `filename` come after the head of the expression, so each is a segment parameter: its value must be exactly one path segment. A value that contains a `/`, or is `""`, `.` or `..`, would change the structure of the path, and is rejected:

```pycon
>>> from wend import InvalidBindingError
>>> for name in ["cv.pdf", "a/b.pdf", "/etc/passwd", "..", "", "x\x00y"]:
...     try:
...         print("ok:", upload.render(root="srv", user="ada", filename=name))
...     except InvalidBindingError as e:
...         print("rejected:", e)
ok: srv/uploads/ada/cv.pdf
rejected: filename='a/b.pdf' is not a single path segment; declare 'filename' with SubPath('filename') to bind multi-segment paths
rejected: filename='/etc/passwd' is not a single path segment; declare 'filename' with SubPath('filename') to bind multi-segment paths
rejected: filename='..' is not a valid path segment
rejected: filename='' is not a valid path segment
rejected: filename='x\x00y': contains NUL
```

So a value bound to a segment parameter always names one entry of the directory before it. `InvalidBindingError` is a `ValueError`.

A parameter inside a formatted field, such as `{stem}` in `t"{stem}.png"`, contributes text to one segment, and that text cannot contain a `/` either:

```pycon
>>> from wend import T
>>> stem = Param("stem")
>>> avatar = P(root) / "avatars" / user / T(t"{stem}.png")
>>> avatar.render(root="srv", user="ada", stem="../../x")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: {stem} formats '../../x' to '../../x', which contains a separator
```

## Nested names: SubPath

The names in an archive have directories, so they need more than one segment. A `SubPath` parameter accepts a relative path of zero or more segments, without `..`. Create an archive with two ordinary members and two that point outside the target directory:

```python
import zipfile

with zipfile.ZipFile("upload.zip", "w") as zf:
    zf.writestr("docs/readme.txt", "hello\n")
    zf.writestr("docs/img/logo.svg", "<svg/>\n")
    zf.writestr("../../.bashrc", "echo hi\n")
    zf.writestr("/etc/cron.d/job", "* * * * * root true\n")
```

Extract it through an expression, skipping each member whose name is rejected:

```python
from wend import SubPath

member = P("extracted") / SubPath("member")


def extract(archive):
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            try:
                path = member.resolve(member=info.filename)
            except InvalidBindingError as e:
                print("skipped:", e)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(zf.read(info))
            print("wrote:", path)
```

```pycon
>>> extract("upload.zip")
wrote: extracted/docs/readme.txt
wrote: extracted/docs/img/logo.svg
skipped: member='../../.bashrc' must not contain '..'
skipped: member='/etc/cron.d/job' must be a relative path
```

A sub-path containing `..` is rejected even where the result would stay inside, as `a/../b` would.

## A fixed set of values: choices

Where the valid values are known in advance, list them with `choices=`:

```pycon
>>> from wend import Segment
>>> area = Segment("area", choices={"avatars", "documents"})
>>> stored = P(root) / area / user / filename
>>> stored.render(root="srv", area="documents", user="ada", filename="cv.pdf")
'srv/documents/ada/cv.pdf'
>>> stored.render(root="srv", area="config", user="ada", filename="cv.pdf")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: area='config': not one of {'avatars', 'documents'}
```

## Path and absolute parameters: Under

A parameter at the head of an expression, an `AnyPath` and an `Absolute` accept a whole path, which can lead anywhere. To keep such a path below a base, declare `Under` on the expression. `render` checks it against the rendered path, lexically, with no filesystem access:

```pycon
>>> from wend import AnyPath, Under
>>> extra = (P(root) / AnyPath("rel")).requires(Under(P(root)))
>>> extra.render(root="/data", rel="lookups/zones.csv")
'/data/lookups/zones.csv'
>>> extra.render(root="/data", rel="/etc/passwd")
Traceback (most recent call last):
  ...
wend.errors.ContainmentError: '/etc/passwd' is not under '/data' (required: Under('{root}'))
>>> extra.render(root="/data", rel="lookups/../../etc/passwd")
Traceback (most recent call last):
  ...
wend.errors.ContainmentError: '/data/lookups/../../etc/passwd' is not under '/data' (required: Under('{root}'))
```

The rule is conservative: a path with a `..` after the base is not under it, even when the `..` would stay inside. An `Absolute` parameter also rejects a relative value:

```pycon
>>> from wend import Absolute
>>> export = P(Absolute("export")).requires(Under(P("/data/exports")))
>>> export.render(export="/data/exports/2026-10")
'/data/exports/2026-10'
>>> export.render(export="/etc")
Traceback (most recent call last):
  ...
wend.errors.ContainmentError: '/etc' is not under '/data/exports' (required: Under('/data/exports'))
>>> export.render(export="exports/2026-10")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: export='exports/2026-10' must be an absolute path
```

`ContainmentError` is an `InvalidBindingError`, so one `except ValueError` handles every rejected value on this page.

## What is and is not a sandbox

The rules above are about the text of a path. Every rendering checks them, and [SEMANTICS.md §8](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#8-what-is-guaranteed-by-construction-and-what-is-only-tested>) records how each is guaranteed or tested. The filesystem can still lead elsewhere through a symlink, and it can change after a check.

### Symlinks

Create an upload directory that holds a symlink to a directory outside it:

```python
import os

Path("srv/uploads/ada").mkdir(parents=True)
Path("srv/uploads/ada/cv.pdf").write_text("%PDF\n")
Path("private").mkdir()
Path("private/key.pem").write_text("secret\n")
os.symlink(os.path.abspath("private"), "srv/uploads/ada/keys")
```

`render` checks `Under` lexically, so it accepts a path through the link. `check` also resolves symlinks, and rejects it:

```pycon
>>> files = (P(root) / "uploads" / user / SubPath("file")).requires(
...     Under(P(root) / "uploads")
... )
>>> files.render(root="srv", user="ada", file="keys/key.pem")
'srv/uploads/ada/keys/key.pem'
>>> files.check(root="srv", user="ada", file="keys/key.pem")
Traceback (most recent call last):
  ...
wend.errors.ContainmentError: 'srv/uploads/ada/keys/key.pem' resolves outside 'srv/uploads' (required: Under('{root}/uploads'))
>>> files.check(root="srv", user="ada", file="cv.pdf")
PosixPath('srv/uploads/ada/cv.pdf')
```

### Checks are point-in-time

`check` describes the filesystem at the moment it runs. It is not atomic with opening the path afterwards: if another process can change the tree, it can replace a checked file with a symlink before the program opens it. Conditions state what a program expects and catch mistakes. They do not stop another process.

### glob's symlink policy

Below an expression's literal prefix, `glob` does not descend into symlinked directories by default, and with `kind="file"` it does not yield a link:

```pycon
>>> listing = P(root) / "uploads" / user / Param("name")
>>> [m.path for m in listing.glob(root="srv")]
['srv/uploads/ada/cv.pdf', 'srv/uploads/ada/keys']
>>> [m.path for m in listing.glob(root="srv", kind="file")]
['srv/uploads/ada/cv.pdf']
```

The policy decides which directories the walk lists and how it classifies links. It does not make a yielded path safe to open: an entry can be replaced between the walk and the open, as it can between a check and an open.

## See also

- [Parameters](<https://lmmx.github.io/wend/pr-preview/pr-121/concepts/parameters/index.md>): the four kinds, and why a segment cannot traverse.
- [Effects](<https://lmmx.github.io/wend/pr-preview/pr-121/concepts/effects/index.md>): every condition, and what checks do and do not guarantee.
- [SEMANTICS.md §8](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#8-what-is-guaranteed-by-construction-and-what-is-only-tested>) (what is guaranteed by construction) and [§10](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#10-conditions>) (conditions).
- API reference: `Segment`, `SubPath`, `AnyPath`, `Absolute`, `Under`, `InvalidBindingError`, `ContainmentError`.
