"""Bindings from objects: a dataclass, attrs or Pydantic instance, a named
tuple, or any object with instance attributes, binds by field name.

Everything that takes a mapping of bindings (``render``, ``resolve``,
``bind``, ``glob``, ``check``, compiled renderers, unions, lenses, steps,
``Ledger.run``) takes such an object in its place, and reads exactly what
`bindings` reads.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from typing import Any


# How a class's instances give their bindings, decided once per class: the
# declared field names (dataclass, attrs, named tuple), the fields of a
# Pydantic model (plus each instance's extra fields), the mapping protocol,
# or the instance dictionary.
_FIELDS, _PYDANTIC, _KEYS, _VARS = "fields", "pydantic", "keys", "vars"
_PLANS: dict[type, tuple[str, tuple[str, ...]]] = {}
_PLANS_SIZE = 1024  # bounded, so classes made on the fly are not kept forever


def _plan(obj: Any) -> tuple[str, tuple[str, ...]]:
    cls = type(obj)
    if isinstance(obj, type):
        raise TypeError(
            f"Cannot take bindings from the class {obj.__name__}: pass an instance"
        )
    if isinstance(obj, (str, bytes, bytearray, os.PathLike)):
        raise TypeError(
            f"Cannot take bindings from {obj!r}: bind a path by name,"
            " e.g. render(root=path), or pass a mapping"
        )
    if dataclasses.is_dataclass(cls):
        return _FIELDS, tuple(f.name for f in dataclasses.fields(cls))
    attrs = getattr(cls, "__attrs_attrs__", None)
    if attrs is not None:
        return _FIELDS, tuple(a.name for a in attrs)
    fields = getattr(cls, "__pydantic_fields__", None)
    if isinstance(fields, dict):  # a Pydantic (v2) model
        return _PYDANTIC, tuple(fields)
    named = getattr(cls, "_fields", None)
    if issubclass(cls, tuple) and isinstance(named, tuple):
        return _FIELDS, named  # a named tuple
    if callable(getattr(cls, "keys", None)) and hasattr(cls, "__getitem__"):
        return _KEYS, ()
    if hasattr(obj, "__dict__"):
        return _VARS, ()
    raise TypeError(
        f"Cannot take bindings from {cls.__name__}: pass a mapping, a"
        " dataclass, attrs or Pydantic instance, or an object with attributes"
    )


def object_bindings(obj: Any) -> Mapping[Any, Any]:
    """What ``obj``, which is not a mapping, binds when it is given where a
    mapping of bindings is expected:

    - a dataclass, attrs or Pydantic instance (its fields, and a model's
      extra fields) or a named tuple: its declared fields, skipping any not
      set;
    - an object with ``keys()`` and ``__getitem__`` (the protocol ``dict()``
      accepts): its items;
    - any other object with a ``__dict__``: its instance attributes, as
      ``vars(obj)`` gives them.

    Properties, methods and Pydantic computed fields bind nothing. So a
    parameter named like a method (``copy``, ``count``) cannot pick it up,
    and a computed field can render a path from its own model
    (``CONFIG.resolve(self)``) without reading itself.
    """
    cls = type(obj)
    plan = _PLANS.get(cls)
    if plan is None:
        plan = _plan(obj)
        if len(_PLANS) >= _PLANS_SIZE:
            _PLANS.clear()
        _PLANS[cls] = plan
    how, names = plan
    if how is _KEYS:
        return {k: obj[k] for k in obj.keys()}
    if how is _VARS:
        return dict(vars(obj))
    out: dict[str, Any] = {}
    for n in names:
        try:
            out[n] = getattr(obj, n)
        except AttributeError:
            pass  # a field that is not set (init=False, no default)
    if how is _PYDANTIC:
        extra = obj.__pydantic_extra__
        if extra:
            out.update(extra)
    return out


def bindings(source: Any = None, /, **overrides: Any) -> dict[str, Any]:
    """The bindings ``source`` gives, as a dict keyed by parameter name, with
    ``overrides`` taking precedence.

    ``source`` is what every rendering and binding method takes: a mapping
    (keyed by name or by `Param`), or an object whose fields bind by name (a
    dataclass, attrs or Pydantic instance, a named tuple, or any object's
    instance attributes; see `object_bindings`)::

        @dataclass
        class Run:
            root: Path
            split: str

        shard.render(Run("/mnt", "train"), idx=7)  # the same as
        shard.render(bindings(Run("/mnt", "train"), idx=7))

    The result is a snapshot. It includes fields no expression uses; those
    are ignored where it is used.
    """
    from ._expr import _make_env

    return _make_env(source, overrides)
