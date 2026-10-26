# 2026-10-26: The oracle behind `relate(..., thorough=True)` (#THOROUGH)

#129 to #135 built an oracle for `relate`, kept out of the wheel in
`wend._experimental`, to check `relate` against. On #119's samples it decides most of
what `relate` leaves `"unknown"`. This entry makes it available to users, as an option,
and keeps it able to check `relate`.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Definition]**.

## 1. What `thorough` does

**[Definition]** `relate(a, b, thorough=True)` first answers by its rules (SEMANTICS
§15.3, 1 to 6). Each relation the rules leave `"unknown"` or `"sometimes"` is then asked
of `wend._languages`, the oracle moved out of `wend._experimental`, and its answer is
taken:
- `"never"`: as it is, a proof. The oracle reads a name used twice as two uses apart, so
  its language holds every rendering, and more.
- `"sometimes"`, `"possible"` or `"always"`: only once wend renders the oracle's binding
  and shows the relation. Then `"always"` where the oracle says so, else `"sometimes"`,
  with the binding as the `Example`.
- `"undecided"`, out of budget, or outside the fragment: the rules' answer.

So an answer only refines the rules': an `"always"` or `"never"` is kept, and a
`"sometimes"` may become `"always"`.

**[Definition]** Values. The oracle's binding gives each name a value that renders the
text each of its uses needs. Where one `str` renders all of them, the binding uses the
`str` (`plainly`). Otherwise it uses a value of a type wend makes: an object whose
`__fspath__` and `__format__` give the texts, and which compares equal to a choice where
`choices` are declared. Both are bindings wend accepts; the second is the "values of
types of their own" of SEMANTICS §15.3, 1. Under `builtin_values=True`, a binding counts
only if every value is of a builtin type.

`EffectGraph(..., thorough=True)` relates its ports so.

## 2. Keeping the oracle a check

**[Fact]** `relate`'s default is unchanged, and never calls the oracle. So
`bench/relate_oracle.py`, which compares `relate`'s answers with the oracle's, still
compares two procedures that share no reasoning. The oracle's own tests still check it
against pooled renderings, which share nothing with either.

**[Fact]** What checks `thorough` itself, not through the oracle:
- `test_thorough_refines_the_rules_and_holds_for_pooled_bindings`: every answer refines
  the rules', every example renders, and every `"always"` and `"never"` holds for every
  pooled binding (of builtin values, so in all four modes);
- `bench/relate_thorough.py`: the same refinement, and every example rendered, over
  #119's samples.

## 3. A budget of steps

**[Definition]** SEMANTICS §15.2: answers are a function of the expressions and options.
A time limit would break that, so the budget counts steps: states made, edges built and
followed, closures taken. `relate` gives each pair 5,000,000. Past it the oracle raises
`Exhausted`, an `Unsupported`, and the rules' answer stands.

**[Proven]** Exhaustion must not be read as an answer. Four handlers in the oracle catch
`Exception`: around a constant's formatting, a value's formatting, a value's
construction, and a binding's rendering. None encloses work that spends: the one around a constant's formatting enclosed building its text, and now
builds it outside. (A constant field always has a dynamic spec in normal form, so the
oracle refuses it before then: the old order was unreachable too.)

**[Measured]** `test_an_exhausted_budget_is_never_an_answer` runs the oracle on four
pairs under every budget from 0 up to the first that suffices, in both modes: each run
answers as with no budget, or raises `Exhausted`.

## 4. Where the time went

**[Measured]** On 300 pairs of each sample, the oracle's time on the pairs `relate` left
`"unknown"` or `"sometimes"` was dominated by one pair: 54 s. A profile put 84% of it in
`compact`'s epsilon closures, called from `_projection`, which enumerates the texts one
use emits. `_projection` hides every edge but that use's, so most edges are epsilon, and
closing each state is quadratic.

`_projection` now trims the automaton (linear) and closes only the states the
enumeration reaches: the start, and the targets of the use's own labels. It enumerates
the same texts.

| | before | after |
|---|---|---|
| the slowest pair | 174.6 s (54 s unloaded) | 7.9 s |
| 301 pairs, total | 170.5 s | 29.4 s |
| 301 pairs, slowest | 54.2 s | 3.5 s |
| answers that differ | | 0 of 301 |

**[Measured]** `bench/relate_oracle.py --shared 1500`, #135's bench of the oracle against
`relate`, on all 4,500 pairs: every count it reports is identical before and after, and
it took 347 s, against 3,348 s for #135's version (on a machine running about eight other
jobs) and 1,845 s for #132's (idle). This run shared the machine with the full suite and
the seeds, three jobs on four cores.

**[Measured]** Steps on those pairs, after: median 15,794; 95th percentile 875,472;
99th 2,543,766; greatest 5,124,312. At 5,000,000, one pair runs out, and none of the
relations it settles is lost (it settles none the rules left `"unknown"`).

## 5. Results

