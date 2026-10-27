# 2026-10-26: The oracle for builtin values, and an intersection that ran out of memory (#BUILTIN)

`relate(..., builtin_values=True)` (#125) proves more `"never"`s than the default,
assuming bound values are of builtin types. Until now nothing independent checked those
answers: the oracle read every value as possibly of a type of its own. This entry gives
the oracle a builtin mode, and uses it twice: to check `relate`'s builtin answers, and
behind `relate(..., builtin_values=True, thorough=True)`. Running that check found a
defect in `relate` itself, on master: an intersection that ran out of memory.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Definition]**.

## 1. What builtin values change

**[Proven]** For a value `v` of a builtin type (`str`, `int`, `float`, `bool`, a
`PurePath`, `None`, `complex`: every value in the tests' pool), a field alone in a
segment renders `os.fspath(v)` for a `str` or path and `format(v, "")` otherwise, and a
plain field in text (no spec; no conversion, or `!s`) renders `format(v, "")`. All of
these are `str(v)`. So the two render one text, and the oracle reads them as one shape,
`PLAIN`, of one name: two uses tied as #130 ties a name's uses in one shape.

**[Proven]** A head parameter or a `SubPath` is not tied to text. The value `.` renders
no character as a head, and one in text; tied, the counts (#135) would rule out
`{x}/{x}.txt` rendering `..txt`, which it does where `x` is `.`.
`test_builtin_values_keep_a_head_apart_from_text` holds it.

**[Proven]** A spec or `!r` renders otherwise (`"07"` for 7, `"'a'"` for `"a"`), so those
stay apart. Tied, `d/{n:02d}` could never be `d/0{n}`, which it is for 7.
`test_builtin_values_keep_specs_and_repr_apart` holds both.

**[Proven]** A field of a name typed `int`, with no spec or a plain width (`d`, `03d`,
`3d`: the specs `0?[0-9]*d?`), renders spaces of padding, a sign and digits, and, with
no spec, `True` or `False` (a `bool` is an `int`). The oracle holds such a field to
those texts. Other specs (`+d`, `x`, `,d`, ...) are left as any text.
`test_a_builtin_int_formats_within_its_language` checks every width against ints from
`-100` to `10**20` and both bools.

**[Definition]** In builtin mode the oracle's possible answers need a binding of
builtin values: a value of its own making that renders one text becomes that text, as
the `int` or `float` it spells where its name is so typed, and wend must render the
binding. Its `"never"` is over builtin bindings alone.

## 2. Checking `relate`'s builtin answers

**[Measured]** `bench/relate_oracle.py --builtin` (new), on #119's samples, the same
pairs as without (the mode is bound outside the function whose source sets the pairs):

| mode | `relate` `"never"`, confirmed | unconfirmed | `"always"` unconfirmed | contradicted | witnesses failing |
|---|---|---|---|---|---|
| shared | 9,565 | 138 | 7 | 0 | 0 |
| shared, builtin | 9,708 | 335 | 123 | 0 | 0 |
| independent | 6,278 | 1 | 0 | 0 | 0 |
| independent, builtin | 6,406 | 296 | 18 | 0 | 0 |

So 96.7% of `relate`'s shared builtin `"never"`s are now confirmed by an argument that
shares nothing with its own, and none is contradicted. The property tests check the
builtin mode itself against pooled bindings, whose values are builtin, in both modes.

**[Measured]** The `int` narrowing came from this measurement. Without it, the shared
builtin column left 473 `"always"`s and 452 `"never"`s unconfirmed. The oracle's shortest
witness gave an `int` field the text `""`, which no `int` renders, so no witness held.
With it: 123 and 335.

## 3. `relate` ran out of memory

**[Measured]** The independent builtin run of the bench died with `MemoryError` inside
`relate`, not the oracle. On master (87b69ec), under a 6 GB limit:

`with_stem({ab}/{n:02d}/{n:02d}/x{p}, a)/{n:02d}/{n:02d}/x{p}` against
`{ab}/{n:02d}/{n:02d}/{q}.txt/{n:02d}/{n:02d}/x{p}/{n:02d}/{n:02d}/x{p}`, with
`shared=False, builtin_values=True`: `MemoryError` after 99 s. Without
`builtin_values`, 30 s.

**[Proven]** The cause: `_overlap.intersect_all`. An alignment of two shapes holds some
segments equal (here eleven uses of `{n:02d}` and their counterparts), and their text
must lie in every one of their languages. The search ran over the product of all of
them at once, sixteen automata of three to ten states, and queued every combination of
their edges before checking whether a state was seen. Where the intersection is empty
it explores the whole product.

**[Measured]** The fix, in three parts:
- a language met twice is met once (its automaton's identity is the key: `Lang`'s own
  equality ignores the automaton);
- the languages are met two at a time, smallest first, each product trimmed to the
  states reachable from the start and able to reach the end (`_meet`);
- a product past 100,000 states raises `TooHard`, and that alignment is then decided
  neither way: it cannot give a NO.

On the pair: 4.5 s and 71 MB, `same` `"never"` as before. Without `builtin_values`,
1.8 s, against 30 s. `test_many_equal_segments_relate_in_bounded_memory` runs it, and
on master fails with `MemoryError` under a 4 GB limit.

**[Measured]** No other answer changed. `relate` on #119's samples, all four modes,
4,500 pairs, master against this branch: all 18,000 answers identical, in 371 s
against 622 s, peaking at 156 MB against 711 MB.

## 4. `thorough` with builtin values

**[Measured]** `bench/relate_thorough.py 1500`, master (87b69ec) against this branch, on
the same pairs (the bench file is master's): what `thorough` makes of the relations the
rules leave `"unknown"`, summed over the three samples.

| mode | `"unknown"` | → never | → sometimes | → always | left |
|---|---|---|---|---|---|
| shared, builtin, master | 900 | 180 | 155 | 2 | 563 |
| shared, builtin, now | 900 | 216 | 261 | 2 | 421 |
| independent, builtin, master | 2,941 | 263 | 838 | 2 | 1,838 |
| independent, builtin, now | 2,941 | 299 | 1,392 | 2 | 1,248 |

Without builtin values every count is as on master. In every mode no answer fails to
refine the rules', and every example renders. Independent with builtin values, the cost
rose with what is settled: 587 s against 458 s for the 4,500 pairs, 48 pairs over 2 s
against 26.

(A first `thorough` run of this branch drew other pairs: `ruff format` had changed the
bench function's source since #136's run, and Hypothesis seeds its draws from that
source. Its counts are not comparable with #136's, and are not used.)

## 5. Tests and mutants

**[Measured]** Mutants, each run on this branch's final code, all killed:

| mutant | killed by |
|---|---|
| a head read as `PLAIN` too | `test_builtin_values_keep_a_head_apart_from_text`, and the tie test |
| any spec merged into `PLAIN` | `test_builtin_values_keep_specs_and_repr_apart` |
| `!r` merged into `PLAIN` | the same |
| witnesses not of builtin values | `test_builtin_answers_hold_for_pooled_bindings` |
| an `int` left a `str` | `test_builtin_values_tie_a_field_alone_to_the_same_field_in_text` |
| a segment's field not `PLAIN` | the same |
| an `int` with no spec never a `bool` | `test_a_builtin_int_formats_within_its_language` |
| an `int` with no padding | the same |
| `TooHard` read as a NO | `test_an_intersection_too_hard_rules_nothing_out` |
| languages deduplicated by equality | `test_many_languages_meet_two_at_a_time` |
| no bound on states | the same, and the memory regression |
| one side's excludes dropped | `test_many_languages_meet_two_at_a_time` |
| one side's epsilon moves dropped | the same, and two property tests |

**[Fact]** Three survived a first run, and the tests that kill them were written after
it:
- "any spec merged" and "`!r` merged" survived, since no generated pair holds a spec
  that differs from the plain text where it matters, nor `!r`. The test's first version
  checked only that neither relation was `"always"` or `"never"` on pairs where merging
  merely loses precision. Merging is unsound only where it ties texts that differ:
  `d/{n:02d}` against `d/0{n}`, `d/{p!r}` against `d/'{p}'`. Those pairs kill both.
- "one side's excludes dropped" survived: no case met a language that excludes `.` with
  one that does not. A direct case kills it.

## 6. What is left

- **Unconfirmed builtin answers.** 335 `"never"`s and 123 `"always"`s under shared
  bindings, 296 and 18 independent. Not examined one by one. Fields of a name typed
  `float`, and `int` fields under other specs, are still read as any text, so their
  witnesses fail where a plain value is needed.
- **The bound on a product.** On #119's samples, in all four modes, `_meet` built 103,523
  products, the largest 27,663 states, and 25 passed 100,000: three pairs, independent
  with builtin values, such as `with_suffix(//{n:02d}/{n:02d}/{s...}, '.b')/{f}/{n:02d}`
  against the same head followed by `{f}/{n:02d}/{n:02d}/{n:02d}`. On each, the answer is
  master's (`same` never, `inside` unknown, `contains` sometimes), in 2 to 3 s and 71 MB,
  where master took 12 to 507 s and up to 3.1 GB. A first draft of this entry said the
  bound was never reached; measuring showed otherwise.
- **The rest of the overlap analysis.** `intersect`, for two languages, still queues
  every pair of edges before checking a state; it was not the cause here, and was left.
