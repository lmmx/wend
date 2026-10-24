# 2026-10-21: Future Paths after 0.2.0 (stock-take)

This entry takes stock, after the 0.2.0 release, of how wend measures up to the five
[Future Paths](https://cog.spin.systems/future-paths) essays, and of how the
documentation presents the library against them. It records the review of the essays
made on 2026-10-20, what has changed since, and a probe of capability types with the
two type checkers the project uses.

Labels: **[Fact]**, **[Measured]**, **[Interpretation]**.

---

## Current State

### The library against the essays

- **[Fact]** wend 0.2.0 is published on PyPI (tag `0.2.0`, commit `c239075`) as the
  rebuilt library, with one `PathExpr` type whose rules are written in
  `docs/SEMANTICS.md` (src/wend/_expr.py:448).
- **[Fact]** The essays' distinction between describing a path and realising it is the
  organising idea of the library: an expression keeps its literals, parameters and
  format specs until `render`, `resolve` or `bind` is called (src/wend/_expr.py).
- **[Fact]** Part 1's union of alternatives tried in order is `PathUnion` with `first`
  and `renderings` (src/wend/_union.py:183).
- **[Fact]** Part 1's intersection and difference of path sets, and the essay's own
  `var/log` example of files modified since yesterday, are `&`, `-` and
  `.where(File, modified_after(yesterday))` on a lazy `Query` that runs only when
  `glob` or `match` is called (src/wend/_expr.py:516-539, src/wend/query.py:114).
- **[Fact]** Part 1's declared project layout with typed accessors
  (`project.data.raw`), validation and scaffolding is `wend.schema.Tree`
  (src/wend/schema.py).
- **[Fact]** Part 1's schema inference in the manner of genson is `wend.infer.infer`.
  It recognises digit runs with their padding, dates, UUIDs and long hex tokens, and
  reports a cardinality per layout (src/wend/infer.py:6-11, src/wend/infer.py:85-87).
- **[Fact]** Part 1's pre- and postconditions on pipeline steps are the conditions
  `Exists`, `Absent`, `File`, `Dir`, `Readable`, `Writable`, `Creatable` and `Under`,
  declared with `requires` and `ensures` and checked by `check` and `Step`
  (src/wend/conditions.py).
- **[Fact]** Part 1's lineage and Nix-style content addressing are `expr.tag`, `Ledger`,
  `explain` and `content_key` (src/wend/_expr.py:616, src/wend/lineage.py).
- **[Fact]** Part 2's relations between paths are `base`, `base_rel`, `rebase`,
  `sibling`, `cousin` and `under` (src/wend/_expr.py).
- **[Fact]** Part 2's containment against untrusted input is enforced at render time:
  a segment parameter cannot add or remove segments, and `Under` is checked lexically
  by `render` and with symlinks resolved by `check` (docs/SEMANTICS.md §4,
  docs/site/guides/untrusted-input.md).
- **[Fact]** Parts 4 and 5's build-once, resolve-many compilation is `expr.compile()`,
  which generates one Python function per expression, and `compile_many`, which shares
  parameter lookup, checking and formatting across a set of expressions
  (src/wend/_compile.py).
- **[Fact]** Part 5's batch resolution runs through Polars: `wend.frame` lowers an
  expression to Polars expressions, so Polars renders a whole column (src/wend/frame.py).
- **[Fact]** Part 1's `file://` URLs and fsspec stores are read through
  `wend.fs.url_to_fs`, which gives `LocalFS` for `file://` and `FsspecFS` otherwise
  (src/wend/fs.py:438).
- **[Fact]** Matching a concrete path back into typed bindings (`match`, `match_all`,
  `Lens.backward`) is wend's own emphasis: the essays mention it only by implication,
  through the backward direction of a lens and through schema inference.

### Research carried out since the review

- **[Fact]** PR #89 added `overlaps(a, b)`, a three-valued test (YES with a witness,
  NO sound under stated assumptions, MAYBE with a reason) of whether two expressions
  can render one path, and `EffectGraph`, which relates the declared effects of a set
  of `Step`s into edges, hazards, conflicts and an order
  (src/wend/_experimental/overlap.py, src/wend/_experimental/effects.py,
  docs/journal/2026-10-20-overlap-research-89.md).