**[Measured]** `bench/relate_thorough.py 1500` on #119's three samples, 1,500 pairs each,
in each of the four modes. In every mode:
- no answer fails to refine the rules';
- every example renders and shows its relation.

What the rules left `"unknown"`, and what `thorough` made of it (all three relations,
summed over the samples):

| mode | `"unknown"` | → `"never"` | → `"sometimes"` | → `"always"` | still `"unknown"` |
|---|---|---|---|---|---|
| shared | 1,210 | 244 | 751 | 2 | 213 |
| shared, builtin values | 954 | 226 | 215 | 0 | 513 |
| independent | 3,573 | 331 | 2,987 | 2 | 253 |
| independent, builtin values | 3,093 | 304 | 842 | 0 | 1,947 |

A `"sometimes"` became `"always"` once in each mode, twice independent with builtin
values. Under shared bindings `thorough` settles 82% of the unknowns. With builtin values
it settles less, because most of the oracle's witnesses bind a value of a type of its own:
1,241 of the under-one-head sample's independent examples did. Its `"never"`s carry over
whole, its witnesses only where plain.

**[Measured]** Cost, the whole bench (rules then `thorough`, 4,500 pairs a mode), on a
4-core machine running about eight other jobs, so the times are high:

| mode | rules | with `thorough` | pairs over 2 s | budget run out |
|---|---|---|---|---|
| shared | 19.4 s | 243.1 s | 22 | 5 |
| shared, builtin values | 16.9 s | 189.1 s | 17 | 3 |
| independent | 139.2 s | 467.7 s | 34 | 1 |
| independent, builtin values | 128.6 s | 441.8 s | 32 | 1 |

Under shared bindings that is 54 ms a pair on average with `thorough`, against 4 ms
without; under-one-head pairs cost most.

## 6. Mutants

**[Measured]** Mutants, against `tests/relate_test.py -k thorough` for `relate` and
`tests/lang_oracle_test.py` for the oracle, under seed 0, each run on this branch's code:

| mutant | killed by |
|---|---|
| the oracle's `"never"` ignored | `test_thorough_settles_what_the_rules_leave_unknown` |
| `"possible"` taken as `"always"` | that, `test_thorough_counts_only_builtin_values_where_assumed`, and the pooled property test |
| the `builtin_values` filter dropped | `test_thorough_refines_the_rules_and_holds_for_pooled_bindings` |
| the oracle's binding not rendered | the three above |
| the budget never spent | `test_thorough_within_its_budget_or_not_at_all` |
| `_projection` reading finals of the state alone, not of its closure | the shared pooled-binding and agreement tests |
| `_projection` reading labels of the state alone | six tests, the pooled-binding ones among them |
| a constant's text built inside its handler | survived: unreachable, as §3 says |
| an exhaustion inside the counts caught and dropped | survived: equivalent on every input tried |

**[Measured]** The last survivor was probed, not assumed. With the drop instrumented, the
oracle ran on two tied pairs, in `_relate` and `relate_shared`, under every budget up to
the first that suffices: 1,538 exhaustions were dropped, and each one raised again before
an answer. Out of budget, every later step raises, and in each case tried the oracle
did more work after the counts. That is not shown in general: a relation decided last,
with no disagreeing name to substitute, could return straight after them. The guard is
the code having no such handler;
`test_an_exhausted_budget_is_never_an_answer` would catch one that changed an answer.

## 7. What is left

- **What `thorough` leaves.** 213 unknowns under shared bindings, mostly word equations
  the counts cannot settle (§5 of the counting entry), and 1,947 independent with
  builtin values, where a witness needs a plain value the oracle does not look for: it
  makes up a value per text, and only then tries a `str`. Searching the oracle's
  language for a word whose texts a builtin value renders would close much of the
  second.
- **Examples of values of wend's making.** Correct, and accepted by wend, but they read
  oddly: a value whose `__fspath__` and `__format__` differ. `Example` could say so.
- **The cost.** Mostly the under-one-head sample's deferred heads, read as automata of
  some thousands of states. A cache of each expression's language, across the pairs of
  an `EffectGraph`, would save the most, since a graph relates each port many times.
- **`EffectGraph` measured.** `bench/effects_corpus.py` has not been run with
  `thorough=True`.

## 8. #135's out-of-memory bench, rerun

**[Measured]** #135's first version (753a7a1) was rerun on the bench's own pairs
(`bench/relate_oracle.py --shared`, unchanged, with the oracle wrapped to log each pair
and the peak resident memory before relating it), under an 8 GB limit. Twice the
container was reclaimed while idle and the run lost; the longer run related 3,574 pairs,
all of the first two samples and 574 of the third, and peaked at 124 MB. The bench killed
at 13.7 GB was, as far as the record shows, this code on these pairs.

**[Fact]** So the culprit, if this version had one, lies in the last 926 pairs of the
under-one-head sample, which neither rerun reached. It is not established. The final
version of the counts completed all 4,500 under the same limit, and this PR's projection
makes the oracle's slowest step linear; the question is left there.
