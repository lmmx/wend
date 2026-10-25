# 2026-10-25: Fewer unknowns on realistic pipelines (#122)

The precision measured in #119 and #120 was measured on the property tests' grammar,
which is adversarial by design: `..` segments, choices that need `builtin_values`, `//`
anchors and stems of `.`. This entry measures instead on pipelines of the shapes people
write, finds where their links stay `"unknown"`, and records three rules that remove
most of them. The contract is `docs/SEMANTICS.md` §15.3 (3, 5) and §15.4.

## 1. The corpus, and what it showed

**[Measured]** `bench/effects_corpus.py` builds eight pipelines:
- the example's seven steps;
- date partitions compacted by month and pruned;
- training checkpoints evaluated, selected and collected;
- a build compiled, packaged and cleaned;
- outputs named after one input by changed suffixes and stems;
- shards with manifests;
- work published from a scratch directory;
- a mirror kept by `SubPath`s.

On master (`2dcfbfe`), 19 of their 55 links were `"unknown"`. Each was traced:

| cause | links | what it is |
|---|---|---|
| parent conflicts where a step needs the shared directory | 10 | spurious (§2): the checkpoints' 5, the partitions' 1 (once the shared directory is named, §3), and 4 among the renames |
| changes of one base's name | 3 | spurious (§3) |
| a field against the same field with text after it | 3 | needs `builtin_values` (§4) |
| a parent conflict where neither step needs the directory | 1 | genuine |
| a step requiring a directory another may make as a parent | 2 | genuine |

After this branch, 6 remain: the 3 genuine ones, and the 3 that need `builtin_values`.

## 2. A step that needs the shared directory makes nothing there