- **[Fact]** `wend._experimental` is excluded from the published wheel by
  `wheel-exclude` in pyproject.toml and is kept in the sdist and the repository
  (PR #101, tests/packaging_test.py).
- **[Fact]** The research for #89 found the `choices` defects that 0.2.0 fixed in
  PRs #96 and #97 — item 6 of the promotion list in
  docs/journal/2026-10-20-overlap-research-89.md ("the value semantics in core") is
  settled for declared members, and issue #95 carries the remaining acceptance
  questions (colliding members, values that render unlike their member).

### The documentation against the essays

- **[Fact]** The home page opens with the positioning paragraph ("A wend expression
  records *how* a path is built …"), followed by a table of what one expression can do
  and a closing sentence that links the essays at cog.spin.systems
  (docs/site/index.md:19-23, docs/site/index.md:96-113).
- **[Fact]** The home page links the essays but not the Background page that maps each
  essay to the code (docs/site/index.md:112-113,
  docs/site/background/future-paths.md).
- **[Fact]** The Background page lists three open themes: static checking, a native
  backend gated on measurements (#37), and effects as data across a program
  (docs/site/background/future-paths.md:180-187).
- **[Fact]** The statement that conditions are checked at runtime, not by a type
  checker, appears on the Effects concept page and the Background page, and on no guide
  and not on the home page (docs/site/concepts/effects.md:208-209,
  docs/site/background/future-paths.md:56-58).
- **[Fact]** The site has six guides: datasets, pipeline steps, lenses, untrusted
  input, lineage and settings (zensical.toml:27-32).

## Missing

### Unrealised in the library

- **[Fact]** Static checking: a type checker sees every expression as `PathExpr` with no
  capabilities, containment or connectivity in its type — `PathExpr` takes no type
  parameters (src/wend/_expr.py:448).
- **[Fact]** Effects as data across a program: `Step.effects()` lists one step's
  declarations, and the program-wide graph lives only in `wend._experimental.effects`,
  outside the public API.
- **[Fact]** Pattern strings: a format-style string is a literal, so
  `P("/data/{dataset}/chunk_{idx:04d}.parquet")` has the pattern
  `/data/{{dataset}}/chunk_{{idx:04d}}.parquet` and no parameters. Part 4's
  `parse_path_pattern(...)` and a glob-string grammar have no counterpart; t-strings are
  the only way to declare a field.
- **[Fact]** A native backend (Rust or pyo3, an arena, SIMD, plans chosen per backend
  for local disk and S3) has no code; issue #37 gates it on measurements.
- **[Fact]** `infer` recognises no regex-like or wildcard name patterns beyond digit
  runs, dates, UUIDs and hex tokens (src/wend/infer.py).
- **[Fact]** Compiled-size introspection (`num_instructions()`, `num_slots()` in part 5)
  has no counterpart in src/wend/_compile.py.
- **[Fact]** `compile_many` shares per-parameter work but computes no shared sub-path
  once across expressions (src/wend/_compile.py).
- **[Fact]** An expression carries no URI type: `file://` and fsspec URLs are accepted
  by `url_to_fs` (src/wend/fs.py:438), not as a kind of `PathExpr`.
- **[Fact]** The library always produces one normal form for equivalent spellings
  (`a/"x"/"y"` and `a/"x/y"`); part 4's choice between them by cost has no counterpart.

### Undocumented in the site

- **[Fact]** Queries have no page: `.where(` appears in README.md and in no file under
  docs/site/, so `&`, `-`, `.where` and `modified_after` are documented only in the
  README and the API reference.
- **[Fact]** Unions appear in the concept index table and the Effects page, with no
  guide (docs/site/concepts/index.md, docs/site/concepts/effects.md).
- **[Fact]** Project layouts (`Tree`, `validate`, `scaffold`, `from_inferred`) appear
  only in the concept index table, the Effects page and the Background page
  (docs/site/concepts/index.md:56-57).
- **[Fact]** Schema inference has no narrative page: `infer(` appears in no file under
  docs/site/ outside the API reference.
- **[Fact]** Object stores are covered by one section of the Effects concept page
  ("Other filesystems") and by the installation extras, with no guide
  (docs/site/concepts/effects.md:211-216).
- **[Fact]** The docstrings PR planned in issue #78 has not landed — the reStructuredText
  rendering problems listed under Missing in docs/journal/2026-10-18-docs-site-78.md
  apply to the reference.

## Divergence

- **[Fact]** The Background page's "What is still open" names three themes and none of
  the smaller unrealised items listed under Missing above (pattern strings, inferred
  name patterns, compiled-size introspection, shared sub-paths, URI-typed expressions)
  (docs/site/background/future-paths.md:180-187).

## Measured

- **[Measured]** Capability types need no type-checker plugin.
  `docs/journal/scripts/2026-10-21-capability-probe.py` gives a stand-in `PathExpr`
  one phantom type parameter per capability (`Yes` or `No`), overloads `requires` to
  set one parameter, and declares functions that demand one capability and leave the
  others generic (`def load[W](p: PathExpr[Yes, W])`). Pyright 1.1.407 and ty 0.0.90
  both accept the four valid calls, reject `load` of a write-only path and `save` of a
  read-only path, and infer `PathExpr[Yes, Yes]` for a path given both capabilities.
- **[Fact]** ty has no plugin system: Astral's feature overview for ty
  (astral-sh/ty#1889) tracks dedicated first-party support for Pydantic, Django, attrs
  and pytest, with the scope "currently not decided", and lists no plugin interface.
- **[Interpretation]** The probe encodes capabilities that a method call adds. It does
  not cover containment that names a root (`Path[Under[root]]`), which would need the
  root in the type, such as a literal or a nominal marker class, nor conditions that an
  operation removes, such as `parent` of a `File` path.
