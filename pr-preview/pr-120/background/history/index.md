# Project history

wend's design decisions are recorded in a development journal: dated Markdown files in [`docs/journal/`](<https://github.com/lmmx/wend/tree/master/docs/journal>) of the repository. Each entry covers one piece of work and records what was built, the decisions behind it and what was measured, so that the next change starts from the reasons. The format is described in [`docs/JOURNAL.md`](<https://github.com/lmmx/wend/blob/master/docs/JOURNAL.md>).

Claims in an entry carry a label:

- **\[Fact\]**: checked against a primary source: the code, a test, an essay or a benchmark;
- **\[Measured\]**: a number from a stated measurement;
- **\[Interpretation\]**: a reading of the facts;
- **\[Proposal\]**: a direction offered for decision;
- **\[Decision\]**: what was chosen, and why.

## Where to start

The [trajectory entry](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-17-trajectory-40.md>) tells the story from the [Future Paths](<https://cog.spin.systems/future-paths>) essays to the rebuilt library, and is written to be read first. [Future Paths and wend](<https://lmmx.github.io/wend/pr-preview/pr-120/background/future-paths/index.md>) gives the same mapping, brought up to date.

## The rebuild

These entries record how the 0.1 release was examined and replaced.

| entry | what it records |
| --- | --- |
| [Retrospective](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-17-retrospective-17.md>) | what 0.1 was, the unsound construction-time rewrites, the loss of t-string formatting, and the performance estimates |
| [Rebuild](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-17-rebuild-22.md>) | the segment normal form, matching, discovery, compilation and inference |
| [Audit](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-17-audit-22.md>) | an adversarial audit of the rebuild against its contract |
| [Messy trees](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-17-messy-trees-22.md>) | inference and matching on real, irregular trees, and t-string fidelity |
| [Trajectory](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-17-trajectory-40.md>) | the whole story so far, and the roadmap it implies |

## Features

These entries record the features built on the normal form, one entry per piece of work.

| entry | what it records |
| --- | --- |
| [Conditions](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-conditions-49.md>) | pre- and postconditions, steps, and what can be checked when, including what static checking could add |
| [Unions](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-unions-50.md>) | unions, `Alt`, `first` and queries |
| [Schemas](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-schemas-52.md>) | directory schemas, declared and inferred |
| [Construction](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-construction-53.md>) | making construction and `bind` faster |
| [Shared compilation](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-shared-compilation-57.md>) | what optimisation still buys: `compile_many` |
| [Lineage](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-lineage-58.md>) | lineage before and after a path exists, and content addressing |
| [Inference kinds](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-infer-kinds-59.md>) | inferred layouts of files and of directories |
| [Bindings](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-bindings-60.md>) | defaults, bindings from objects, counters, anchors and Pydantic |
| [Match gaps](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-match-gaps-61.md>) | the last format-spec differences between `render` and `match` |
| [Filesystem backends](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-fs-backends-62.md>) | the filesystem protocol, fsspec and prefix listing |
| [Documentation site](<https://github.com/lmmx/wend/blob/master/docs/journal/2026-10-18-docs-site-78.md>) | how this site is built, checked and published |

The number at the end of each file name is the issue or pull request the entry belongs to.
