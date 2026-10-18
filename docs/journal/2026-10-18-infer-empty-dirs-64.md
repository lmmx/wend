# 2026-10-18: Empty directories generalise like files

This entry covers issue #64, found while fixing #51
([2026-10-18-infer-kinds-59.md](2026-10-18-infer-kinds-59.md)). After #51,
every empty directory was covered by a `dir` layout of its own, but empty
directories still generalised only through non-empty siblings.

Labels: **[Fact]**, **[Measured]**, **[Interpretation]**, **[Decision]**.

---

## The gaps

**[Fact]** Step 2 of `_unify` clusters lone directories by the similarity of
their contents. An empty directory was kept out twice over:
- it could not join a cluster (`if d.children and ...`);
- its own one-member cluster could not join a map (`bool(cl[0].children)`).

So empty directories merged only by sharing a name or skeleton with
non-empty siblings (`run_3/` beside `run_1/`). They never formed a map among
themselves, and never joined the map beside them.

**[Measured]** On this container's `/usr/share/doc` (1714 paths), 73 of the
110 layouts were dir layouts, and 68 of those held one path each:
- the 9 empty top-level directories (`bigreqsproto`, `xproto`...) beside the
  `{dir}/...` layouts of their non-empty siblings;
- `binutils/{bfd,gas,gprof,ld}`;
- empty siblings deeper down: 14 directly under `{dir}/contrib/` (beside the
  map `{dir}/contrib/{contrib}`), 8 under `{dir}/examples/c/` and 4 under
  `{dir}/contrib/credential/`.

**[Fact]** `_profile` returned `None` when any directory had no children.
`_opaque_dirs` uses it to decide whether a family of same-skeleton
directories (`0`...`9`) is opaque. One empty member therefore stopped
detection.

**[Measured]** The test helper `_terminfo("0123456789")` (seed 0) gives 1
layout, `terminfo/{n:d}/{name}`. With `9/` emptied, master gave 16 layouts:
each digit directory's name families stayed layouts of their own. This
change gives 2: the same file layout, and `terminfo/{n:d}` for the empty
directory.

**[Fact]** While probing this, a third gap turned up. A directory or file
named `..` (possible in an iterable of paths) could join a map. A field never
binds `..`, so `infer` failed its own check that each path matches its
layout:
- `infer(["a/x/f.txt", "b/x/f.txt", "c/x/f.txt", "../x/f.txt"])` raised
  `AssertionError`;
- so did `infer(["q/a", "q/b", "q/c", "q/.."])`.

Joining empty directories to maps would have added a third case, an empty
`../` beside a map.

## Decisions

**[Decision]** Empty directories have no contents to compare, so they are
treated like files of one extension:
- they join the directory map at their position, whatever their number, as
  same-extension files join an existing `{stem}.ext` map;
- without a map, they form one of their own once there are `min_files` (3)
  distinct names among them.

The map at a position is either one from merged parents or one formed in the
same step from clusters.

**[Decision]** The threshold is `min_files`, not `min_dirs` (2):
- `min_dirs` counts directories whose contents were compared and found
  alike.
- An empty directory has only its name, as a file has only its name and
  extension. Two empty siblings (`build/`, `dist/`) are as weak a reason to
  generalise as two `.txt` files.
- Names are counted distinct, as for files. So `examples/`, empty in every
  merged package, counts once.

**[Decision]** A map formed of empty directories takes in no directory with
contents. Non-empty directories still join a map only by similarity, and
nothing is similar to a map without contents (Jaccard 0). Empty directories
are now left out of clustering. That changes no cluster: before, each formed
a one-member cluster that never joined anything.

**[Decision]** An opaque family is judged by its members that hold files:
- `_profile` passes over empty directories, and gives no profile when no
  directory holds a file;
- `_opaque_dirs` counts and compares only non-empty members, and needs
  `min_opaque` (8) of them.

An empty directory says nothing about extensions, so it neither counts
towards the threshold nor stops a family. Seven full members and two empty
ones (nine in all) are not enough. Comparing only full members matters for
the "some members are unlike the others" test too: an empty member is unlike
every full one (Jaccard 0), and would otherwise make any eight similar
directories plus one empty directory "opaque".