A parent conflict (#118 §8.5) keeps apart two creations below a directory that may be
missing, where either checks `Creatable` or `Writable`: making the directory changes
what such a check finds.

**[Proven]** Let `D` be the deepest directory the two creations share, and let one of
the steps, `X`, require a path always strictly inside `D` to exist (`Exists`, or
`Readable` or `Listable`, which imply it, §10).
- Where `D` exists when the two may run, neither makes it, nor anything above it.
- Where `D` is missing, so is the path `X` requires, and `X`'s check fails whatever the
  other step does. A step's code runs only once its checks pass, so `X` makes nothing.
  The other step may make `D`, but `X` fails either way, unless the other step makes
  the very path `X` requires. Then a dependency (a read, a listing, or `exists`)
  already links the two.

So the conflict adds nothing, and is dropped. The argument holds whatever the
permissions, unlike the conflict it removes, which exists because they may differ.

**[Fact]** The deepest shared directory comes from `_shared_parent`, which named it
only where the two paths part at different literal segments, or at their last
segments. It now also names it where they part at segments that differ on every run
(§3), which settles the partitions: `data/{year}/{month}/{day}.parquet` against
`data/{year}/{month}.parquet`.

**[Fact]** No disk oracle can see a parent conflict while the tests run as root: every
directory is writable, so making a parent never changes another step's `Creatable`
answer. A mutant that drops every parent conflict passes the new commutation oracle
(§5). The rule rests on the argument above and on deterministic tests, not on the
oracle.

## 3. Segments that differ, and names written out by their split

**[Proven]** Two segments render the concatenation of their pieces. Under shared
bindings, pieces of equal structure render equal text (§15.3, 1), except a name with a
different default on each side. So equal leading pieces and equal trailing pieces
cancel, character by character in literal text:
- what remains differs if it differs in a character at either end;
- or if one side is empty and the other holds a character.

Under independent bindings only literal characters cancel. A remainder's segments at
aligned positions must be one for any of the three relations, so two that differ there
prove `"never"` for all three. This generalises the old rule, which compared only first
segments, and only literal ones.

**[Proven]** pathlib 3.14 takes a name's suffix from the name less its leading dots
(`PurePath.suffix`: `name.lstrip('.')`, then the last dot). Let the name end in literal
text `L` whose last dot is at `k`.
- If any character before that dot is not a dot, the suffix is `L[k:]`.
- Otherwise the name has no suffix.

So `with_suffix(s)` renders either `X + L[:k] + s` or `X + L + s`, and `with_stem(t)`
renders either `t + L[k:]` or `t`, where `X` is the name's pieces before `L`. On every
binding the expression renders what the case that holds renders under the same
binding, and the cases keep the base's fields. So two changes of one base are never
related when no case of one meets a case of the other. Only fields can render dots
alone, so a literal character before the dot leaves one case. A stem of `.` or `..`
has no cases, as it has no view (#120 §4).

**[Measured]** Among the corpus's renames, `stats` writes `with_stem("summary")` of
`{day}.csv`. Its links stayed `"unknown"` once §2 had removed the rest:
- conflicts with `convert` and `meta`, which write `{day}.parquet` and
  `{day}.meta.json`;
- a dependency of `check`, which reads the parquet.

All three are now `"never"`. With §2, `convert` and `meta` share a stage.

## 4. What stays unknown, and why it should

**[Fact]** A field alone in a segment is a segment-valued parameter
(`role="segment"`). It renders `os.fspath` of a `str` or path, and otherwise `format`.
The same parameter in text renders `format(value, spec)`. For builtin types the two
agree. A `str` subclass with its own `__format__` can make them differ, so `{s}` and
the `{s}` in `{s}.json` do not cancel without `builtin_values=True`. Three corpus
links rest on it: a shard directory `{split}` against its manifest `{split}.json`.
Under `builtin_values=True` they are decided.

## 5. Tests and measurements

**[Measured]** A new disk oracle, `test_steps_of_one_stage_commute_on_disk`, runs every
generated pipeline by its stages forward, and again with every group reversed. Every
step's outcome, and the tree left behind, must be the same. It kills a mutant of
`stages()` that ignores conflicts, under both seeds tried. As §2 says, it cannot see
parent conflicts.

**[Measured]** The relation on #119's derandomised samples, master against this branch:
- 22 `"unknown"` became `"never"` in the general sample;
- 25 in the changed-names sample;
- 24 below one deferred head.

No other answer changed.

**[Measured]** Mutants, each against `tests/relate_test.py`, `tests/overlap_test.py` and
`tests/effects_test.py` under seeds 0 and 1:

| mutant | killed by |
|---|---|
| a field cancels under independent bindings | `test_segments_that_differ_on_every_run_never_meet`, once it compared under a literal head (§6) |
| a different default on each side ignored | the same, once both fields were in text: a lone field is segment-valued and never cancels, so the first version never reached the check |
| no trailing cancellation | eleven tests, both property tests and the commutation oracle among them: the last-character check then compares characters that cancellation should have removed, and is unsound |
| a field may stop cancellation and still be different | the same |
| an empty side differs from a field | both relation property tests |
| divergence counted past a `SubPath` | `test_order_and_stages_hold_for_every_rendered_run` alone |
| a parent conflict dropped for a path inside only on some runs | `test_a_step_that_needs_a_directory_makes_nothing_there`, once it held such a path: its first version survived |
| a parent conflict dropped for any requirement | five tests |
| a parent conflict dropped for the directory itself | two tests |
| the shared directory named by literal segments alone | the same test, once it held the partitions' case (precision) |
| no case without a suffix | `test_the_cases_of_a_changed_name_render_all_it_renders`; it survived the relation tests, which reach the cases only where no example is found |
| the suffix from the first dot | the same |
| a new stem keeping the old suffix where there is none | the same |
| a case without a suffix whatever precedes the dot | survived: equivalent. wend defers a change only where the text before the dot is dots alone (`_suffix_split` decides the rest), so the branch it changes is not reached from the public API; it is kept for robustness, and is sound either way (an extra case only adds renderings) |

**[Measured]** The property suites (relate, overlap, effects and families) pass under
seeds 0 to 4, and the case split's invariant test under seeds 0 to 4.

## 6. Counterexamples found while building it

- **A test that did not reach its code.** The first regression for "a field cancels
  under independent bindings" used a `{root}` head. Under independent bindings only
  literal heads cancel, so the comparison never reached the segments, and the mutant
  survived. The test now uses a literal head: `a{s}x` against `a{s}` is `"never"` under
  shared bindings, and `"sometimes"` bound apart.
