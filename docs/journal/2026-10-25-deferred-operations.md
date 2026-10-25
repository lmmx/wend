# 2026-10-25: Deferred operations with known anchors, and parents written out (#123)

#119 gave changed names a view and their anchors, and #122 wrote changed suffixes and
stems out by how pathlib splits their base's name. The other deferred operations,
`parent`, `relative_to` and `join`, stayed opaque: any anchor, and no prefix to cancel.
This entry gives them what pathlib guarantees of them. The contract is
`docs/SEMANTICS.md` §15.3 (2, 3).

## 1. Anchors

**[Proven]** wend renders a deferred operation by pathlib on what its base renders
(`_render_deferred`). Then:
- **`parent`.** `PurePath.parent` keeps the path's drive and root, so a parent has its
  base's anchor.
- **`relative_to`.** Its result is built from the path's parts after the other path's,
  with no anchor, so it is relative (`""`).
- **`join`.** `p / q` is `q` where `q` is absolute, and otherwise `p` followed by `q`'s
  parts. So its anchors are the right side's absolute ones, together with the left
  side's where the right side may be relative.

**[Measured]** Checked over thirteen paths, including `/`, `//`, `/..`, `..` and `a/..`:
every parent keeps its anchor, and every successful `relative_to` is relative. #119's
pin, that `relative_to(Absolute, "/")` may meet a relative path, still holds: it is
relative.

## 2. A parent written out by its SubPath

**[Proven]** A parent is deferred when its base ends in a `SubPath`, which may render
no segment. Let the base be `H/q/{rel...}`, where `q` is the parts before the
`SubPath`.
- **`rel` renders segments `s₁ … sₖ`, with `k ≥ 1`.** The parent is `H/q/s₁/…/sₖ₋₁`:
  the base with a `SubPath` of `k − 1` segments in place of `rel`. A fresh `SubPath`
  renders exactly those, since `rel`'s segments are never `.` or `..`.
- **`rel` renders none.** The parent is the parent of `H/q`:
  - `H/q` less its last part, where that is a segment;
  - `H` itself, where `H` is `/`, `//` or `.`;
  - a deferred parent otherwise.

On every binding, the parent renders what one of the two renders, with the fresh
`SubPath` bound as above. Both keep the prefix `H/q`, which cancels against a sibling's,
so a "never" proved of every pair of cases holds of the expressions.

## 3. Tests and measurements

**[Measured]** `test_the_cases_of_a_parent_render_all_it_renders` checks that claim
itself, not a relation it implies. Over 200 generated parents and the pooled bindings,
every rendering is one of the cases' renderings under the same binding:
- 24,730 renderings in all;
- 6,479 of them explained only by the shorter case.

A mutant that drops the shorter case fails it. The same check for #122's case split
(`test_the_cases_of_a_changed_name_render_all_it_renders`) has 24,792 renderings, of
which 856 are explained only by the case with no suffix. Its mutant had survived the
relation tests, which reached the case only when no witness was found.

**[Measured]** The relation on #119's samples, #122 against this branch: 552
`"unknown"` became `"never"` below one deferred head, where `"unknown"` falls from 1,693
to 1,141 of 4,500 answers. The general and changed-names samples are unchanged.

**[Measured]** Mutants, each against `tests/relate_test.py` and `tests/overlap_test.py`
under seeds 0 and 1. All seven are killed:

| mutant | killed by |
|---|---|
| a parent anchors anywhere | `test_parents_relative_paths_and_joins_have_their_anchors` |
| a relative path anchored at `/` | the same, `test_different_anchors_never_meet`, and the property test below one deferred head |
| a join keeps its left side's anchor | `test_parents_relative_paths_and_joins_have_their_anchors` |
| a join takes its right side's anchor | the same |
| no shorter case | `test_the_cases_of_a_parent_render_all_it_renders` |
| the shorter case keeps the last segment | the same |
| the longer case keeps the whole `SubPath` | the same |

The three mutants of the cases are killed only by the invariant test, which checks the
cases themselves: the relation tests reach them only where no example is found, as with
#122's case split.

**[Measured]** The relate and overlap property suites pass under seeds 0 to 4, the
invariant tests among them.