**[Decision]** An entry named `..` stays a literal record: step 1 of
`_unify` puts it straight into the output, so it joins no map. SubPath folds
already treated `..` this way. This is a separate commit, since it fixes
inputs that crashed before this change.

**[Fact]** Symlinked directories are unchanged (point 3 of the issue).
`os.walk` lists them without descending, so they are not observed paths.
This matches glob's default policy.

## Results

**[Measured]** The messy-trees script (`scripts/2026-10-17-messy-trees.py`)
on its synthetic trees and on this container's real trees. Every error
column (uncovered, kind-wrong, uncounted, glob-missed, optional-wrong,
cardinality-wrong, duplicates) is 0 before and after, on every tree:

| tree | paths | layouts before | after |
|---|---:|---:|---:|
| hive | 47 | 1 | 1 |
| ml-runs | 43 | 4 | 4 |
| photos | 30 | 2 | 2 |
| imagenet | 9 | 1 | 1 |
| fastq | 12 | 1 | 1 |
| terminfo | 384 | 1 | 1 |
| package | 124 | 6 | 6 |
| doc | 181 | 12 | 11 |
| `/usr/share/doc` | 1714 | 110 | 60 |
| `/usr/share/terminfo` | 44 | 1 | 1 |
| `/usr/share/zoneinfo` | 506 | 9 | 9 |
| `/usr/lib/python3` | 2952 | 55 | 55 |
| `/usr/include` | 4244 | 20 | 20 |

The changes:
- In the synthetic `doc`, the empty `xproto/` and `kbproto/` became
  `doc/{doc}` (dir, 2 paths).
- In `/usr/share/doc`, dir layouts fell from 73 to 25, and those holding one
  path from 68 to 13. New layouts: `{dir}` (9), `{dir}/{dir2}` (11),
  `{dir}/contrib/{contrib}` (14), `{dir}/examples/c/{c}` (8),
  `{dir}/examples/{examples}` (6), `{dir}/contrib/credential/{credential}`
  (4), `{dir}/html/{html}` (3).
- `binutils` was a record before: its four empty directories made its
  contents unlike its siblings'. As one map they no longer do, so `binutils`
  joins the package map, its two files join `{dir}/...` layouts, and its
  empty directories join `{dir}/{dir2}`.
- In `/usr/include`, the one empty directory, `php/20230831/include`, joined
  the map beside it: `{dir}/{n:d}/include` became `{dir}/{n:d}/{dir2}`.

**[Measured]** More real trees with empty directories, checked the same way
(all error columns 0 before and after):

| tree | paths | empty dirs | layouts before | after |
|---|---:|---:|---:|---:|
| `/opt/ruby-3.3.6/lib` | 2371 | 70 | 201 | 134 |
| `/var/lib/postgresql` | 977 | 12 | 29 | 21 |
| `/usr/local/share` | 16 | 11 | 9 | 3 |
| `/usr/share/locale` | 215 | 169 | 3 | 3 |
| `/usr/share/man` | 297 | 52 | 3 | 3 |
| `/root/.cache/pre-commit` | 2868 | 6 | 228 | 228 |
| `/usr/share/icons` | 12647 | 330 | 101 | 59 |

In Ruby's library, the 65 empty default-gem directories became
`ruby/{ruby}/3.3.0/gems/{gems}`. In PostgreSQL's data directory, the nine
empty `pg_*` directories became `16/main/{main}`. The empty directories of
`locale` and `man` already merged by name or skeleton
(`{dir}/LC_MESSAGES`, `{dir}/man{man:d}`).

**[Measured]** On 4800 generated trees, the Hypothesis strategies of
`tests/infer_test.py` plus terminfo families and package-doc trees with
empty directories, the schemas of 1509 changed:

| generator | trees | changed | fewer layouts | more | layouts before | after |
|---|---:|---:|---:|---:|---:|---:|
| `observed_trees` | 3000 | 437 | 272 | 0 | 14050 | 13506 |
| `doc_trees` | 750 | 401 | 274 | 55 | 8998 | 8281 |
| `nested_packages` | 150 | 65 | 24 | 10 | 833 | 784 |
| terminfo with empty members | 150 | 78 | 57 | 0 | 1052 | 713 |
| package docs with empty dirs | 750 | 528 | 480 | 0 | 8147 | 7238 |

