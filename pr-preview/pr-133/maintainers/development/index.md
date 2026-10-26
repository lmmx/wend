# Development

## The repository

| path | holds |
| --- | --- |
| `src/wend/` | the package. Public modules (`wend`, `wend.fs`, `wend.infer`, `wend.schema`, ...) re-export from private ones (`_expr.py`, `_match.py`, `_fs.py`, ...) |
| `tests/` | the tests, one file per area, named `*_test.py` |
| `examples/` | runnable scripts, each run by `tests/examples_test.py` |
| `bench/bench.py` | the benchmarks |
| `docs/SEMANTICS.md` | the contract: what every operation must compute |
| `docs/MIGRATING.md` | the changes between releases |
| `docs/CHANGELOG.md` | each release's notes, which its GitHub Release takes |
| `docs/journal/` | the development journal ([Project history](<https://lmmx.github.io/wend/pr-preview/pr-133/background/history/index.md>)) |
| `docs/site/`, `zensical.toml` | this site ([Documentation](<https://lmmx.github.io/wend/pr-preview/pr-133/maintainers/documentation/index.md>)) |

## Setting up

wend needs Python 3.14 or later. [uv](<https://docs.astral.sh/uv/>) installs the package with its `test` dependency group, which is the default group:

```sh
uv sync
uv run pytest
```

`just test` runs the same tests with the project's Python. The `test` group includes the optional integrations (Pydantic, fsspec, Polars), so their tests run too.

The hooks in `.pre-commit-config.yaml` (ruff, ruff format, file checks and a conventional-commit check on the message) run with [prek](<https://github.com/j178/prek>) or pre-commit:

```sh
prek install
just pc-fix        # run every hook on every file
```

CI runs the tests on every CPython version from 3.14 that uv provides, including pre-releases.

## The contract and its tests

[`docs/SEMANTICS.md`](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md>) states what wend computes, independently of how. Two kinds of test check the code against it:

- **`tests/contract_test.py`** holds a reference evaluator written from the contract alone. It evaluates terms strictly with pathlib and imports only wend's parameter declarations, never its expressions, matcher or compiler. Hypothesis generates random terms and checks that wend agrees with it.
- **`tests/oracle_test.py`** builds each random expression twice, once with wend and once as the eager pathlib computation on the formatted strings. If wend renders a value, the oracle renders the same one; if the oracle raises, so does wend.

A change to the contract comes with the matching change to the reference evaluator, in the same pull request, and the reverse. SEMANTICS.md §8 says which guarantees hold by construction and which are only tested.

## Benchmarks

```sh
uv run python bench/bench.py --quick
uv run python bench/bench.py matching discovery
```

Each timing is the median of several repeats, in nanoseconds per item, next to baselines such as eager pathlib joins and hand-written regular expressions. Absolute numbers depend on the machine, so compare rows within one run.

## Conventions

- **Commits** follow [Conventional Commits](<https://www.conventionalcommits.org/>) (`feat(union): ...`, `fix(core): ...`, `docs: ...`), checked by a commit-message hook. `just commit "message"` runs the fixers first and stages what they change.
- **Journal entries.** A piece of work with decisions worth keeping gets an entry in `docs/journal/`, named `YYYY-MM-DD-topic-<number>.md` after its issue or pull request, in the format of [`docs/JOURNAL.md`](<https://github.com/lmmx/wend/blob/master/docs/JOURNAL.md>).
- **Documentation.** A change to public behaviour updates the README, SEMANTICS.md where the contract changes, and the pages of this site that describe it. Their examples are tests, so a stale example fails CI.
