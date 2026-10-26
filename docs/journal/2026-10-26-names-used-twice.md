# 2026-10-26: The oracle for names used twice (#NAMES)

#129's oracle decides `relate(..., shared=False)` exactly on expressions that use no
name twice, and that left out a third of #119's samples (`{p}-{q}/{p}-{q}`). This entry
extends it to them. The code is `src/wend/_experimental/lang_oracle.py`, as before.

Labels: **[Fact]**, **[Measured]**, **[Proven]**.

## 1. What "the same name" ties

**[Fact]** Rendering is a function of structure (SEMANTICS §15.3, 1): two uses of a
name render one text where they render it the same way. Without `builtin_values`, a
value is any object, and different ways of rendering it are independent:
- `os.fspath` or `format(v, "")`, alone in a segment, as a `SubPath` or as a head;
- `format` after one conversion, with one spec, in text.

So a value may format `007` with the spec `03d` and `7` with none, and
`d/{n:03d}/{n}` renders `d/007/7`. The first version of this extension tied every use
of a name together. It would have answered `"never"` there, which is false. The
`fspath` shape needs care of its own: a path's text spells a trailing `/` and a
segment's never does, so the two are compared after the same normalisation.

The oracle therefore keys each use by name and *shape*: `fspath`; or `format` with a
conversion and a spec; or, for a type of two values (`bool`), the value itself.
Only uses of one shape are tied.

## 2. The procedure, and why it is exact

**[Proven]** Read each use as a name of its own. The language grows, since uses that
should agree may now differ, so a `"never"` on it is still exact.

Where the larger language does meet, a word gives each use a text:
- **The uses of each shape agree.** That is a real binding: rendering it confirms it,
  and a value of its own renders each shape's text.
- **Some shape's uses disagree.** Take, for that (name, shape), each use's
  *projection*: the texts it emits on the words of the intersection. Every real binding
  that shows the relation is such a word, with that text on every use, so the text lies
  in every use's projection. Where one use's projection is finite, its texts are all
  the candidates. The (name, shape) is held to each candidate in turn, by building that
  use's language as the text alone, and the question is decided again.
- **No candidate shows the relation.** Where the candidates were complete, the
  relation never holds. Otherwise the answer is `"undecided"`.

The answers are therefore `"never"`, `"sometimes"` and `"always"` (exact), `"possible"`
(shown, though whether it always holds is not decided), and `"undecided"`. A relation
held to be possible always comes with bindings that wend renders.

## 3. Tests and measurements

**[Measured]** `tests/lang_oracle_test.py` now draws pairs with names used twice too.
- Every `"possible"` and `"sometimes"` renders.
- Every `"never"` and `"always"` holds for the pooled bindings.
- `relate` agrees, allowing it to say less (`"unknown"`).

`test_a_name_used_twice_is_decided_through_its_values` holds three cases:
- `d/{p}-{q}/{p}-{q}` against `a-b/a-c` (never) and `a-b/a-b` (possible);
- `{n:03d}` used twice (never) against `{n:03d}` and `{n}` (sometimes);
- a `SubPath` used twice.

**[Measured]** `bench/relate_oracle.py` on #119's samples, 1,500 pairs each. 4,427 of
the 4,500 pairs are now decided, against #129's 2,896; the 73 left out have a typed
path parameter. That is 13,281 answers:

| oracle answer | general | changed names | below one head | all |
|---|---|---|---|---|
| `"never"` | 2,502 | 2,609 | 1,527 | 6,638 |
| `"sometimes"` | 1,267 | 1,454 | 1,325 | 4,046 |
| `"always"` | 308 | 65 | 4 | 377 |
| `"possible"` | 295 | 278 | 1,508 | 2,081 |
| `"undecided"` | 23 | 16 | 100 | 139 |

Against `relate(shared=False)`:
- **0 contradictions**, and no witness that fails to render;
- 8,999 answers agree;
- `relate`'s `"unknown"` becomes `"never"` 332 times, `"sometimes"` 1,722 times,
  `"possible"` 1,360 times and `"always"` once, and stays undecided 136 times;
- `"sometimes"` where the relation holds always: 7.

Three answers `relate` decides the oracle leaves undecided: two `"never"` and one
`"sometimes"`. The oracle is exact where it answers, not complete.

**[Measured]** Under one deferred head, a pair takes 0.31 s on average, against 6 ms
for linear pairs: the candidates are decided again, up to twice over.

**[Measured]** Mutants, against `tests/lang_oracle_test.py` under seed 0:

| mutant | killed by |
|---|---|
| uses of every shape tied | `test_a_spec_does_not_narrow_a_value_without_builtin_values`, and the `{n:03d}`/`{n}` case |
| the candidates taken as complete, though a use's texts are infinite | `test_a_name_used_twice_is_decided_through_its_values`, once it held `{p}.x/{p}.y` against `A{q}.x/{r}B.y`: the uses take `A` and `B`, neither of which holds, while `AB` does. Its first version survived |
| a candidate not held to its text | `test_a_name_used_twice_is_decided_through_its_values` |
| disagreeing uses read as agreeing | the same |
| a witness not confirmed by rendering | survived: a safety net. Where every shape's uses agree, the value the oracle builds renders each shape's text, so the confirmation never fails on the generated pairs; `test_every_possible_relation_renders` renders every witness anyway |
| path texts compared unnormalised | survived: equivalent in its answers. A head's text spells a trailing `/`, a segment's never does, so without normalising, the two uses of an AUTO name disagree. Substitution then tries both texts, and the one without the `/` holds, giving the same answer by the slower route |

**[Measured]** The oracle's tests pass under seeds 0 to 4.
