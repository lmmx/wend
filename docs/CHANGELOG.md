# Changelog

Each release's notes, newest first. A release's GitHub Release takes its notes from here,
followed by the pull requests it includes, which GitHub lists. Write the next release's
notes under "Unreleased": `just release` titles them with the new version in the release
commit. Changes in behaviour also go in [MIGRATING.md](MIGRATING.md).

## Unreleased

### New

- **`builtin_values=True` relates a field in either role** (#125). A parameter alone in
  a segment (`P(root) / split`, or `T(t"{split}")`) and the same parameter plainly in
  text (`T(t"{split}.json")`) render one text for a value of a builtin type. With
  `builtin_values=True`, `relate` and `EffectGraph` now cancel them, so a shard
  directory and its manifest never meet. `Relation.assumptions` names
  `builtin_values` wherever such an answer may rest on it. Without the option nothing
  changes: a `str` subclass may render the two apart.
- **Names changed below a `SubPath` are written out** (#127). A name changed by
  `with_name`, `with_suffix` or `with_stem` while its base ends in a `SubPath` had no
  view, and `relate` left most such answers `"unknown"`. It is now written out as the
  change of the `SubPath`'s last segment, or of what precedes the `SubPath`. A path that
  begins with the same base is split alike, so `({root}/raw/{rel...}).with_suffix(".csv")`
  is never `{root}/out/x`, and `(data/{sc...}).with_suffix(".b")` is never strictly
  inside or above `data/{sc...}`. On #119's samples, 288 more `"unknown"` answers are now
  `"never"`.
- **Stems of `.` and `..` are written out** (#128). `with_stem(".")` and
  `with_stem("..")` of a name whose suffix is unknown had no view, since they may render
  the name `..`. They are now written out as the stem, a dot and the suffix's text, or
  the name `..`, so `({root}/{x}).with_stem("..")` is never `{root}/a`. On #119's
  samples, 552 more `"unknown"` answers are now `"never"`.
- **Depths decide through `SubPath`s and deferred operations** (#131). A path's
  depth is its count of segments plus what its `SubPath`s, head parameters and deferred
  heads render. Changed names keep their base's depth, parents have one fewer, paths made
  relative drop the other's and joins add theirs. Under shared bindings a part both
  sides share cancels, and every part renders no segments or more, so depths bound the
  relations: `({root}/{n:d}.{p}/{s...}).with_suffix("")` is never
  `{root}/{n:d}.{p}/{n:d}.{p}/{s...}`. On #119's samples, 282 more `"unknown"` answers
  are now `"never"`.

### Fixed

- **`relate` gives the same answers whatever `PYTHONHASHSEED` is** (#126). Whether a
  bounded search found an example, and so `"sometimes"` or `"unknown"`, could depend on
  string hashing. A parameter's `choices` were tried in set order, and the names `relate`
  makes up for its own reasoning came from `hash()`. Choices are now tried in a fixed
  order, and those names are numbered. They also never take the name of a parameter of
  either expression, which `hash()` made unlikely but did not rule out.

- **`relate` no longer takes minutes over many finite choices** (#125). With
  `builtin_values=True`, each `SubPath` or parameter with `choices` multiplies the
  shapes the overlap analysis pairs, and keeping its candidate paths took quadratic
  time. An expression with five `SubPath`s of three choices took longer than two
  minutes; it now takes a third of a second, and no answer changes.

### Research, in the repository but not the wheel

- **An exact oracle for `relate(shared=False)`** (#129). `src/wend/_experimental/lang_oracle.py` turns
  an expression into the regular language of the paths it renders, built from wend's
  interpreter and pathlib's rules, and nothing of `relate`'s. On the expressions that
  use no name twice, it decides each relation exactly, with bindings that wend renders
  to show every relation it finds possible. `tests/lang_oracle_test.py` checks the
  oracle against rendering and `relate` against the oracle. `bench/relate_oracle.py`
  compares them on #119's samples. Over 8,688 answers, `relate`
  contradicts the oracle nowhere, and leaves 1,575 to settle, 1,402 of them `"sometimes"`
  answers its search misses.
- **The oracle decides names used twice** (#130). Two uses of a name render one text
  where they render it the same way: as a path or a segment, or formatted with one
  conversion and spec. Read apart, then held to each text a use can take, such pairs are
  decided as well, and `"never"` stays exact. On #119's samples the oracle now decides
  4,427 of 4,500 pairs, and finds no contradiction with `relate` in 13,281 answers.
- **The oracle under shared bindings** (#132). `relate_shared` ties each name of
  both sides as one name's uses, and decides a name both sides default both bound and
  unbound. Where both begin with the same head and parts, it also decides what follows,
  since in a free monoid a shared prefix cancels. That checks `relate`'s default mode,
  whose `"never"` answers pipelines rely on. On #119's samples it decides 4,419
  of 4,500 pairs, finds no contradiction with `relate`, and settles 892 of its
  `"unknown"` answers.
- **Exchange-and-validate is fooled by a reused inode number** (#133). `publish`'s
  `expect=(st_dev, st_ino)` names a number, which ext4 gives to a new object once the
  observed one is gone, so a writer can replace another's update, told nothing changed:
  with two writers. `publish.identity()` adds the inode's generation, and an `expect`
  given as an identity tells the two apart. A draft whose exchange or replacement
  failed after its link can no longer be named, and `publish` now refuses it with that
  reason instead of a later `ENOENT`. The three-writer test failed in 38 of 40 runs on
  ext4 for this reason; it now holds the observed object open.
- **The oracle counts characters and segments** (#135). Uses of one name in one
  shape render one text, so they emit as many characters, and as many separators where
  both render segments. Where some weighting of their differences is positive on every
  walk of the intersection automaton, the relation never holds. The bench now sorts
  each pair where `relate` says `"always"` and the oracle `"never"`: a contradiction
  where a pooled binding renders both; vacuous where a side's language proves that
  nothing renders it; otherwise unresolved. On #119's samples the oracle now
  confirms 9,565 of `relate(shared=True)`'s 9,703 `"never"` answers, where it confirmed
  8,670 of the same pairs before, and contradicts none.

## 0.5.0

### New

- **What paths given as existing, reads and listings establish** (#121).
  `EffectGraph.obligations()` takes a path given as `existing` as a fact from the start
  that no step forgets: it exists, and so does every directory above it. A passed
  `Readable` check says its path exists, and a passed `Listable` check that it exists as
  a directory, so later requirements of either are discharged, and a requirement that
  the path be absent is refuted.
- **Fewer unknowns on realistic pipelines** (#122). Over eight realistic pipelines
  (`bench/effects_corpus.py`), the links `EffectGraph` could neither prove nor rule out
  fall from 19 to 6:
  - `relate` cancels equal pieces at either end of two segments, so `{day}.csv` and
    `{day}.csv.gz`, or `run{s}/x` and `run{s}.log`, never meet;
  - a suffix or stem changed from one base is written out by how pathlib splits the
    base's name, so `{day}.parquet` and `with_stem("summary")` of `{day}.csv` never
    meet;
  - `EffectGraph` drops a parent conflict where either step requires a path inside the
    shared directory to exist: while it is missing, that step fails and makes nothing.
- **Deferred operations keep what pathlib guarantees of them** (#123). A deferred
  `parent` keeps its base's anchor, a deferred `relative_to` is relative, and a deferred
  join keeps the anchors its sides allow, so `relate` rules out more paths by anchor
  alone. A parent deferred because its base ends in a `SubPath` is written out by what
  the `SubPath` renders: `parent({root}/raw/{rel...})` is `{root}/raw/{rest...}` or
  `{root}`, so it never meets `{root}/out/x`. Below one deferred head, a third of the
  answers `relate` left `"unknown"` on #119's sample are now `"never"`.
### Fixed

- **A name defaulted differently on each side is no longer tied inside a changed name**
  (#124). `relate` could answer `"always"` or `"never"` wrongly for two expressions in
  which one name has a different default on each side, and the name sits inside a name
  changed by `with_suffix`, `with_stem` or `with_name`, or inside a parent of a
  `SubPath`. Left unbound, each side renders its own default, but the analysis tied the
  two texts. `(data/{x}).with_suffix(".q")/y`, with `x` defaulting to `a` on one side
  and `b` on the other, was "always" the same, though unbound it renders `data/a.q/y`
  and `data/b.q/y`. `EffectGraph.obligations()` could then discharge a requirement by
  a fact about the other path. 0.4.0 was affected through changed names. Pairs whose
  names have the same defaults on both sides, and every `relate(e, e)`, were not.

## 0.4.0

### New

- **Relations between families** (#118). `wend.relate(a, b)` says, before any binding,
  whether two expressions, unions or strings name the same path, one inside the other, or
  neither. Each of its three answers, `same`, `inside` and `contains`, is `"always"`,
  `"sometimes"` (with an example of the bindings and the paths), `"never"` or
  `"unknown"`. A parameter name means one value on both sides unless `shared=False`.
  `Relation.kind` sums it up in one word: `"same"`, `"inside"`, `"contains"`,
  `"disjoint"`, `"overlapping"` or `"unknown"`.
  [SEMANTICS.md §15](https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md) says how
  each answer is proved, and that identity is lexical: a symlink, `..` resolved on disk
  or case folding are not seen.
- **Effects across a pipeline** (#118). `wend.effects.EffectGraph(steps)` relates what a
  set of `Step`s declare they read, list, write and delete, with every link as sure as its
  relation:
  - dependencies, hazards (a step that reads or lists a path another deletes) and
    conflicts (two steps that write, or delete, or write and delete one path, or a path
    declared with no verbs and another). A declared path covers what lies below it, so
    a step that writes `{root}/raw` and one that reads `{root}/raw/{day}.csv` are linked;
  - `order()`, `stages()` (the groups that may run at once), `independent(x, y)`,
    `cycles()`, `dependencies(certain=True)` (the links that hold on every run) and
    `explain()`, one sentence per link with an example.

  Every query counts every link, whatever its certainty, so a possible interference is
  never taken for independence; `cycles(certain=True)` lists the cycles no binding
  avoids. Parents a creation may make are part of its effect: a port requiring a
  directory to exist follows the steps that may make it, and a `Creatable` or `Writable`
  check is kept apart from a creation below a directory that may be missing.
  `existing=[...]` names the directories that exist before the run. The guarantees hold
  for the effects the steps declare, with paths compared as rendered strings, not as
  files.

  Under one shared `{root}`, a six-step pipeline that the experimental graph could not
  order (four "maybe" edges and a false cycle) gets five certain dependencies, an order and
  stages, in about 0.2 ms where the experimental graph took 27 to 40 ms.

- **`relate` proves more** (#119). Paths with different anchors (relative, `/`, `//`) are
  never related; paths of segments alone nest only by depth; and a name changed by
  `with_suffix`, `with_stem` or `with_name` while its value is unknown is related as its
  base's parent and one segment of which the operation fixes the suffix, the stem or
  the name. Over the property tests' pairs, `"unknown"` answers fall from 15% to 8%,
  and from 26% to 11% for changed names, with no answer lost. `EffectGraph` gains as
  much: outputs named after one input by different suffixes are independent.

- **What a requirement relies on** (#120). `EffectGraph.obligations(schedule=None)` says,
  for each condition a step requires, what settles it when the steps run in order or by
  stages: `"discharged"` by an earlier check or promise of the same path (however it is
  spelt) that no step in between may change, so it holds whenever the earlier steps
  completed; `"refuted"`, so the step fails; `"at risk"`, naming the step that may have
  broken it; or `"external"`, for the world to provide. Creating and writing are never
  discharged. The answers rest on `wend.effects.ASSUMPTIONS`: nothing outside the steps
  changes their paths, each step does what it declares, and no two spellings name one
  file. It carries the experimental families analysis into the library, and a disk
  oracle checks it as that analysis was checked.
- **A deferred head is itself** (#120). Two paths below one `parent`, `relative_to` or
  changed name that is not known until binding now cancel it as a shared prefix, so
  `relate(e, e)` is `"same"` for every expression, and what follows the head decides.
  Over pairs below one such head, `"unknown"` answers fall from 64% to 33%, with no
  answer lost.

### Fixed

- **A changed name may be `..`** (#120). `relate` could answer `"never"` for paths that
  meet, where a name changed by binding renders `..`: pathlib keeps the name `..` through
  `with_suffix("")`, and makes it from the stem `..`, or the stem `.` before the suffix
  `.`. Neither the overlap analysis nor the view of a changed name (#119) allowed it.
  `relate` is new since 0.3.0, so no release gave these answers.

### Changed

- The overlap analysis behind `relate` moved from `wend._experimental.overlap` into the
  wheel as the private `wend._overlap`. The experimental name is an alias for it, and
  `wend._experimental.effects` stays, superseded by `wend.effects`.

## 0.3.0

wend 0.3.0 adds typed declarations and evidence to `PathExpr`, and makes `Creatable` refuse
a path that a broken symlink blocks. The research behind them lands in the repository as
experimental code and journals, and is not in the wheel.

```sh
pip install -U wend   # Python 3.14+
```

Documentation: https://lmmx.github.io/wend/

### Upgrading from 0.2

[MIGRATING.md](https://github.com/lmmx/wend/blob/master/docs/MIGRATING.md#from-02-to-03)
lists the changes in behaviour. In short:

- **`Creatable`, and `Writable` for a missing path, fail when a broken symlink occupies the
  path's name or a name above it** (#111). Before, the check passed, and then no way of
  creating the path worked: `mkdir -p` failed with `EEXIST`, and `open(path, "w")` wrote
  through the link to wherever it pointed. The check now raises a `CapabilityError` saying
  the name "is a broken symlink". A symlink loop stays indeterminate.
- **`PathExpr` is generic** (#113). Its type parameters have defaults that accept any
  expression, so an unparameterised `PathExpr` annotation means what it did, and `check()`
  and `confirm()` still return a plain `Path`.
- **A `Param`'s repr and its `choices` error** show the members as one set,
  `{'test', 'train'}`, instead of a list of quoted reprs (#102).

### New

- **What an expression declares** (#107). `PathExpr.declares` and `PathUnion.declares`
  return a `Declarations`: the atoms the expression requires, the atoms it ensures, and the
  bases it is declared `Under`. `Step.effects` is now computed from it, with unchanged
  output. [SEMANTICS.md §10.1](https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md)
  states that a declaration is an obligation the runtime checks, not a fact about the
  filesystem.
- **Typed declarations** (#113). `PathExpr` is generic, `PathExpr[C, K, Q]`:
  - `C` is what `requires` declares and `Q` what `ensures` declares, as literal atoms such
    as `Literal["read", "exists"]` and `Under` markers;
  - `K` is `IsFile` once `File` is declared, and `Unspecified` otherwise.

  A function can ask for an expression that declares what it needs, and Pyright and ty both
  reject one that does not, with no plugin. Joining below a declared `File` gives
  `JoinBelowFile`, which is not a path. One known gap: ty 0.0.90 can reject an inline
  declaration of several atoms passed where a multi-atom type is expected. Binding the
  expression to a name first avoids it.
- **Evidence** (#113). `checked()` and `confirmed()` run the same checks as `check()` and
  `confirm()`, and return evidence instead of the path: `Checked[C, K]` and
  `Confirmed[Q, K]`, which record the rendered path and the atoms found true of it at that
  moment.
  - Evidence is not a path: `.path` holds the path, and nothing derived from it inherits
    the evidence.
  - A later change to the filesystem leaves it as it was.
  - [SEMANTICS.md §10.2](https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md) says
    what it establishes, and what it does not.
- New names: `Checked`, `Confirmed`, `IsFile`, `NotFile`, `Unspecified`, `JoinBelowFile`.

### Research, in the repository but not the wheel

The research programme from path algebra to typed knowledge of program state is in
`wend._experimental`, with its tests and journals; the
[research index](https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-22-research-index.md)
orders them. It covers:
- what a program knows about a path before and after each step (#108, #109);
- when two strings name one file, and confinement with `openat2` (#110, #112);
- freshness, atomic publication and consistency (#114);
- a synthesis with read leases, an experimental run model (SEMANTICS.md §14), a privileged
  CI job and a mutation harness (#115).

`wend._experimental` ships in the sdist but not the wheel, and none of it is a supported
API.

### Releasing

A release is made in CI from start to finish. "Deploy Release" bumps and tags the version
and CI publishes it to PyPI (#116), then the GitHub Release workflow makes its GitHub
Release from these notes.

## 0.2.0

The first release of the rebuilt library: see its
[GitHub Release](https://github.com/lmmx/wend/releases/tag/0.2.0) and
[MIGRATING.md](https://github.com/lmmx/wend/blob/master/docs/MIGRATING.md#from-01x-to-02).