Every property of `_check_schema` held on all of them, before and after.

**[Interpretation]** The 65 trees with more layouts show that bottom-up
inference is not monotone: generalising a directory's children changes what
it looks like to the level above. Two mechanisms, each seen in a shrunk
example:
- **Similarity.** In `doc_trees`, a package holding three empty directories
  (`examples/`, `html/`, `log.gz/`) now has a map of them. Its siblings hold
  one or two of the same names as literal empty directories, so the package
  shares fewer child skeletons with them and falls out of their map.
- **Folds.** In `nested_packages`, an empty `fixtures/` beside a package's
  two sub-packages joins their map, and loses its name. The
  `{rel...}/fixtures` fold that took in every package's `fixtures/` then
  lacks a starting layout of two `fixtures` paths, and the shrunk tree's two
  layouts become five.

The same mechanisms help elsewhere. In 24 `nested_packages` trees, a
one-sided literal `fixtures/` going into a map makes sibling packages alike,
and more folds (9 layouts to 6, 13 to 7). Files have always behaved this
way: three `.md` files in one directory become `{stem}.md`, while a sibling
holding two keeps them literal, and the two directories stop looking alike.

**[Decision]** I kept the rule as the issue proposed it. On the same 4800
trees I measured two narrower rules (from 33,080 layouts in all on master):

| rule | layouts | trees with fewer | with more |
|---|---:|---:|---:|
| join any map at the position (kept) | 30,522 | 1107 | 65 |
| join only a map already holding observed directories | 30,928 | 860 | 41 |
| join only a map of at least `min_opaque` names | 31,419 | 656 | 46 |

Both narrower rules leave `nested_packages` unchanged, losing its 24
improvements along with its 10 regressions. Both leave `/usr/share/doc` at
60 layouts. The first keeps `xproto/` and `kbproto/` as records in the
synthetic `doc` tree. The rule as proposed is the simplest of the three,
and it generalises the most. The regressions come from `_similar` and the
fold criterion, not from the joining rule: comparing childless directories
by one coarse key would address the first, but that changes similarity for
trees without empty directories too.

**[Measured]** Cost is within noise. This machine was noisy (other work ran
on it), so separate runs of `bench/bench.py inference` varied by up to 70%
between repeats. Six interleaved runs per side gave best times of 23,010
ns/path on master and 23,171 on this branch. Alternating master and branch
in one process, 21 rounds each, warm caches:

| workload | master median ms | branch median ms | master min | branch min |
|---|---:|---:|---:|---:|
| `bench.py` inference (20,030 paths) | 539.2 | 542.1 | 470.8 | 468.0 |
| `/usr/share/doc` | 94.4 | 91.0 | 87.1 | 80.6 |
| `/usr/lib/python3` | 271.5 | 266.2 | 252.0 | 245.5 |
| `/usr/include` | 164.3 | 159.9 | 150.7 | 151.5 |
| `/opt/ruby-3.3.6/lib` | 324.2 | 323.9 | 289.4 | 286.2 |

The bench workload has no empty directories. There the change adds only a
pass that finds the empty ones among each level's lone directories.
`/usr/share/doc` is a little faster, most likely because `_mark_cardinality`
and the SubPath fold now have 50 fewer layouts to go through.

**[Fact]** #52's schemas still round-trip:
- for `/usr/share/doc`, `terminfo`, `zoneinfo`, `/usr/lib/python3`,
  `/usr/include`, the seven further real trees above and the eight synthetic
  trees, `from_inferred(infer(root))` validates its tree with no problems;
- so does the class that its `source()` text defines.

`/usr/share/doc` now has 25 dir layouts, and its `{dir}` dir entry matches
every package directory, empty or not.

## Left open

- **Non-monotone similarity.** Generalising children can make a directory
  less like its siblings (see the interpretation above). Comparing childless
  directories by one coarse key, and files by extension where one side is a
  map, would address it. Both change similarity beyond this issue.
- **Recurring names.** An empty directory named like a record that recurs
  elsewhere (`fixtures/` in each package) joins a map beside it, and its
  name is lost there. A SubPath fold with that tail can still take in the
  map's layout, but only when all of its paths end in the name, and only
  when another layout gives the fold a start.
