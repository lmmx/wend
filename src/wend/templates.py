"""Readymade templates: counter filename patterns.

Part 3 of Future Paths observes that sized and unsized counters are the same
few t-strings written again and again. `counter` writes them once::

    counter("log", width=5, suffix=".parquet")
    # PathExpr('log_{idx:05d}.parquet')
    counter("chunk", width=3, of_total=True, suffix=".parquet")
    # PathExpr('chunk_{idx:03d}-of-{total:03d}.parquet')

A counter is an ordinary one-segment expression: join it below a directory,
render it, match it, glob it. Its parameters are integers formatted with
``d``, so matching parses them back as ``int``, and a literal after each field
that does not start with a digit keeps matching on its single-parse fast path.
"""

from __future__ import annotations

from string.templatelib import Interpolation, Template
from typing import Any

from ._expr import PathExpr, T
from ._params import Param


__all__ = ["counter"]


def _int_param(p: str | Param) -> Param:
    if isinstance(p, Param):
        return p
    if isinstance(p, str):
        return Param(p, type=int)
    raise TypeError(f"A counter's parameter is a name or a Param, not {p!r}")


def counter(
    stem: str = "",
    *,
    width: int | None = None,
    suffix: str = "",
    of_total: bool = False,
    sep: str = "_",
    of: str = "-of-",
    idx: str | Param = "idx",
    total: str | Param = "total",
) -> PathExpr:
    """A counter filename: ``{stem}{sep}{idx}{suffix}``, or, with
    ``of_total``, ``{stem}{sep}{idx}{of}{total}{suffix}`` (a *sized* counter,
    which says how many there are).

    ``width`` zero-pads every number to that many digits (``{idx:04d}``);
    without it they are unpadded (``{idx:d}``). ``sep`` is only written when
    there is a stem. ``idx`` and ``total`` name the parameters, or are
    `Param`s to use (declared ``type=int`` by default), so a declared default
    carries over: ``counter("chunk", of_total=True, total=Param("total",
    type=int, default=10))``.
    """
    if width is not None and (type(width) is not int or width < 1):
        raise ValueError(f"width must be a positive int, not {width!r}")
    for label, text in (("stem", stem), ("suffix", suffix), ("sep", sep), ("of", of)):
        if not isinstance(text, str):
            raise TypeError(f"{label} must be a str, not {text!r}")
        if "/" in text:
            raise ValueError(f"A counter is one segment: {label}={text!r} has a '/'")
    spec = "d" if width is None else f"0{width}d"
    pieces: list[Any] = [stem + sep if stem else ""]
    pieces.append(Interpolation(_int_param(idx), "idx", None, spec))
    if of_total:
        pieces.append(of)
        pieces.append(Interpolation(_int_param(total), "total", None, spec))
    pieces.append(suffix)
    return T(Template(*pieces))
