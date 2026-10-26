# 2026-10-26: The oracle behind `relate(..., thorough=True)` (#THOROUGH)

#129 to #COUNTS built an oracle for `relate`, kept out of the wheel in
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

**[Measured]** Steps on those pairs, after: median 15,794; 95th percentile 875,472;
99th 2,543,766; greatest 5,124,312. At 5,000,000, one pair runs out, and none of the
relations it settles is lost (it settles none the rules left `"unknown"`).

## 5. Results

RESULTS

## 6. Mutants

MUTANTS

## 7. What is left

LEFT
