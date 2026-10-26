# 2026-10-26: The oracle under shared bindings (#132)

#129 and #130 decide `relate(..., shared=False)`. `relate`'s default is
`shared=True`, where a name takes one value on both sides (SEMANTICS §15.1), and its
`"never"` answers there are the ones a pipeline relies on: two steps' paths that never
meet. Until now only pooled bindings checked them. This entry decides the shared case
with the same oracle: `relate_shared` in `src/wend/_experimental/lang_oracle.py`.

Labels: **[Fact]**, **[Measured]**, **[Proven]**.

## 1. A name of both sides, tied

**[Proven]** Under shared bindings a name of both sides renders one value on both. That
is #130's question for a name used twice, with the uses on two sides instead of one, so
the same procedure decides it:
- each use is read apart, so a `"never"` on the larger language is exact;
- a witness counts where each shape's uses agree, on both sides together, and is then
  one binding of both, which wend renders;
- otherwise each disagreeing (name, shape) is held to each text its uses can take, on
  both sides at once, and decided again.

**[Fact]** A name both sides give a default may also be unbound, and each side then
renders its own default (§15.1). `relate_shared` decides each such name both ways:
tied, and with each side bound to its own default. A relation holds never, or always,
where it does in every case, and is possible where it is in one.

## 2. A shared prefix cancels

**[Measured]** On #119's samples, 200 pairs each, the procedure of §1 alone leaves 418
of `relate`'s `"never"` answers undecided. Most are a shared prefix: `{ab}/a` against
`{ab}`, or `{root}/{p}.txt/b/x.txt` against `{root}/{p}.txt/b/../{sc...}`. Read apart,
the two `{ab}` render different texts and meet; the candidates for `ab` are infinite.

**[Proven]** Under shared bindings a piece equal on both sides renders one text on both
(SEMANTICS §15.3, 1), and a path's characters are its head's, then its parts'. In a
free monoid `uv = uw` exactly where `v = w`, and `uv` is `uw` followed by more exactly
where `v` is `w` followed by more. So where `a` and `b` share a head and leading parts,
they relate on every binding as what follows does. Every binding that renders `a` and
`b` renders what follows, since a part renders by itself. So a relation never (or
always) holding of what follows never (or always) holds of `a` and `b`.

`relate_shared` decides both and keeps the stronger answer. A witness for the whole,
rendered by wend, where what follows says `"never"`, would raise: none has.

## 3. Tests and measurements

**[Measured]** `bench/relate_oracle.py --shared` on #119's samples, 1,500 pairs each,
against `relate(shared=True)` as it was before #131. The oracle decides 4,423 of the
4,500 pairs (the 77 left out have a typed path parameter), 13,269 answers:

| | without cancellation | with it |
|---|---|---|
| contradictions | 0 | 0 |
| witnesses that fail to render | 0 | 0 |
| `relate`'s `"never"` left undecided | 3,296 | 802 |
| `"unknown"` settled as `"never"` | 219 | 238 |
| `"unknown"` settled as `"sometimes"` or `"possible"` | 724 | 724 |
| `"unknown"` left undecided | 470 | 451 |

Each run flags one pair, `with_stem(with_stem(//{n:d}.{p}/{p}, .), .)` against itself,
where `relate` answers `"always"` and the oracle `"never"`. Its language is empty, which
proves that nothing renders it (the stem `.` of `..y` is refused), and no pooled binding
does. Both answers hold vacuously (SEMANTICS §15.2); the bench now reports such pairs
apart.

**[Measured]** The same, against `relate(shared=True)` with #131's depth rule, which
turns 282 more `"unknown"` answers into `"never"`. #131 also changed the generators, so
the 4,419 pairs decided are drawn differently, and the two runs are not compared pair
by pair:
- **0 contradictions**, and no witness that fails to render;
- `relate`'s `"never"` left undecided: 1,016 (#131's depth arguments are counts, which
  the oracle does not make, §4);
- `"unknown"` settled: 124 as `"never"`, 169 as `"sometimes"`, 596 as `"possible"`,
  3 as `"always"`; 216 left undecided.

Three pairs over `with_stem({root}/x{p}/{p}{q}/{f}, .)`, with `f` a `bool`, are flagged
as before, and are vacuous for the same reason: `True` and `False` have no suffix, so
the stem `.` is refused. The language with each use read apart, which holds every
rendering, is empty. The bench now asks that language, which also covers names used
twice.

**[Measured]** Found while measuring: `relate_shared(e, e)` for an `e` that renders
nowhere answered `"always"` with no example, since cancellation leaves `"."` against
`"."`, which is always the same. Every possible answer must come with bindings.
`test_every_possible_shared_relation_renders` failed on it under seed 0, and so did the
bench. Now `"always"` is raised only from an answer a binding has shown.
`test_shared_bindings_tie_a_name_across_sides` holds the case.

**[Measured]** The oracle's tests, with the three property tests for shared bindings,
pass under seeds 0 to 4.

**[Measured]** Mutants, against the shared tests in `tests/lang_oracle_test.py` under
seed 0:

| mutant | killed by |
|---|---|
| no name tied across sides | all four shared tests |
| defaults not split | `test_shared_bindings_tie_a_name_across_sides` |
| different heads cancelled | all four, the pooled-binding test among them |
| unequal parts cancelled | all four, the pooled-binding test among them |
| a `"never"` in one case taken for all | `test_shared_bindings_tie_a_name_across_sides` |
| `"always"` after the prefix over the whole's answer | `test_every_possible_shared_relation_renders`, `test_shared_bindings_tie_a_name_across_sides` |

The first four ran before the fix above, the last two after it. Where a test that killed
one of the first four reads the examples, its failure could be the bug's, so the table
counts only the other tests.

## 4. Next

**[Measured]** On a sample of 60 pairs per sample, cancellation leaves 21 of `relate`'s
`"never"` answers undecided, against 143 without it. They are of three kinds:
- **An equation inside a segment.** `//{p}{q}` against `//{p}-{q}` asks whether
  `pq = p-q` for one `p` and one `q`: never, since the two sides differ in length by
  one. A count of characters per tied name settles it: one linear equation per tied
  (name, shape) over the Parikh image of the intersection, which an integer program
  decides.
- **A deferred head on one side only.** `with_suffix({ab}/a/{sc...}, "")` against
  `{ab}/a/{sc...}`: the heads differ, so nothing cancels, though the change of a suffix
  keeps the parent. Cancellation could run inside a deferred operation that keeps its
  base's parent (changed names), as `relate`'s views do.
- **Two deferred heads of one base.** `parent(x)/..` against `with_name(x, "x.txt")/..`:
  both rewrite the same base, at its last segment.

The first is the general one: under shared bindings the question is a word equation
with regular constraints, decidable (Makanin; Plandowski; Jeż) but not cheaply in
general. Counting characters and segments is the cheap, sound half of it.
