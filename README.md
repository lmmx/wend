# wend

[![PyPI version](https://img.shields.io/pypi/v/wend.svg)](https://pypi.org/project/wend/)
[![Python versions](https://img.shields.io/pypi/pyversions/wend.svg)](https://pypi.org/project/wend/)
[![License](https://img.shields.io/pypi/l/wend.svg)](https://github.com/lmmx/wend/blob/master/LICENSE)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/lmmx/wend/master.svg)](https://results.pre-commit.ci/latest/github/lmmx/wend/master)

Symbolic, typed, invertible filesystem paths built from Python t-strings (3.14+).

## Installation

```sh
uv pip install wend
````

## Requirements

- Python 3.14+

## About

For backstory read my blog about this package [cog.spin.systems/future-paths][blog]!

[blog]: https://cog.spin.systems/future-paths

The general idea is to use t-strings to house eagerly instantiated parameter objects which offer a
form of deferred execution.

## Usage

```py
from wend import P, Param, Segment, T

root = Param("root")
split = Segment("split", choices={"train", "test"})
idx, total = Param("idx", type=int), Param("total", type=int)

shard = root / "data" / split / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")

shard.resolve(root="/mnt", split="train", idx=7, total=100)
# PosixPath('/mnt/data/train/chunk_0007-of-0100.parquet')
shard.match("/mnt/data/train/chunk_0007-of-0100.parquet")
# Match(..., {'root': '/mnt', 'split': 'train', 'idx': 7, 'total': 100})
shard.parent  # PathExpr('{root}/data/{split}')
shard.bind(
    root="/mnt"
)  # PathExpr('/mnt/data/{split}/chunk_{idx:04d}-of-{total:04d}.parquet')
```

The semantic contract is in [docs/SEMANTICS.md](docs/SEMANTICS.md); `demo.py` walks
through the core API.

## Contributing

Contributions are welcome! Please:

1.  Open an issue to discuss bugs or feature requests
2.  Fork the repo and submit a PR for changes
3.  Install dev dependencies with `uv sync` and run `pre-commit install`

## License

MIT License - see [LICENSE](LICENSE) for details.
