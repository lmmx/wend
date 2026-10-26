# Installation

wend needs Python 3.14 or later. Its expressions are built from template strings (t-strings), which [PEP 750](<https://peps.python.org/pep-0750/>) added in Python 3.14.

```sh
pip install wend
```

With uv, add it to a project:

```sh
uv add wend
```

The core package has no dependencies.

## Extras

Each optional integration is an extra, which installs the library it needs.

| extra | installs | enables |
| --- | --- | --- |
| `pydantic` | Pydantic | `wend.pydantic.PathOf`: path fields on Pydantic models, validated against an expression |
| `fsspec` | fsspec | `wend.fs.FsspecFS` and `wend.fs.url_to_fs`: `glob` and `infer` on object stores and other fsspec filesystems |
| `polars` | Polars | `wend.frame.resolve_frame`: render one expression for every row of a DataFrame |

```sh
pip install "wend[polars]"
uv add "wend[pydantic,fsspec]"
```

The `fsspec` extra installs fsspec alone. A store's own backend, such as s3fs for S3 or gcsfs for Google Cloud Storage, is installed separately.

## Checking the installation

```pycon
>>> from wend import Param, T
>>> name = Param("name")
>>> T(t"data/{name}.csv").render(name="trips")
'data/trips.csv'
```

On an earlier Python, `t"..."` is a syntax error.

## Next

- [Quickstart](<https://lmmx.github.io/wend/pr-preview/pr-136/getting-started/quickstart/index.md>): build, render, match and glob one expression.
- [API reference](<https://lmmx.github.io/wend/pr-preview/pr-136/reference/index.md>): which modules need which extra.
