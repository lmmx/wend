"""Symbolic, typed, invertible filesystem paths built from Python t-strings.

A path expression records how a path is built (which parts are literal, which
are parameters, how values are formatted) instead of collapsing it to a
string. The same expression can be resolved with bindings, partially bound,
transformed structurally, matched against concrete paths, used to discover
files on disk, and compiled for fast batch resolution.
"""

from __future__ import annotations

from ._bindings import bindings
from ._compile import CompiledSet, compile_many
from ._expr import P, PathExpr, T, Text
from ._fs import glob
from ._kinds import Checked, Confirmed, IsFile, JoinBelowFile, NotFile, Unspecified
from ._lens import Lens, NoMatchError
from ._match import Match
from ._params import Absolute, AnyPath, Kind, Param, Segment, SubPath
from ._union import Alt, PathUnion, U
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
    IndeterminateError,
    InvalidBindingError,
    MissingBindingError,
    MissingPathError,
    NoAlternativeError,
    NotInvertibleError,
    NotStaticError,
    ParamConflictError,
    PathExistsError,
    PathOperationError,
    WendError,
    WrongKindError,
)
from .query import Query
from .templates import counter


__all__ = [
    "Absent",
    "Absolute",
    "Alt",
    "AmbiguousMatchError",
    "AnyPath",
    "CapabilityError",
    "Checked",
    "CompiledSet",
    "Condition",
    "ConditionError",
    "Confirmed",
    "ContainmentError",
    "Creatable",
    "Dir",
    "Exists",
    "File",
    "IndeterminateError",
    "InvalidBindingError",
    "IsFile",
    "JoinBelowFile",
    "Kind",
    "Lens",
    "Listable",
    "Match",
    "MissingBindingError",
    "MissingPathError",
    "NoAlternativeError",
    "NoMatchError",
    "NotFile",
    "NotInvertibleError",
    "NotStaticError",
    "P",
    "Param",
    "ParamConflictError",
    "PathExistsError",
    "PathExpr",
    "PathOperationError",
    "PathUnion",
    "Query",
    "Readable",
    "Segment",
    "Step",
    "SubPath",
    "T",
    "Text",
    "U",
    "Under",
    "Unspecified",
    "WendError",
    "Writable",
    "WrongKindError",
    "bindings",
    "compile_many",
    "counter",
    "glob",
]
