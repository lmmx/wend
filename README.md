# wend

[![PyPI version](https://img.shields.io/pypi/v/wend.svg)](https://pypi.org/project/wend/)
[![Python versions](https://img.shields.io/pypi/pyversions/wend.svg)](https://pypi.org/project/wend/)
[![License](https://img.shields.io/pypi/l/wend.svg)](https://github.com/lmmx/wend/blob/master/LICENSE)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/lmmx/wend/master.svg)](https://results.pre-commit.ci/latest/github/lmmx/wend/master)

A library for templated paths using Python t-strings (3.14+)

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

Following the examples in the [blog post][blog]:

```py
from pathlib import Path
from wend import Param, P, T, RelativePath

# Define parameters (late-bound)
root = Param("root")
dataset = Param("dataset")
idx = Param("idx")
total = Param("total")

# Build expressions - these don't touch the filesystem
data_dir = root / "data" / dataset
chunk_file = data_dir / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")

# Inspect what's needed
print("Required params:", chunk_file.required_params())
# -> {'root', 'dataset', 'idx', 'total'}

# Resolve with bindings
path = chunk_file.resolve({
    "root": "/mnt/storage",
    "dataset": "train",
    "idx": 7,
    "total": 100,
})
print("Resolved:", path)
# -> /mnt/storage/data/train/chunk_0007-of-0100.parquet

# Constant folding happens at construction
folded = P("/home") / "user" / "data"
print("Folded type:", type(folded).__name__)
# -> LiteralExpr (not nested JoinExprs)

# Parent simplification
expr = root / "a" / "b"
print("Parent of join:", expr.parent)
# -> JoinExpr(ParamExpr, LiteralExpr("a")) -- the "b" is gone structurally

# Suffix chain collapse
double_suffix = (root / "file.txt").with_suffix(".tmp").with_suffix(".json")
print("Suffix chain:", double_suffix)
# -> WithSuffixExpr(base=JoinExpr(...), suffix='.json') -- .tmp is gone

# Connectivity: rebasing
config = RelativePath(
    base=root,
    relative=P("config") / "settings.yaml"
)
print("Config path:", config.resolve({"root": "/project"}))
# -> /project/config/settings.yaml

# Rebase to test environment
test_config = config.rebase(P("/tmp/test"))
print("Test config:", test_config.resolve({}))
# -> /tmp/test/config/settings.yaml
```

## Contributing

Contributions are welcome! Please:

1.  Open an issue to discuss bugs or feature requests
2.  Fork the repo and submit a PR for changes
3.  Install dev dependencies with `uv sync` and run `pre-commit install`

## License

MIT License - see [LICENSE](LICENSE) for details.
