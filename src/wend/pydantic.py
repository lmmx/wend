"""Pydantic integration (optional dependency: ``pip install 'wend[pydantic]'``).

Two kinds of field metadata, for ``typing.Annotated``:

- `PathOf(expr)`: the field holds a path of ``expr``'s layout. A path given
  as input must match ``expr``; bindings given as input (a mapping, or an
  object such as another model) are rendered through it, which resolves the
  path at validation time, as Pydantic's ``ImportString`` imports. Either way,
  ``expr``'s preconditions (``requires``) are then checked against the
  filesystem::

      class Job(BaseModel):
          shard: Annotated[Path, PathOf(shard.requires(File, Exists))]
          last: Annotated[Match, PathOf(shard)]  # the path and its bindings

- wend's conditions themselves (`File`, `Dir`, `Exists`, `Absent`,
  `Readable`, `Writable`, `Creatable`, `Listable`, and `Under` with a static
  base) validate a path field: ``Annotated[Path, File, Exists]`` is Pydantic's
  ``FilePath``. They work without importing this module, which they load when
  Pydantic asks for their schema.

The field's type decides the validated value: ``Path`` (or another
``PurePath`` class), ``str``, or `Match` for the path with its bindings. In
JSON, every one of them is the path string.

Checks touch the filesystem when the model is validated, and describe it at
that moment (docs/SEMANTICS.md §10): validation is an effect here.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath
from typing import Any, LiteralString


try:
    from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
    from pydantic_core import PydanticCustomError, core_schema
except ImportError as e:  # pragma: no cover - exercised without pydantic installed
    raise ImportError(
        "wend.pydantic needs Pydantic: pip install 'wend[pydantic]'"
    ) from e

from ._bindings import bindings
from ._expr import PathExpr, _coerce, canonical
from ._match import Match
from ._union import AltMatch, PathUnion
from .conditions import Condition, ConditionError, Under, check_conditions
from .errors import AmbiguousMatchError


__all__ = ["PathOf"]


def _output(source: Any, what: str) -> Any:
    """A function from (path string, match) to the field's value."""
    if isinstance(source, type):
        if issubclass(source, Match):
            return lambda s, m: m
        if issubclass(source, str):
            return lambda s, m: s
        if issubclass(source, PurePath):
            return lambda s, m: source(s)
    if source is Any or source is object:
        return lambda s, m: Path(s)
    raise TypeError(
        f"{what} applies to a field of type Path (or another PurePath), str or"
        f" wend.Match, not {source!r}"
    )


def _text(v: Any) -> str | None:
    """The canonical path string of a path input (as pathlib reads it, so
    ``""`` is ``"."``), or None for bindings."""
    if isinstance(v, Match):
        return v.path
    if isinstance(v, (str, bytes, os.PathLike)):
        s = os.fspath(v)
        if not isinstance(s, str) or "\x00" in s:
            raise PydanticCustomError(
                "wend_path", "{value} is not a text path", {"value": repr(v)}
            )
        return canonical(s)
    return None


def _error(kind: LiteralString, e: BaseException) -> PydanticCustomError:
    return PydanticCustomError(kind, "{error}", {"error": str(e)})


def _dump(v: Any) -> str:
    return v.path if isinstance(v, Match) else os.fspath(v)


_SERIALIZER = core_schema.plain_serializer_function_ser_schema(
    _dump, when_used="json-unless-none"
)


class PathOf:
    """Field metadata: the value is a path of ``expr`` (an expression, a
    union, or anything `P` takes).

    - A path (``str``, ``os.PathLike`` or `Match`) must have exactly one
      reading by ``expr``; no reading and several readings are validation
      errors.
    - Anything else is bindings (see `wend.bindings`), rendered through
      ``expr``. Defaults apply as they do in `render`.

    Then ``expr``'s preconditions are checked with the bindings
    (`PathExpr.check`); a `Match` result carries those bindings.
    """

    __slots__ = ("expr",)

    def __init__(self, expr: Any) -> None:
        self.expr: PathExpr | PathUnion = (
            expr if isinstance(expr, PathUnion) else _coerce(expr, at_head=True)
        )

    def __repr__(self) -> str:
        return f"PathOf({self.expr.pattern!r})"

    def validate(self, value: Any) -> tuple[str, Match]:
        """The path ``value`` stands for and its reading, or a
        ``PydanticCustomError``. A declaration that cannot be used this way
        (``NotInvertibleError``) is raised as it is."""
        expr = self.expr
        s = _text(value)
        if s is not None:
            try:
                m = expr.match(s)
            except AmbiguousMatchError as e:
                raise _error("wend_ambiguous", e) from None
            if m is None:
                raise PydanticCustomError(
                    "wend_no_match",
                    "{path} does not match {pattern}",
                    {"path": s, "pattern": expr.pattern},
                )
            if isinstance(m, AltMatch):  # a union's reading names its alternative
                target = m.expr
            else:
                assert isinstance(expr, PathExpr)
                target = expr
        else:
            try:
                env = bindings(value)
            except TypeError as e:  # a value that is neither a path nor bindings
                raise _error("wend_bindings", e) from None
            try:
                s = expr.render(env)
            except (ValueError, ConditionError) as e:  # invalid or missing bindings
                raise _error("wend_render", e) from None
            target = expr if isinstance(expr, PathExpr) else expr.alternatives[0]
            names = target.param_names
            m = Match(s, {**target.defaults, **{k: env[k] for k in env if k in names}})
        conds = target.conditions
        if conds is not None and conds.requires:
            try:
                check_conditions(s, conds.requires, m.bindings)
            except ConditionError as e:
                raise _error("wend_condition", e) from None
        return s, m

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        out = _output(source, repr(self))

        def validate(value: Any) -> Any:
            return out(*self.validate(value))

        return core_schema.no_info_plain_validator_function(
            validate,
            json_schema_input_schema=core_schema.str_schema(),
            serialization=_SERIALIZER,
        )

    def __get_pydantic_json_schema__(
        self, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> dict[str, Any]:
        js = handler.resolve_ref_schema(handler(schema))
        js["format"] = "path"
        js["x-wend-pattern"] = self.expr.pattern
        return js


def condition_schema(
    c: Condition, source: Any, handler: GetCoreSchemaHandler
) -> core_schema.CoreSchema:
    """The schema of a path field annotated with the condition ``c``: the
    field's own schema, then a check of ``c`` against the filesystem."""
    if isinstance(c, Under) and c.base.param_names:
        raise TypeError(
            f"{c!r} needs bindings for {sorted(c.base.param_names)}: declare it"
            " on an expression and annotate the field with PathOf(expr)"
        )
    conds = (c,)

    def check(v: Any) -> Any:
        s = _text(v)
        if s is None:
            raise PydanticCustomError(
                "wend_condition", "{value} is not a path", {"value": repr(v)}
            )
        env = v.bindings if isinstance(v, Match) else {}
        try:
            check_conditions(s, conds, env)
        except ConditionError as e:
            raise _error("wend_condition", e) from None
        return v

    return core_schema.no_info_after_validator_function(check, handler(source))
