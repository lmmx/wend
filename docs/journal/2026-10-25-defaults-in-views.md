# 2026-10-25: A name defaulted differently on each side is two texts (#124)

A soundness defect in `relate`. It was in 0.4.0, through the views of changed names
(#119), and on master also through the parents written out by #123. The contract is
`docs/SEMANTICS.md` §15.3 (1, 3). This entry records how it was found, its cause, the
fix, and how the fix is checked.

## 1. The defect

**[Measured]** Under shared bindings, a name left unbound renders each side's own
default (§15.3, 1). Two reproducers:

```python
xa, xb = Param("x", default="a"), Param("x", default="b")
a = (P("data") / xa).with_suffix(".q") / "y"
b = (P("data") / xb).with_suffix(".q") / "y"
relate(a, b).same  # "always" in 0.4.0 and on master
a.render({}), b.render({})  # "data/a.q/y", "data/b.q/y"

rel_a, rel_b = SubPath("rel", default="x/z"), SubPath("rel", default="x")
a = (P("data") / rel_a).parent / "a"
b = (P("data") / rel_b).parent / "x" / T(t"{z}")
relate(a, b).same  # "never" on master (since #123)
a.render({}), b.render({"z": "a"})  # both "data/x/a"
```

**Found** while #127's prototype was being checked. That change makes fresh
parameters shared by more operations, so I asked what makes sharing sound. A fuzzer
over bases whose last name has a different default on each side found the second
reproducer on master: 1 unsound answer in 15,000 checks. Against #127's prototype it
found 12, and the first reproducer followed from the argument.

## 2. The cause

**[Fact]** A view's text (#119) and a parent's new `SubPath` (#123) are parameters
wend makes up. Each is named from the operation's render key (`_key`), so the same
operation on both sides gets the same parameter, and shared bindings tie the two. The
render key compares parameters by name, as §15.3 (1) allows. That rule has an
exception, though: a name both sides give different defaults. Prefix cancellation
honours it (`_conflicting_defaults`), but a view hides the name inside its text, where
the check cannot see it. So the text was tied across two sides that, unbound, render
two texts.

## 3. The fix, and why it is sound

**[Proven]** The made-up name is now taken from `_fresh_key`: the render key together
with each name's default, or its lack of one.
- Let two sides' operations have equal fresh keys. Under shared bindings each of their
  names is bound to one value on both sides, or unbound on both.
- If it is bound, it renders one text, by (1). If it is unbound, it renders the same
  default on both sides, or fails on both.
- So the operation renders one text on both sides, wherever both render, and tying the
  made-up names is sound.
- Different defaults give different fresh keys, so the names are two, and nothing ties
  them. That can lose a proof, never make a false one.

Under independent bindings no name is tied, so nothing changes there.

## 4. Exposure

- **0.4.0** answered `"always"` for the first reproducer: a view's text, since #119.
  Its `EffectGraph.obligations()` (#120) then let a fact pass between the two paths. A
  step that creates `(data/{x}).with_suffix(".q")`, with `x` defaulted `a`, discharged
  a later requirement that the same expression with `x` defaulted `b` exist. Unbound,
  the two are `data/a.q` and `data/b.q`.
- **#123** (on master, unreleased) added the second, through a parent's `SubPath`.
- Only pairs in which one name has a different default on each side are affected.
  Within one expression a name has one declaration (wend refuses two,
  `ParamConflictError`), so `relate(e, e)` never met the defect. An `EffectGraph` met
  it only where two steps give one name different defaults.

## 5. Tests and measurements

**[Measured]** `test_a_name_changed_under_different_defaults_is_not_tied` holds both
reproducers. Both fail on master. The property suites' pool binds every name, so no
default ever rendered there. That is why they missed this.
`test_names_defaulted_apart_hold_bound_and_unbound` draws two expressions over one
base, whose last name (a `SubPath` or a segment) has a default on each side, perhaps a
different one. Each is then changed by a parent or a name operation and joined onto.
Every `"always"` and `"never"` must hold bound and unbound. It fails on master.

**[Measured]** The fuzzer that found the defect gives 0 unsound answers in 30,000
checks with the fix, under two seeds.

**[Measured]** Mutants, each against `tests/relate_test.py` under seeds 0 and 1:

| mutant | killed by |
|---|---|
| a view's name ignores defaults (0.4.0's code) | both regression tests |
| a parent's `SubPath` ignores defaults (#123's code) | `test_a_name_changed_under_different_defaults_is_not_tied` |
| defaults keyed without their names | the same, once it held two names with defaults swapped between the sides (`{x}{y}` renders `ab` on one, `ba` on the other): its first version survived |
| a missing default keyed as any default | survived: equivalent. A side that gives a name no default fails to render with it unbound, so the bindings both sides render have it bound, and one text. The fix's key is stricter than it needs to be here, which costs nothing |

**[Measured]** The relation on #119's samples, master against this branch, with the
same `PYTHONHASHSEED`: no answer changed. Their pools give no name two defaults.

**[Measured]** The relate, overlap and effects property suites pass under seeds 0 to
4, the new property test among them.
