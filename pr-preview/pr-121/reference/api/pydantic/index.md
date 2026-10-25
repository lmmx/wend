# wend.pydantic

Pydantic integration (optional dependency: `pip install 'wend[pydantic]'`).

Two kinds of field metadata, for `typing.Annotated`:

- `PathOf(expr)`: the field holds a path of `expr`'s layout. A path given as input must match `expr`; bindings given as input (a mapping, or an object such as another model) are rendered through it, which resolves the path at validation time, as Pydantic's `ImportString` imports. Either way, `expr`'s preconditions (`requires`) are then checked against the filesystem::

  class Job(BaseModel): shard: Annotated\[Path, PathOf(shard.requires(File, Exists))\] last: Annotated\[Match, PathOf(shard)\] \# the path and its bindings
- wend's conditions themselves (`File`, `Dir`, `Exists`, `Absent`, `Readable`, `Writable`, `Creatable`, `Listable`, and `Under` with a static base) validate a path field: `Annotated[Path, File, Exists]` is Pydantic's `FilePath`. They work without importing this module, which they load when Pydantic asks for their schema.

The field's type decides the validated value: `Path` (or another `PurePath` class), `str`, or `Match` for the path with its bindings. In JSON, every one of them is the path string.

Checks touch the filesystem when the model is validated, and describe it at that moment (docs/SEMANTICS.md §10): validation is an effect here.

## PathOf

```python
PathOf(expr: Any)
```

Field metadata: the value is a path of `expr` (an expression, a union, or anything `P` takes).

- A path (`str`, `os.PathLike` or `Match`) must have exactly one reading by `expr`; no reading and several readings are validation errors.
- Anything else is bindings (see `wend.bindings`), rendered through `expr`. Defaults apply as they do in `render`.

Then `expr`'s preconditions are checked with the bindings (`PathExpr.check`); a `Match` result carries those bindings.

### expr

```python
expr: PathExpr | PathUnion = (
    expr if isinstance(expr, PathUnion) else _coerce(expr, at_head=True)
)
```

### validate

```python
validate(value: Any) -> tuple[str, Match]
```

The path `value` stands for and its reading, or a `PydanticCustomError`. A declaration that cannot be used this way (`NotInvertibleError`) is raised as it is.
