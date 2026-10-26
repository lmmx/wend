# 2026-10-26: Counting characters and segments in the oracle (#COUNTS)

#132 left 1,016 of `relate(shared=True)`'s `"never"` answers unconfirmed: the oracle
answered `"undecided"`. An unconfirmed answer is not wrong, but it is not independently
checked either. This entry adds a second argument to the oracle, independent of
`relate`'s, and sorts every answer by what was shown of it.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Definition]**.

## 1. What the answers mean where nothing renders

**[Definition]** For two expressions and a binding mode, let R be the set of bindings
under which both render. SEMANTICS §15.2:
- `"never"`: no binding in R relates them;
- `"always"`: every binding in R relates them.

Where R is empty, both are true. `relate` may answer either, and its `"always"` then
has no `Example`.

**[Definition]** The oracle claims more for its possible answers. `"sometimes"`,
`"possible"` and `"always"` each come with a binding in R that wend renders, showing the
relation. Its `"always"` says that R is not empty. Since #132 the oracle raises a
relation to `"always"` only after it has shown one, so where R is empty it answers
`"never"`, or `"undecided"`.

**[Definition]** When `relate` answers `"always"` and the oracle `"never"`, at most one is
wrong, and only if R is not empty. The bench (`bench/relate_oracle.py`, `vacuity`) sorts
such a pair three ways:
- **a contradiction**, when a pooled binding renders both. Whether that binding relates
  the two names which answer is wrong;
- **vacuous**, when the language of a side, read with each use of a name apart, is
  empty. It holds every rendering, so nothing renders that side, and R is empty;
- **unresolved**, otherwise: neither shown nor ruled out.

## 2. Counts

