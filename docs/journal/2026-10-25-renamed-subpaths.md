# 2026-10-25: Names changed below a SubPath, written out (#127)

After #126, most of the answers `relate` leaves `"unknown"` on #119's samples have no
witness in the test pool: most are gaps in the proofs, not in the search for an
example. The largest group of them that follows one pattern is a name changed by
`with_name`, `with_suffix` or `with_stem` while its base ends in a `SubPath`:
`(data/{sc...}).with_suffix(".b")`. Such a change has no view (#119): the name it
changes is the `SubPath`'s last segment, which may not exist. This entry writes the
change out by cases, as #123 wrote out a parent. The contract is `docs/SEMANTICS.md`
§15.3 (3).

## 1. Where the unknowns are

**[Measured]** For every `"unknown"` under shared bindings in #119's three samples
(1,500 pairs each), each sample's pooled bindings were tried for a witness:

| sample | unknown answers | with a witness in the pool |
|---|---|---|
| general | 419 | 35 |
| changed names | 628 | 31 |
| below one deferred head | 1,189 | 62 |

The rest, 92% to 95% of each, have no witness among the pooled bindings, so most of
them are gaps in the proofs rather than in the search: a pooled binding is no proof of
"never", but the search tries fewer bindings than the pool. The classification ran on
#125 and #126 together, before this change. Their largest classes are the overlap
analysis's MAYBE on changes of a `SubPath`-ended base, and stems of `.` and `..`,
which have no view. This entry takes the first.

## 2. The cases, and why they are sound

**[Proven]** Let a name operation `op` change `H/q/{rel...}`, where `q` is the parts
before the `SubPath`.
- **`rel` renders segments `s₁ … sₖ`, with `k ≥ 1`.** The base renders the same
  string as `H/q/{rest...}/{seg}`, with `rest` bound to `s₁ … sₖ₋₁` and `seg` to `sₖ`.
  `seg` is a segment-valued parameter, and `sₖ` is never `""`, `.` or `..`, so it
  accepts it. The same pathlib operation on the same string gives the same result. So
  `e` renders what `op(H/q/{rest...}/{seg})` renders, and that change has a view,
  since its base ends in a segment.
- **`rel` renders none.** The base renders `H/q`, and `e` renders `op(H/q)`. Where
  pathlib refuses that (`op` of `/`, say), `e` renders nothing on such bindings, and
  the case is dropped.

Each case is built with the public operation, as wend builds it, so a change of a
known name is made at once rather than deferred.

**[Proven]** `rest` and `seg` are named from the base's fresh key (#124): its
structure, and its names' defaults. So a parent and a changed name of one base, on one
side or on two, split it with the same parameters. Under shared bindings two bases with
equal fresh keys render one text, so their `SubPath`s render the same number of
segments, and the same case holds on both sides. Two refinements follow:
- **Correlated cases.** Where both sides are split on bases of equal fresh key, only
  the cases where the `SubPath` renders alike are paired: longer with longer, shorter
  with shorter. The other pairs describe no binding under which both render.
- **A plain side split alike.** A path that begins with the base, by fresh key, is
  split by the same two cases. Under shared bindings it renders `H/q/s₁/…/sₖ/tail`, or
  `H/q/tail`, exactly as the cases spell it.

Under independent bindings neither refinement applies, and the cases of one side are
paired with every case of the other.

## 3. Tests and measurements

**[Measured]** `test_the_cases_of_a_renamed_subpath_render_all_it_renders` checks
the cases themselves. Over 200 generated changes and the pooled bindings, every
rendering is one of the cases' renderings under the same binding, with `rest` and `seg`
bound to the `SubPath`'s value less its last segment, and that segment. There are
16,859 renderings: 12,526 explained only by the longer case, and 4,333 only by the
shorter.

**[Measured]** `test_a_name_changed_below_a_subpath_is_written_out` holds the
examples above. It also shows that under independent bindings nothing is proved, and
that a parent and a change of one base share the split.

**[Measured]** The fuzzer of #124 finds no unsound answer in 30,000 checks, under two
seeds. Its bases end in a name defaulted differently on each side, changed by a parent
or a name operation.

**[Measured]** `test_names_changed_below_two_subpaths_hold_for_pooled_bindings`
draws two parents or changed names of bases ending in two different `SubPath`s, and
checks every `"always"` and `"never"` against their pooled bindings. Their branches
are independent, so no pair of cases may be skipped.

**[Measured]** Mutants, against `tests/relate_test.py` (then `tests/overlap_test.py`
and `tests/effects_test.py` where needed), under seeds 0 and 1:

| mutant | killed by |
|---|---|
| no shorter case of a changed name | `test_a_name_changed_below_a_subpath_is_written_out`, the invariant test |
| no longer case of a changed name | the same, and three property tests |
| the segment named as the rest | seven tests |
| a plain side split whatever it begins with | `test_names_defaulted_apart_hold_bound_and_unbound` |
| branches paired across two bases | `test_a_name_changed_below_a_subpath_is_written_out`, once it held `with_suffix(x/{r1...}, ".b")/../a` against `with_stem(data/{r2...}, "x")/x.b`. That case was found by fuzzing the mutant: it answered `"never"` for `inside`, though `r1="x"` and `r2` empty render `x/x.b/../a` and `x/x.b`. The property test over two SubPaths does not reliably reach it |
| branches paired under independent bindings | survived. Under independent bindings each side's `rest` is free, and the longer cases' pair covers what a crossed pair would show: a fuzzer of 1,500 pairs over one base, bound apart, found no answer the mutant changes. The guard stays, since the argument for pairing by branch needs shared bindings |

**[Measured]** The relation on #119's samples, #126 against this branch with the same
`PYTHONHASHSEED`: 10, 43 and 235 `"unknown"` became `"never"` in the general,
changed-names and below-one-head samples. No other answer changed. Of these, the
correlated cases alone give 154: without them the change gives 134.

**[Measured]** The property suites (relate, overlap, effects and families) pass under
seeds 0 to 4.
