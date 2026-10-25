# 2026-10-25: Answers that do not depend on string hashing (#126)

Comparing #125 against master, two answers were lost: `"sometimes"` became
`"unknown"`. Neither was caused by #125. Each pair gave either answer on master too,
depending on `PYTHONHASHSEED`. This entry records why, and what fixes it. The contract
is `docs/SEMANTICS.md` §15.2.

## 1. Where the hash came in

**[Measured]** `/{c}.txt/{p}{q}` against `/{c}.txt/{c}.txt/{p}{q}`, with
`c = Param("c", choices={"a", "b", "x.txt"})`: `contains` is `"sometimes"` under hash
seed 1 and `"unknown"` under seeds 0, 2 and 3, on master and on #125 alike. The overlap
analysis returned YES with a witness under one seed and MAYBE under the others.

**[Fact]** Two places made the search for an example follow string hashing:
- **A parameter's `choices`** are a `frozenset`, and `_overlap._domain` listed them in
  its iteration order, which for strings follows their hashes. The samples tried for a
  witness come from that list, and the search tries a bounded number of them.
- **The names of a view's text and of a parent's `SubPath`** (#119, #123) were
  `_name_` and `_rest_` followed by `hash()` of the operation's key (with its names'
  defaults, since #124). The search sorts
  parameters by name, so the order of the names changed which bindings it tried first.

Neither touches a proof. Every `"never"` and `"always"` is proved by structure or by
the overlap analysis's NO, and neither depends on the order of samples. What changed
was whether the bounded search found an example before giving up: `"sometimes"` or
`"unknown"`.

## 2. The fix

- `_domain` sorts choices by type name, then `repr`.
- A `Memo` names each view's text and each parent's `SubPath` by a counter: one name
  per operation, numbered in the order first asked. The order of the calls is fixed,
  so the names are too. Two operations of different keys also never share a name,
  which `hash()` could not promise: equal hashes would have tied two texts that
  differ.

## 3. A name wend makes up never takes one of the expressions'

**[Proven]** A view's text stands for text the operation fixes, and is not any
parameter of the expressions. Were it to share a name with a parameter of the other
side, shared bindings would tie the two. Take `({root}/{x}).with_suffix(".csv")`,
whose view is `{root}/{_name_0}.csv`, against `{root}/{_name_0}.csv` built from a
user's parameter named `_name_0`. They would be the same expression, and the relation
would read `"always"`. Yet `x="f"` and `_name_0="g"` render `r/f.csv` and `r/g.csv`.

The hash-derived names made such a clash unlikely, but did not rule it out: a
parameter may have any name. A counter's names are easier to hit, so the fix rules the
clash out:
- the memo *reserves* every parameter name of the expressions it serves, and never
  gives a reserved name;
- `Analysis` reserves the names of the two expressions;
- `EffectGraph` reserves those of every port and of every path given as existing,
  before it builds a view, since it builds views itself to find the directory two
  paths share.

A memo asked to reserve a name it has already given raises, rather than answer wrongly.

## 4. Tests and measurements

**[Measured]** `test_answers_do_not_depend_on_string_hashing` runs four pairs, the
two of §1 among them, in subprocesses under hash seeds 0 to 3, and requires the same
output, examples included. It fails on #125 and passes here.
`test_a_view_never_takes_a_name_of_the_expressions` holds the clash of §3, and
`test_a_graph_never_names_a_view_after_one_of_its_parameters` holds a graph in which
one step's view is named before another step's parameter of that name is reached.

**[Measured]** Mutants, against `tests/relate_test.py` (then `tests/overlap_test.py`
and `tests/effects_test.py` where needed), under seeds 0 and 1:

| mutant | killed by |
|---|---|
| choices in set order | `test_answers_do_not_depend_on_string_hashing` |
| relate reserves nothing | `test_a_view_never_takes_a_name_of_the_expressions` |
| the graph reserves nothing | `test_a_graph_never_names_a_view_after_one_of_its_parameters`, once its graph had a third step: with two, each `Analysis` reserved its pair's names before the graph named a view |
| a reserved name may be given | `test_a_view_never_takes_a_name_of_the_expressions` |
| a clash is not refused | survived: unreachable. Every user of a memo reserves its names before any is given, so the refusal is a guard against a later caller that does not |

**[Measured]** The relation on #119's samples, #125 under hash seeds 0 and 1 against
this branch: no answer changed. Those samples happen to hold no pair whose answer
moves with the seed, which is why the test above names its pairs.

**[Measured]** The property suites (relate, overlap, effects and families) pass under
seeds 0 to 4.
