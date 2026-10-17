"""Symbolic, typed, invertible filesystem paths built from Python t-strings.

A path expression records how a path is built (which parts are literal, which
are parameters, how values are formatted) instead of collapsing it to a
string. The same expression can be resolved with bindings, partially bound,
transformed structurally, matched against concrete paths, and compiled for
fast resolution.
"""

from __future__ import annotations

from ._expr import P, PathExpr, T, Text
from ._match import Match
from ._params import Absolute, AnyPath, Kind, Param, Segment, SubPath
from .errors import (
    AmbiguousMatchError,
    InvalidBindingError,
    MissingBindingError,
    NotInvertibleError,
    NotStaticError,
    ParamConflictError,
    PathOperationError,
    WendError,
)


__all__ = [
    "Absolute",
    "AmbiguousMatchError",
    "AnyPath",
    "InvalidBindingError",
    "Kind",
    "Match",
    "MissingBindingError",
    "NotInvertibleError",
    "NotStaticError",
    "P",
    "Param",
    "ParamConflictError",
    "PathExpr",
    "PathOperationError",
    "Segment",
    "SubPath",
    "T",
    "Text",
    "WendError",
]
