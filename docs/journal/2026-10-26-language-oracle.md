# 2026-10-26: An exact oracle for relate under independent bindings (#ORACLE)

`relate` proves relations with a growing set of rules (views, cases, depths), and
checks them against pooled bindings, which try finitely many values. This entry builds
something stronger to check them against: an exact decision procedure for
`relate(..., shared=False)` on a stated fragment, built only from wend's interpreter.
The code is `src/wend/_experimental/lang_oracle.py`, the tests are `tests/lang_oracle_test.py`, and the
comparison is `bench/relate_oracle.py`.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Interpretation]**.

## 1. What an expression denotes

**[Fact]** Under independent bindings an expression denotes the set of paths it
renders over all bindings, and each side's set is independent of the other's. The
three questions are then questions about two sets:
- `same` is possible exactly where the sets intersect;
- `inside` where `a`'s set meets `b`'s followed by one segment or more;
- `always` where every pair relates. For `same` both sets must be one path; for
  `inside`, `b`'s must be one path with all of `a`'s below it.

**[Proven]** For a *linear* expression, one that uses no name twice, that set is a
regular language. The oracle builds it as a nondeterministic automaton over a path's
parts, an anchor token and then each segment's characters followed by `/`:
- a field's text is any text without `/` or NUL, narrowed only by what rendering
  enforces (a spec's facts, dot-free or non-empty);
- a segment drops `""`, `.` and `..` wherever wend checks it (`needs_check`);
- a `SubPath` is any number of segments other than `.` and `..`;
- a head parameter is any canonical path, absolute where its kind says so.

pathlib's operations map onto standard language operations:
- `parent` drops a last segment, a right quotient;
- `with_name`, `with_suffix` and `with_stem` rewrite the last segment with a
  transducer that follows pathlib 3.14's `stem` and `suffix` exactly. The suffix is the
  last dot onward, where the text before it holds a character other than a dot;
- `relative_to` drops a prefix, a left quotient;
- `join` concatenates, or replaces where the right side is absolute.

Images of regular languages under these operations are regular, so the construction
is exact.

**[Fact]** Without `builtin_values`, neither a format spec nor `choices` narrows a
value's text. A value's `__format__` may return anything, and an object may compare
equal to a choice: `value in choices` is a hash and an `==`. So `{n:03d}` may render
`zz`. The oracle mirrors that, and builds such values to show it.

**[Fact]** A name used twice in one expression (`{p}/{p}`) renders one value twice,
and `{ww}` is not regular. Such expressions are outside the fragment, and the oracle
says so (`Unsupported`) rather than guess.

## 2. Every "possible" comes with a rendering

**[Fact]** Every edge of an automaton records which parameter emitted its character.
That includes the characters an operation reads and drops, such as the old suffix
that `with_suffix` replaces, or the prefix `relative_to` removes. A word the oracle
accepts therefore carries a binding for each side, and wend renders it:
`test_every_possible_relation_renders` checks that the paths relate as the oracle
says, for every relation it finds possible.

**[Measured]** That check found the oracle's own bug at once. The first transducer
for `with_suffix` let the no-suffix branch start after part of the name was copied,
so it accepted `/a.b` for `with_suffix(/{c}, "")`. 13 witnesses in 600 pairs rendered
otherwise. The fix chooses the branch at the start of the segment. Restoring the bug
fails the test.

**[Measured]** The oracle's tests, each over 300 valid examples:
- `test_a_language_holds_every_rendering`: every pooled rendering of an expression,
  under up to two deferred operations, is in its language;
- `test_every_possible_relation_renders` (above);
- `test_never_and_always_hold_for_pooled_bindings`: no pooled pair contradicts a
  `"never"` or an `"always"`;
- `test_relate_agrees_with_the_oracle`: `relate` answers the oracle's answer, or
  less. That is `"unknown"`, or `"sometimes"` where the relation holds always, which
  SEMANTICS allows (§15.2: at least one binding).

## 3. relate against the oracle

**[Measured]** `bench/relate_oracle.py` on #119's three samples, 1,500 pairs each
(derandomised; two identical runs agree exactly). Of 4,500 pairs, 2,896 are in the
fragment, so 8,688 answers are compared:

| | general | changed names | below one head | all |
|---|---|---|---|---|
| pairs in the fragment | 1,133 | 1,203 | 560 | 2,896 |
| answers agreeing | 3,030 | 3,126 | 951 | 7,107 |
| `"unknown"`, oracle `"never"` | 33 | 32 | 106 | 171 |
| `"unknown"`, oracle `"sometimes"` | 334 | 449 | 619 | 1,402 |
| `"unknown"`, oracle `"always"` | 0 | 0 | 2 | 2 |
| `"sometimes"`, oracle `"always"` | 2 | 2 | 2 | 6 |
| contradictions | 0 | 0 | 0 | 0 |
| oracle witnesses that fail to render | 0 | 0 | 0 | 0 |

The oracle takes 18 s for the 2,896 pairs, about 6 ms a pair.

**[Measured]** No answer of `relate` contradicts the oracle: no `"never"` where a
rendered binding shows the relation, no `"always"` where it fails, no `"sometimes"`
where it is impossible. On this fragment, under independent bindings, the rules of
#119 to #128 found no soundness defect.

**[Measured]** The precision `relate` leaves on this fragment is 1,575 answers, 18% of
those compared. Most (1,402) are `"unknown"` where a binding exists that the search
does not find. 171 are `"unknown"` where nothing can render the relation. Some of
the 171:
- `with_suffix(data/{x}, ".q")` is never `data/.q`, since a stem is never empty;
- `with_stem({ab}/{f}, ".")`, with `f` a `bool`, renders nothing: its name `True`
  or `False` has no suffix, and pathlib refuses the stem `.` there, so every relation
  is vacuously `"never"`;
- `with_suffix(with_stem(//{c}, "a"), ".b")` is always `//a.b`, which `relate`
  answers `"sometimes"` with itself.

## 4. What the fragment leaves out

**[Measured]** 1,604 of the 4,500 pairs are outside it: 1,563 because a name is used
twice in one expression, and 41 for a typed path parameter. Names used twice are
common in the samples (`{p}-{q}/{p}-{q}`), and in real layouts (a run's id in a
directory and in a file name). They are the next thing to decide.

**[Fact]** Also outside it: dynamic specs, a conversion together with a spec, the
`!a` conversion, and fields over a path's name or stem (`TextOp`). Each raises
`Unsupported`, so the oracle is exact or silent, never approximate.

## 5. Where this sits in the Future Paths essays

**[Interpretation]** The owner asked for this work to be read against the
[Future Paths](https://cog.spin.systems/future-paths) essays, and a reading of it was
offered with the request. That reading is one interpretation and may not match the
essays everywhere; it is recorded here because its framing is useful.

- **A path is a recipe, not a string.** The essays' first move is to keep how a path
  is built (its parameters, its format specs, its derivation) rather than collapse it
  into its rendered value. `relate` and this oracle add one consequence of keeping
  it: the recipe also describes exactly which strings are possible. Built as an
  automaton, that description answers questions about all renderings at once.
- **Three uses of one expression.** wend began with two directions:
  - *render*, parameters to a path;
  - *match*, a path back to parameters, which the essays imply through the backward
    direction of a lens.

  `relate` is a third, an expression against an expression, decided before any
  binding. Part 3's structured filenames (`chunk_{idx:04d}-of-{total:04d}.parquet`)
  are where the three meet: the pattern formats, parses, and constrains which names
  can exist. Without `builtin_values` that constraint holds only for the literal
  text, since a spec narrows nothing (§1).
- **Connectivity, then consequences.** Part 2's relations (`sibling`, `cousin`,
  `rebase`, `under`) say how paths are derived from one another. `relate` asks what
  that implies: whether two derivations can ever name one path.
- **Conditions and steps need the answer.** Part 1's `requires` and `ensures`, and
  `Step`, raise the question whether a later step's requirement is met by what an
  earlier one established. That has two halves:
  - whether the two expressions name one path, which is `relate`;
  - whether what was established still holds, which is the effects and obligations
    work (`EffectGraph`, #120 and after).
- **Queries and inference.** Part 1's queries and schema inference already treat
  patterns as sets of paths found on disk. The language view decides relations between
  those sets without listing anything: whether two patterns of a layout overlap, or one
  includes another.
- **Where it stops.** Lineage, staleness and content addressing are about files over
  time, which no language of path strings can describe. A proof about strings also
  says nothing of two strings naming one file through a symlink or a hard link
  (SEMANTICS §15: the comparison is lexical).

**[Interpretation]** One sentence from that reading states the direction well: *a
path expression is not only a deferred computation of a pathname, it is a symbolic
specification of possible pathnames, whose relationships to other specifications can
sometimes be proved before any filesystem operation occurs.* The research since the
0.2.0 stock-take (types, effects, identity, matching, dependencies, and now languages)
asks one question from different sides: how much a program can know, derive and
trust about its paths before they are concrete.

## 6. Next

- Names used twice: the largest gap (§4). Over a finite pool of values, or with word
  equations, both sides' repeats are decidable in principle (Makanin; Plandowski; Jeż).
- Shared bindings, where the same question becomes a word equation between the two
  sides.
- A `builtin_values=True` mode, where specs and choices do narrow values, and the
  languages become those of `int`, `float` and `str` formatting.
