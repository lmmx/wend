# 2026-10-18: Conditions on filesystems without permission bits

This entry covers item 5 of #68: checking declared conditions (§10) on an
fsspec filesystem, which #62 made discoverable but which `check` still read
as the local disk. The rules are in
[SEMANTICS.md §10](../SEMANTICS.md#10-conditions).

Labels: **[Fact]**, **[Decision]**, **[Interpretation]**.

---

## Two questions

**[Interpretation]** "Does this backend support reading?" and "can this
object be read, now, with these credentials?" are different questions. A
precondition asks the second. On a local disk `os.access` answers it; an
object store has no permission bits, so the answer is whatever the store can
report, and sometimes it can report nothing without doing the operation.

## Decisions

**[Decision]** A check has three outcomes: holds, known not to hold (the
existing errors), or cannot be determined, a new `IndeterminateError`. It
subclasses `ConditionError`, so existing `except ConditionError` code is
unaffected. Locally it is what a `stat` that fails other than by the path
being missing already raised ("could not be checked"); only the class is
new.

**[Decision]** On a store each capability is what the store reports:

- a lookup the store refuses (a 403) is indeterminate, not absent:
  discovery may read it as absent, a check must not, or `Absent` would pass
  on a path that exists;
- `Readable`: on S3, GCS, Azure and memory a successful metadata lookup is
  evidence, because there it takes the same permission as the content (S3
  `HEAD` needs `s3:GetObject`). Elsewhere it is indeterminate;
- `Listable`: the listing itself, refused means not listable;
- `Writable`/`Creatable`: indeterminate, since a store cannot say whether a
  write would succeed without writing, and a check must not write. Known
  read-only filesystems (HTTP, archives) refuse; memory accepts.

**[Decision]** Strict by default. An unverifiable precondition fails with
`IndeterminateError`, so `Writable` on S3 never passes `check`. A
precondition is a claim the caller wants verified; passing an unverifiable
one would make `check` lie. An opt-out (`unknown="pass"`) is easy to add if
a use asks for it, and nothing here constrains it.

**[Decision]** `check`, `confirm`, `Step` and `PathUnion.first` take
`fs=`, as `glob` and `infer` do, under the same rule that keeps the option
apart from a parameter named `fs`. `Query.glob` checks its condition filters
on the filesystem it walks; its stat predicates (`larger_than`, ...) read
the local disk, so they refuse another filesystem rather than answer for the
wrong one.

**[Decision]** Two places that swallowed "could not be checked" now raise
it, on every filesystem including the local disk:

- `PathUnion.first` no longer skips an alternative it could not check: a
  fallback chain must not choose a later alternative over one that may
  exist;
- a query's condition filter no longer drops such a path.

These are the only local behaviour changes.

## Limits

**[Fact]** The store rules are per protocol and conservative. A backend
wend does not know (an fsspec filesystem outside the lists) gets
indeterminate answers for `Readable`, `Writable` and `Creatable`, and true
answers for what it can report: existence, kind and listing.
