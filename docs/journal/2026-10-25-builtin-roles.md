# 2026-10-25: A field in either role, for builtin values (#125)

#122 left three of its corpus's links `"unknown"`, and said why they should stay so
without an assumption: a shard directory `{split}` against its manifest `{split}.json`.
This entry makes the assumption `builtin_values=True` decide them. The contract is
`docs/SEMANTICS.md` §15.3 (1, 5) and the paragraph on `builtin_values` after it.

## 1. Two roles, one text

**[Fact]** wend renders a parameter in one of two roles (`_expr.Field.role`):
- **Alone in a segment**, as `P(root) / split` or `T(t"{split}")`, it is segment-valued.
  It renders `os.fspath` of a `str` or `os.PathLike`, and `format(v, "")` of anything
  else (`_segment_text`), and fails on `""`, `.`, `..` and separators.
- **In text**, as in `T(t"{split}.json")`, it renders `format` of its value after its
  conversion, with its spec (`format_field`).

A value of a type of its own may render the two apart. A `str` subclass whose
`__format__` drops a `.json` suffix renders `r/a.json` both as `P(root) / split` and as
`P(root) / T(t"{split}.json")`, from `split=Odd("a.json")`. So, by default, the two
pieces do not cancel (#122 §4), and the relation stays `"unknown"`.

## 2. The rule, and why it is sound

**[Proven]** Call a field *plain* when its parameter renders with no spec and no
conversion but `!s`: every segment-valued field, and `{split}` or `{split!s}` in text.
Let `v` be a value of a builtin type: `str`, `int`, `float`, `complex`, `bool`, `None`,
or a pathlib path, as `builtin_values=True` assumes (§15.5).
- A segment-valued field renders `os.fspath(v)` for a `str` or path, which is `str(v)`:
  a `str` is itself, and `PurePath.__fspath__` returns `str(self)`. For the other types
  it renders `format(v, "")`.
- A plain field in text renders `format(v, "")`, or `format(str(v), "")` under `!s`.
- For every builtin type, `format(v, "")` is `str(v)`: an empty spec formats as `str`.

So a plain field renders `str(v)` in either role, wherever it renders. Where one role
fails (a segment of `""`, say), the relation does not ask, since it compares only the
bindings under which both sides render. So two plain fields of one parameter render one
text, as (1) requires of pieces that cancel, and wend compares them equal: their keys
are `("plain", name)` (`_relate._key`, under a `Memo` built with `builtin=True`).

Everything that compares by key inherits it: prefix cancellation, the cancellation of
pieces within two segments (#122), and the names given to views (#119). Each uses only
that equal keys render equal text.

**[Fact]** An answer may then rest on the assumption, so `Relation.assumptions` names
`builtin_values` whenever some name is a plain field in both roles across the two
expressions. That may name it where no answer needed it, as the overlap analysis also
does for every answer it was asked about, `"unknown"` included. It never leaves it out
where one did.

## 3. Tests and measurements

**[Measured]** The relate property tests had never asked `builtin_values=True`,
though the pool they bind holds only builtin values. `assert_sound` now checks every
`"always"` and `"never"` in both modes, and the pool gains a pathlib path
(`PurePosixPath("x.txt")`). The effects disk oracles do the same: each generated graph
is built with `builtin_values` drawn at random, over families that give `name` both
roles (`P(root) / name` against `{name}.csv` and `T(t"{name}")`). Every pooled value
is a `str`, so both kinds of graph must hold on disk.

**[Measured]** `test_a_field_renders_its_value_alike_in_a_segment_and_in_text` holds
the shard and its manifest:
- `"disjoint"` with `builtin_values=True`, and `"builtin_values"` among the
  assumptions;
- `"unknown"` without it;
- a `str` subclass that renders `r/a.json` both ways, to show the assumption carries
  weight;
- `!s` cancelling, while a spec or `!r` does not.

`test_builtin_values_relates_a_shard_directory_and_its_manifest` shows the same of
`EffectGraph`: two unknown links without the assumption, none with it.

**[Measured]** The corpus (`bench/effects_corpus.py --builtin`): the shards' three
links are decided, and the corpus's unknown links fall from 6 to 3. These are the three
#122 found genuine.

**[Measured]** The relation on #119's samples, under `builtin_values=True`, master
against this branch. Each side ran with the same fixed `PYTHONHASHSEED`, since the
search for an example depended on it (#126):
- 4 `"unknown"` became `"never"` in the general sample;
- 1 in the changed-names sample;
- 1 below one deferred head.

No other answer changed, under hash seeds 0 and 1. A first comparison, run without a
fixed seed, showed two `"sometimes"` become `"unknown"`. Both pairs give either answer
on master too, depending on the seed. #126 removes that dependence.

**[Measured]** Mutants, against `tests/relate_test.py`, then `tests/overlap_test.py`
and `tests/effects_test.py` where those were needed, under seeds 0 and 1:

| mutant | killed by |
|---|---|
| any conversion is plain | `test_a_field_renders_its_value_alike_in_a_segment_and_in_text` |
| `!s` is not plain | the same, once it held `{split!s}.json` |
| any spec is plain | the same |
| plain fields alike without `builtin_values` | the same, and `test_segments_that_differ_on_every_run_never_meet` |
| no assumption recorded | the same |
| the assumption for one role alone | the same |
| relate's memo ignores `builtin_values` | the same |
| the graph's memo ignores `builtin_values` | `test_builtin_values_relates_a_shard_directory_and_its_manifest` |

One more survived in a first version: "the assumption for unknown answers too". The rule
then named `builtin_values` only beside answers other than `"unknown"`, and no test
told the two apart. The overlap analysis already names it for every answer it was
asked about, `"unknown"` included, so the rule now does the same. It is simpler, and
it is what the mutant did.

**[Measured]** The property suites (relate, overlap, effects and families) pass under
seeds 0 to 4.

## 4. A hang the new checks found

**[Measured]** Checking `builtin_values=True` in the relate property tests found a
pair whose relation did not finish: under seed 3, below one deferred head,

```python
base = (P(ab) / sc / q / sc / s).with_suffix(".b")   # sc: choices {".", "a", "a/b"}
a = base / s / n / sc
b = a / s / n / sc
relate(a, b, shared=False, builtin_values=True)    # over 120 s on master
```

**[Fact]** With `builtin_values=True` a `SubPath`'s choices are exhaustive, and each
of the five `sc` gives the overlap analysis three shapes: 54 for one side, 162 for the
other. `_overlap` paired all 8,748 shape pairs, up to 64 alignments each. It also kept
every candidate path in a list, checking membership before each addition, which made
the work quadratic in the number of candidates.

**[Proven]** The fix keeps the candidates in a dict, and stops pairing shapes once two
have met and enough candidates are in hand. Neither changes an answer.
- A NO needs no two shapes to meet, so once two have met the verdict is YES or MAYBE
  whatever the rest give.
- Only the first `witnesses × 4` candidates were ever tried: those rendered from
  samples first, then those the shapes gave, in order. The fix keeps exactly those.

**[Measured]** The pair now takes 0.3 s. A variant whose shapes never meet still
pairs them all, as a NO requires: 7.5 s, where master did not finish in 300 s.
`test_finite_choices_that_multiply_shapes_stay_quick` holds the pair. On #119's
samples, in both modes of `builtin_values`, no answer changed.
