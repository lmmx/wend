"""Symbolic, typed, invertible filesystem paths built from Python t-strings.

A path expression records how a path is built (which parts are literal, which
are parameters, how values are formatted) instead of collapsing it to a
string. The same expression can be resolved with bindings, partially bound,
transformed structurally, matched against concrete paths, used to discover
files on disk, and compiled for fast batch resolution.
"""

from __future__ import annotations

from ._expr import P, PathExpr, T, Text
from ._fs import glob
from ._lens import Lens, NoMatchError
from ._match import Match
from ._params import Absolute, AnyPath, Kind, Param, Segment, SubPath
from .conditions import (
    Absent,
    Condition,
    Creatable,
    Dir,
    Exists,
    File,
    Listable,
    Readable,
    Step,
    Under,
    Writable,
)
from .errors import (
    AmbiguousMatchError,
    CapabilityError,
    ConditionError,
    ContainmentError,
    InvalidBindingError,
    MissingBindingError,
    MissingPathError,
    NotInvertibleError,
    NotStaticError,
    ParamConflictError,
    PathExistsError,
    PathOperationError,
    WendError,
    WrongKindError,
)


__all__ = [
    "Absent",
    "Absolute",
    "AmbiguousMatchError",
    "AnyPath",
    "CapabilityError",
    "Condition",
    "ConditionError",
    "ContainmentError",
    "Creatable",
    "Dir",
    "Exists",
    "File",
    "InvalidBindingError",
    "Kind",
    "Lens",
    "Listable",
    "Match",
    "MissingBindingError",
    "MissingPathError",
    "NoMatchError",
    "NotInvertibleError",
    "NotStaticError",
    "P",
    "Param",
    "ParamConflictError",
    "PathExistsError",
    "PathExpr",
    "PathOperationError",
    "Readable",
    "Segment",
    "Step",
    "SubPath",
    "T",
    "Text",
    "Under",
    "WendError",
    "Writable",
    "WrongKindError",
    "glob",
]
