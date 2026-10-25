# 2026-10-25: A more precise relation: anchors, depth, and names changed by binding (#119)

> **Correction, #120.** §2's view of a changed name is revised in place, with its earlier
> wording kept beside it, marked *Before*: a stem of `.` or `..` can make the name `..`.
>
> **Correction, #124.** §2's naming of a view's text is revised in place, with its
> earlier wording marked *Before*: two sides that give a name different defaults do not
> render one text (`2026-10-25-defaults-in-views.md`).

After #118, `wend.relate` answered `"unknown"` for about one question in six over the
property tests' pairs, and for one in four over names changed with `with_suffix`,
`with_stem` and `with_name`. An `"unknown"` is safe, since every query counts it as a
possible link. But it costs the graph ordering and parallelism it could have, and it
leaves the must, may and disjoint question open. This entry records three rules that
prove more answers, how each was checked, and the one rule that was wrong at first.
The contract is `docs/SEMANTICS.md` §15.3, steps 2, 3 and 5.

## 1. Where the unknowns came from

**[Measured]** I traced every `"unknown"` over 1,500 of the property tests' pairs, under
shared bindings, to its cause in `Analysis._overlap`:

| cause | same | inside | contains |
|---|---|---|---|
| the overlap engine's MAYBE (coarse shapes) | 77 | 68 | 100 |
| the `..` guard (§15.3) | 0 | 82 | 100 |
| a YES no binding of the expressions confirmed | 3 | 9 | 11 |

Two of these were structure the relation did not use.
- **Anchors.** `.` against `/` reached the engine, and the engine's "strictly below"
  construction made `{_inside}` a head parameter for an empty relative path, which can
  render `/`. Its YES was never confirmed, so the answer was `"unknown"`, where the two
  never meet.
- **Depth.** `{root}/raw/{day}.csv` against `{root}/{other}/{day}.parquet` asked the
  engine about nesting, though both render exactly three segments.

**[Measured]** On the same sample, an anchor rule would settle 66 unknowns in each mode,
and a depth rule 44 more.

## 2. The rules

**[Fact]** A segment renders exactly one segment. wend rejects `""`, `.` and a separator
in any segment's rendering (`InvalidBindingError`), and a literal `.` is dropped when
the expression is built. A literal `..` is one segment when paths are compared as strings
(`PurePosixPath` keeps it). That is what both rules rest on.

**[Proven]**, relative to that fact and to §15.3 (1):
1. **Anchors.**
   - A relative head renders the anchor `""`, and a root head its anchor.
   - An `Absolute` parameter renders `/` or `//`, since `PurePosixPath("//x")` keeps
     `//`.
   - A changed name keeps its base's anchor.

   `lexically` compares anchors first, so disjoint anchor sets prove `"never"` for all
   three questions, in both modes.
2. **Depth.** After prefix cancellation, remainders made only of segments render `n` and
   `m` segments. "Same" needs `n = m`, "inside" `n > m`, "contains" `n < m`.

**[Fact]** **Views of changed names.** When the name is not known until binding,
`with_suffix`, `with_stem` and `with_name` are deferred: wend builds them structurally
only where it can (`_suffix_split`). The relation now sees each as its base's parent and
one segment (`_view`):
- the new name, for `with_name`;
- text, then the suffix, for `with_suffix`;
- the stem, then text, for `with_stem`.

The text's parameter is named from the operation's render key and its names' defaults,
so one operation viewed twice is alike where it renders one text, and `relate(e, e)` is
`"same always"` for a deferred `e`. Under shared bindings two sides render one text
where the operation's structure is equal and so is each name's default. A name
defaulted differently on each side renders each side's own default when unbound.

> *Before:* "The text's parameter is named from the operation's render key, so one
> operation viewed twice is alike, and `relate(e, e)` is `"same always"` for a deferred
> `e`." The render key leaves defaults out, so the text was tied across two sides that
> render different texts. `(data/{x}).with_suffix(".q")/y` with `x` defaulted `a` on one
> side and `b` on the other was `"same always"`, yet renders `data/a.q/y` and
> `data/b.q/y` unbound. 0.4.0 shipped this; #124 fixes it.

