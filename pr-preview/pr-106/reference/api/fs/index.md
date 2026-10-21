# wend.fs

Filesystems for discovery: the local disk, fsspec, and object stores.

`glob` and `infer` read a tree through `FileSystem`, a small protocol: - list a directory; - say what a path is; - identify a directory, to detect link cycles; - walk a tree; - give a view of one subtree for the duration of one walk.

`LocalFS`, the default, implements it with `os`. `FsspecFS` adapts an fsspec filesystem, so the same expressions discover keys in memory or in S3, GCS or Azure storage. `render`, `match` and `Lens` never touch a filesystem, so they need nothing from here.

Paths stay in the filesystem's own namespace. fsspec strips a URL's protocol: `memory://data/x` is `/data/x` and `s3://bucket/x` is `bucket/x`. `url_to_fs` splits a URL into a filesystem and such a path, which is then bound like any root::

```text
fs, root = url_to_fs("s3://bucket/data")
expr.glob(root=root, fs=fs)
```

A URL is not an expression's head. pathlib reads `s3://bucket` as the path `s3:/bucket`, so `glob` refuses one with a pointer to `url_to_fs`.

## DirEntry

Bases: `Protocol`

One entry of a directory listing, as `os.DirEntry` provides it.

### name

```python
name: str
```

### is\_dir

```python
is_dir(*, follow_symlinks: bool = True) -> bool
```

### is\_file

```python
is_file(*, follow_symlinks: bool = True) -> bool
```

### is\_symlink

```python
is_symlink() -> bool
```

## EntryKind

```python
EntryKind = Literal['file', 'dir', 'link', 'other']
```

## FileSystem

Bases: `Protocol`

What `glob` and `infer` need from a filesystem.

Paths are strings in the filesystem's namespace, joined with `/`; `.` is the directory a relative path starts from.

### scandir

```python
scandir(path: str) -> Sequence[DirEntry]
```

The entries of directory `path` sorted by name.

Empty if `path` is not a directory or cannot be listed.

### kind

```python
kind(path: str, *, follow_symlinks: bool = True) -> EntryKind | None
```

What `path` is, or None if it does not exist.

With `follow_symlinks=False` a symlink is `"link"`; otherwise it is what it points to, and None if that does not exist. A path that cannot be examined (no permission, a symlink loop) is None, as `os.path.isdir` reads it; a failure that says nothing about the path, such as a dropped connection, raises.

### dir\_key

```python
dir_key(path: str) -> Hashable | None
```

An identity for directory `path`, equal for the same directory reached by different paths.

None on a filesystem without links, where no walk can cycle. Raises `OSError` if the directory cannot be identified.

### walk

```python
walk(top: str) -> Iterator[tuple[str, list[str], list[str]]]
```

`(dirpath, dirnames, filenames)` for `top` and every directory below it, as `os.walk(top)` gives them.

The walk is top-down, does not descend symlinks, and visits only the `dirnames` left after the caller prunes the list in place.

### subtree

```python
subtree(path: str) -> FileSystem
```

A filesystem to read `path` and everything below it during one walk.

`LocalFS` returns itself. `FsspecFS` returns a view that answers from what it has listed, and lists the whole subtree at once if `listing="flat"`.

## FsspecFS

```python
FsspecFS(fs: Any, *, listing: Literal['flat', 'tree'] = 'flat')
```

An fsspec filesystem: object storage (S3, GCS, Azure), memory, HTTP...

`listing` decides how `glob` and `infer` read a tree:

- `"flat"` (default): one `find` for everything below the expression's literal prefix, which `glob` then walks in memory. On an object store that is a single prefix listing (one request per page of keys) however deep the layout, where a directory-by-directory walk makes one request per directory.
- `"tree"`: one `ls` for each directory the expression reaches, as on the local disk. Suited to filesystems with real directories (SFTP, HDFS), where `find` itself lists every directory, and to prefixes holding many keys that the expression never reaches.

Results are the same either way. Within one walk, a path whose parent has been listed is classified without another request.

Stores have no symlinks: no entry is a link, so `glob`'s symlink options change nothing, and `dir_key` is None. A directory is a prefix of some key or an explicit marker (a key ending in `/`, or `makedirs` on the memory filesystem), so an empty directory exists only as a marker. A key that is also a prefix of other keys is a directory. Keys with an empty, `.` or `..` segment cannot be rendered by any expression and are never listed.

fsspec's own local filesystem is refused: use `LocalFS`, which keeps `glob`'s symlink policy and cycle detection.

### fs

```python
fs = fs
```

### listing

```python
listing = listing
```

### scandir

```python
scandir(path: str) -> list[_Entry]
```

### kind

```python
kind(path: str, *, follow_symlinks: bool = True) -> EntryKind | None
```

### dir\_key

```python
dir_key(path: str) -> None
```

### walk

```python
walk(top: str) -> Iterator[tuple[str, list[str], list[str]]]
```

### subtree

```python
subtree(path: str) -> _Subtree
```

## LocalFS

The local disk through `os`, the default for `glob` and `infer`.

### scandir

```python
scandir(path: str) -> list[DirEntry[str]]
```

### kind

```python
kind(path: str, *, follow_symlinks: bool = True) -> EntryKind | None
```

### dir\_key

```python
dir_key(path: str) -> tuple[int, int]
```

### walk

```python
walk(top: str) -> Iterator[tuple[str, list[str], list[str]]]
```

### subtree

```python
subtree(path: str) -> LocalFS
```

## url\_to\_fs

```python
url_to_fs(url: str, **storage_options: Any) -> tuple[FileSystem, str]
```

Split a URL into a filesystem and a path in that filesystem's namespace.

`url_to_fs("s3://bucket/data")` is `(FsspecFS(S3FileSystem), "bucket/data")`; `url_to_fs("memory://data")` is `(FsspecFS(...), "/data")`; a local path or `file://` URL gives `LocalFS`. Bind the path as an expression's root and pass the filesystem to `glob` or `infer`. `storage_options` go to fsspec (credentials, `anon=True`, and so on). Needs fsspec (`pip install "wend[fsspec]"`).