**[Proven]** Two uses of one name in one shape render one text, so they emit as many
characters. Uses that both render a path's segments (both heads, or both `SubPath`s)
also emit as many separators. Each edge of the intersection automaton records which
uses emitted its character, including characters an operation drops (#129). So a
binding that shows the relation is an accepting walk on which every such difference is
zero.

For a weighting `y` of the differences, each edge has a weight. If the least weight of
an accepting walk is positive, or the greatest is negative, no walk has every
difference zero, and the relation never holds. This is a Farkas certificate for the
integer program of the counts, with the connectivity of the walk relaxed. Relaxing only
widens what is feasible, so a certificate stays a proof.

The least weight is a shortest path (Bellman-Ford, by a queue: SPFA), and -∞ where a
negative cycle lies on an accepting walk. The automaton is trimmed first, so every cycle
does. A component whose internal edges weigh at most zero, one of them less, holds such
a cycle, and is found first.

The oracle tries each `y` in {-1, 0, 1}^m for up to four differences. Beyond that it
tries each difference alone, and the sums of each measure. `//{p}{q}` against
`//{p}-{q}` needs the sum: a binding gives `|p| + |q|` on the left and `|p| + 1 + |q|`
on the right, so on every walk the two differences add up to one.

**[Fact]** What counts are not compared:
- uses of a `bool` name, whose texts differ with each spec;
- separators between a field alone in a segment and a `SubPath`, which split one text
  differently;
- anything between different shapes, which a value may render apart (#130).

## 3. Results

RESULTS

## 4. Tests and mutants

**[Measured]** `tests/lang_oracle_test.py`:
- `test_counts_rule_out_what_no_candidate_settles`:
  - `//{p}{q}` against `//{p}-{q}`, both ways round;
  - `{x}/a` against `a/{x}`, both ways round;
  - two cases where counts must not answer `"never"`: two shapes of one name, and two
    names.
- `test_the_least_walk_has_no_bound_below_a_negative_cycle`: `_least_walk` on a hand-made
  automaton.
- `test_a_bool_used_twice_is_not_counted`: `{f:>5}` formats a `bool` as an int, `"    1"`,
  where `{f}` gives `"True"`.
- The property tests, which check every `"never"` against pooled renderings, run the
  counts wherever a witness is not found at once.

**[Measured]** Mutants, against `tests/lang_oracle_test.py` under seed 0:

| mutant | first run | now |
|---|---|---|
| characters an operation drops not counted | killed by the pooled-binding and agreement tests | the same |
| separators compared across a field and a `SubPath` | killed by the pooled-binding and agreement tests | the same |
| no counts at all | killed by `test_counts_rule_out_what_no_candidate_settles` | the same |
| a negative cycle ignored | survived | killed by `test_the_least_walk_has_no_bound_below_a_negative_cycle` |
| only one sign tried | survived | killed by the reversed cases of `test_counts_rule_out_what_no_candidate_settles` |
| a `bool`'s uses compared | survived | killed by `test_a_bool_used_twice_is_not_counted` |

The first two are the unsound ones. Each would answer `"never"` where a binding renders
the relation, and the pooled bindings, which share nothing with the counts, find it.
Of the three survivors:
- "one sign only" loses power, not soundness;
- "a negative cycle ignored" is unsound, but needs a long walk of positive weight beside
  a slightly negative cycle, which no generated pair had;
- "a `bool`'s uses compared" is reached only where substitution has not already
  decided the `bool`.

Each now has a direct test. The `bool` test's first version expected `{f:>5}` to render
`" True"`. The oracle answered `"never"` against that text, and rendering showed the
oracle right and the test wrong.

## 5. What is left

**[Measured]** The 145 answers left unconfirmed on this sample (138 `"never"`, 7
`"always"`; recorded by `record_bench.py`, which wraps the oracle without changing the
bench, so the pairs are the same):
- 138 relate a deferred operation (`with_stem`, `with_suffix`, `with_name`, `parent`,
  `relative_to`) of a base that ends in a `SubPath`, to the same base or a second
  operation of it. `relate` writes such a base out by how the `SubPath` splits, and
  pairs only cases where it splits alike on both sides (#127). The oracle reads each use
  of the `SubPath` apart, and ties the uses only by their counts, which do not say how
  the text splits. Typical: `with_suffix({sc...}/{sc...}, '.b')` is never strictly
  inside `{sc...}/{sc...}`.
- 7 others. Four are word equations that tie lengths across positions the counts do
  not align: `{root}/{q}/{c}/{q}` is never `/{c}/{p}-{q}/x.txt`, since `q` and `c`
  would both be `x.txt` and `c` also `p-x.txt`. Three hold the same name in two shapes
  (`{n}` and `{n:d}`), which the oracle keeps apart (#130).

**[Fact]** None of the 145 is known to be wrong. They are unconfirmed, not refuted: no
pooled binding contradicts them (the property tests and the bench check every answer
against renderings), and no other argument confirms them.

What would settle them:
- **Both uses of one `SubPath` read at once.** A product of the two operations'
  transducers over one copy of the base, rather than two copies tied by counts. This is
  the oracle's next step.
- **Counts per position.** Lengths tied between aligned segments, not only per name.
- **The oracle in `relate`.** #THOROUGH offers it as `relate(..., thorough=True)`,
  measured there. It needs the oracle kept a check: `relate`'s default never calls it.

**[Measured]** The out-of-memory bench. With the counts' first version (753a7a1), the
1,500-pair bench reached 13.7 GB and was killed by the kernel. The final version
(b2e3295) completed the same bench, under an 8 GB limit: the bench and its tests did not
change between the two, so Hypothesis drew the same pairs. Three probes, each relating
1,500 pairs of one sample with the first version, logged each pair; none ran out of
memory, but their pairs were drawn differently, since Hypothesis derives a derandomized
seed from the source of the function it runs.

**[Fact]** The cause is not established. Between the two versions only the least walk
changed: a queue (SPFA) for rounds over every state, and a test of each component's
cycles, which skips a walk where a cycle surely weighs less than zero. Both keep one
distance per state, so neither obviously bounds memory. Either a skipped walk was the
one that grew, or the killed run was not of exactly 753a7a1. The first version is being
rerun on the bench's own pairs, under a limit, logging each pair.