**[Proven]** The view renders every path the expression renders, except where the new
name may be `..`: the operation keeps its base's parent, and its new name has the stated
form. A segment never renders `..` (§3), but pathlib makes the name `..` from the stem
`..`, or from the stem `.` before the suffix `.`, so `with_stem` with a literal `.` or
`..` has no view (corrected in #120; its journal, §4). So a "never" proved on the views
holds of the expressions. A "sometimes" is still shown only by a binding of the
expressions themselves (`_search`), and a view's text is never cancelled as a prefix.

> *Before:* "**[Proven]** The view renders every path the expression renders: the
> operation keeps its base's parent, and its new name has the stated form." It does
> not: `({root}/{d}).with_stem(".")` renders `q/..` from `d="x."`, which the view
> `{root}/.{text}` cannot, and the relation answered "never" against `{root}/..`.

## 3. Counterexamples found while building it

- **`with_suffix` on `{day}.csv` is not `{day}.parquet`.** I expected "same always".
  With `day = ""` the segment is `.csv`, a dotfile with no suffix, so
  `with_suffix(".parquet")` renders `r/raw/.csv.parquet`. wend defers the operation for
  exactly this reason, and the relation is `"sometimes"`. It is pinned by
  `test_a_changed_name_keeps_its_parent_and_what_the_change_fixes`.
- **A stem is a `Text`, not a `str`.** The first view of `with_stem` spelled its argument
  with `str()`, which gives `Text('x')`. So `raw.with_stem("x")` against
  `{root}/raw/x.csv` was proved `"never"`, though `mon.csv` with the stem `x` is `x.csv`.
  That is an unsound answer, found by a probe before any test ran. The view now takes
  the `Text`'s pieces.

  The property test as first extended caught the bug under only one seed in five: its
  pairs rarely put a changed name beside a path that can coincide with it. A second
  property test, `test_changed_names_hold_for_every_pooled_binding`, draws exactly those
  pairs, a changed name and a sibling or another change of the same base. It catches the
  bug under every seed tried.
- **Views alone lost answers.** Reasoning only on the views turned 38 `"sometimes"` and 7
  `"never"` into `"unknown"`. The engine's witness on a view binds the view's text, which
  no binding of the expressions takes, so the search for an example failed where the
  engine on the expressions had found one. None was unsound. Where the views leave an
  answer unknown, the expressions are now asked as they are, and the comparison below
  shows no answer lost.
- **The pool lacked `//`.** The mutant "an absolute parameter anchors only at `/`"
  survived: the overlap tests' pool for `Absolute` held `/`, `/a` and `/a/b`, none
  starting `//`. `//x` is now in the pool, and both the overlap and relate property
  tests pass with it.
- **Only a changed name keeps its anchor.** `relative_to({ab}, /)` renders `x` from
  `ab = "/x"`: a deferred head in general may change the anchor. It is pinned in
  `test_different_anchors_never_meet`.

## 4. Measured

**[Measured]** The same derandomised sample, answered by master (`d5b2779`) and by this
branch. Each pair is asked `same`, `inside` and `contains` under shared bindings:

| sample | always | sometimes | never | unknown |
|---|---|---|---|---|
| 1,500 general pairs, master | 694 | 287 | 2,845 | 674 (15.0%) |
| the same, this branch | 719 | 269 | 3,133 | 379 (8.4%) |
| 1,500 changed names and their siblings, master | 153 | 540 | 2,660 | 1,147 (25.5%) |
| the same, this branch | 189 | 516 | 3,324 | 471 (10.5%) |

Answer by answer, every change is a gain:
- 952 `"unknown"` became `"never"`;
- 61 `"sometimes"` became `"always"`;
- 19 `"unknown"` became `"sometimes"`.

No answer moved the other way.

**[Measured]** Mutants of the new rules, each against `tests/relate_test.py` under seeds
0 and 1, with no example database:

| mutant | killed by |
|---|---|
| an absolute parameter anchors only at `/` | `test_different_anchors_never_meet`, the general property test (with `//x` pooled) |
| a relative head anchors anywhere | `test_different_anchors_never_meet` |
| any deferred head keeps its base's anchor | `test_different_anchors_never_meet` (`relative_to`) |
| depth ignores a `SubPath` | both property tests |
| depth nests the wrong way | both property tests |
| a view keeps the base's name as well | the view cases, both property tests |
| a suffix placed before the text | both property tests |
| a stem read as its `repr` | the view cases, the changed-names property test |
| a new name seen as opaque | the view cases (precision only: sound) |
| views not taken | the view cases (precision only) |

**[Measured]** In a pipeline whose outputs are named after their inputs:
- `convert` writes `{day}.parquet` and `schema` writes `{day}.schema.json`, both from
  `{root}/raw/{day}.csv`;
- on master the graph linked them by `"unknown"` conflicts, and they could not share a
  stage;
- now they are independent (`test_outputs_named_after_their_inputs`). The graph's
  parent rule (#118 §8.5) reads a changed name's directory through its view too.

A `stats` step writing `raw.with_stem("summary")` collides with the raw CSV of a day
named `summary`. The graph shows a possible cycle through that collision, and
`cycles(certain=True)` stays empty. That is the may/must distinction doing its work.

## 5. What it does not do

- **[Fact]** Two changed names of one base are related only through the engine. For
  `{day}.parquet` against `summary.csv`, both from `{day}.csv`, the answer is never in
  fact, but `"unknown"` here: the views lose that the texts come from one `day`.
- **[Fact]** The engine's MAYBE remains the largest source of `"unknown"`: conversions,
  floats, untyped formatted fields and `SubPath`s against segments.
- **[Open]** Other deferred operations (`parent` of a `SubPath`-ended path,
  `relative_to`, a join that may reset to an absolute path) have no view.
