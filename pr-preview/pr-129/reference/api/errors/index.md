# wend.errors

Exception hierarchy.

Every error raised deliberately by wend derives from `WendError`. Errors that signal an unacceptable value also derive from `ValueError`, so callers that already handle pathlib's `ValueError` keep working. Misused arguments raise `TypeError` or `ValueError`, as Python's own functions do; the private helpers at the end hold the argument rules that several entry points share.

## WendError

Bases: `Exception`

Base class for all wend errors.

## MissingBindingError

```python
MissingBindingError(missing: set[str])
```

Bases: `WendError`, `ValueError`

Resolution was attempted without values for some parameters.

### missing

```python
missing = frozenset(missing)
```

## InvalidBindingError

Bases: `WendError`, `ValueError`

A bound value is not acceptable at the position where it is used.

Raised when a value would silently change the segment structure of the expression (a separator inside a segment, an empty segment, `.`), escape upwards (`..`), or violate a declared type, kind or set of choices.

## PathOperationError

Bases: `WendError`, `ValueError`

A path operation is invalid for this expression (mirrors pathlib's ValueError).

## NotStaticError

Bases: `WendError`

The requested information depends on parameter values that are not bound.

## NotInvertibleError

Bases: `WendError`

The expression contains a construct that `match` cannot invert.

## AmbiguousMatchError

```python
AmbiguousMatchError(path: str, candidates: Sequence[Mapping[str, Any]])
```

Bases: `WendError`, `ValueError`

A concrete path matches the expression with more than one set of bindings.

### path

```python
path = path
```

### candidates

```python
candidates = list(candidates)
```

## ParamConflictError

Bases: `WendError`, `ValueError`

Two different parameter declarations share a name within one expression.

## ConditionError

```python
ConditionError(path: str, condition: Any, message: str)
```

Bases: `WendError`

A declared condition does not hold for a rendered path (§10).

`path` is the rendered path and `condition` the condition that failed. Subclasses also derive from the builtin exception that describes the same failure, so `except FileNotFoundError` keeps working.

### path

```python
path = path
```

### condition

```python
condition = condition
```

## IndeterminateError

```python
IndeterminateError(path: str, condition: Any, message: str)
```

Bases: `ConditionError`

Whether a condition holds could not be determined (§10).

The filesystem could not say: the path could not be examined (no permission to look, a symlink loop, a failed request), or the backend cannot report the capability without exercising it (whether an object store would accept a write). It is not a known failure, which is a `CapabilityError`, `MissingPathError`, `PathExistsError` or `WrongKindError`.

## MissingPathError

```python
MissingPathError(path: str, condition: Any, message: str)
```

Bases: `ConditionError`, `FileNotFoundError`

A path required to exist does not.

## PathExistsError

```python
PathExistsError(path: str, condition: Any, message: str)
```

Bases: `ConditionError`, `FileExistsError`

A path required to be absent exists (possibly as a broken symlink).

## WrongKindError

```python
WrongKindError(path: str, condition: Any, message: str)
```

Bases: `ConditionError`

A path exists but is not the declared kind (a file, or a directory).

## CapabilityError

```python
CapabilityError(path: str, condition: Any, message: str)
```

Bases: `ConditionError`, `PermissionError`

A path cannot be used as declared: read, written, created or listed.

## ContainmentError

```python
ContainmentError(path: str, condition: Any, message: str)
```

Bases: `ConditionError`, `InvalidBindingError`

A path is not under the base it was declared to be under.

Raised by `render` when the bindings take the path lexically outside the base, and by `check` when it resolves outside it through symlinks.

## NoAlternativeError

```python
NoAlternativeError(tried: list[tuple[str, ConditionError]])
```

Bases: `ConditionError`, `FileNotFoundError`

No alternative of a union exists (or meets its preconditions).

`tried` lists each rendered alternative with the condition error that ruled it out, in order.

### tried

```python
tried = tried
```

### path

```python
path = tried[0][0] if tried else ''
```

### condition

```python
condition = None
```

## show

```python
show(value: Any) -> str
```

`repr(value)` for an error message, which never raises.

Some values have no repr: an int beyond the digit limit for conversion to text, or an object whose `__repr__` fails. A message about such a value must not replace the error it describes.
