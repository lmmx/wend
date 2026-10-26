# 2026-10-26: The oracle under shared bindings (#SHARED)

#129 and #130 decide `relate(..., shared=False)`. `relate`'s default is
`shared=True`, where a name takes one value on both sides (SEMANTICS §15.1), and its
`"never"` answers there are the ones a pipeline relies on: two steps' paths that never
meet. Until now only pooled bindings checked them. This entry decides the shared case
with the same oracle: `relate_shared` in `src/wend/_experimental/lang_oracle.py`.

Labels: **[Fact]**, **[Measured]**, **[Proven]**.

## 1. A name of both sides, tied

**[Proven]** Under shared bindings a name of both sides renders one value on both. That
is #130's question for a name used twice, with the uses on two sides instead of one, so
the same procedure decides it:
- each use is read apart, so a `"never"` on the larger language is exact;
- a witness counts where each shape's uses agree, on both sides together, and is then
  one binding of both, which wend renders;
- otherwise each disagreeing (name, shape) is held to each text its uses can take, on
  both sides at once, and decided again.

**[Fact]** A name both sides give a default may also be unbound, and each side then
renders its own default (§15.1). `relate_shared` decides each such name both ways:
tied, and with each side bound to its own default. A relation holds never, or always,
where it does in every case, and is possible where it is in one.

## 2. A shared prefix cancels

**[Measured]** On #119's samples, 200 pairs each, the procedure of §1 alone leaves 418
of `relate`'s `"never"` answers undecided. Most are a shared prefix: `{ab}/a` against
`{ab}`, or `{root}/{p}.txt/b/x.txt` against `{root}/{p}.txt/b/../{sc...}`. Read apart,
the two `{ab}` render different texts and meet; the candidates for `ab` are infinite.

**[Proven]** Under shared bindings a piece equal on both sides renders one text on both
(SEMANTICS §15.3, 1), and a path's characters are its head's, then its parts'. In a
free monoid `uv = uw` exactly where `v = w`, and `uv` is `uw` followed by more exactly
where `v` is `w` followed by more. So where `a` and `b` share a head and leading parts,
they relate on every binding as what follows does. Every binding that renders `a` and
`b` renders what follows, since a part renders by itself. So a relation never (or
always) holding of what follows never (or always) holds of `a` and `b`.

`relate_shared` decides both and keeps the stronger answer. A witness for the whole,
rendered by wend, where what follows says `"never"`, would raise: none has.

## 3. Tests and measurements

RESULTS

MUTANTS

## 4. Next

- A count of segments or characters settles most of what is left: `{x}/a/{x}` against
  `{x}/{x}` asks `|x| + 2 = 2|x|`. That is a question about the Parikh image of the
  intersection, with one equation per tied name, which integer programming decides.
- `builtin_values=True`, where a spec does narrow a value's text.
