"""Anchors: the standard places a path starts from, read from the environment
only when asked.

Each anchor is an `Absolute` parameter named after its environment variable,
so an expression built on one stays symbolic, portable and matchable::

    from wend import anchors
    from wend.anchors import XDG

    models = (P("models") / Param("name")).under(XDG.CACHE_HOME / "myapp")
    models  # PathExpr('{XDG_CACHE_HOME}/myapp/models/{name}')
    models.render(anchors.bindings(), name="bert")  # reads the environment now

`render` stays pure: nothing here is read until `bindings` is called, and a
test binds the anchors like any parameter (``XDG_CACHE_HOME="/tmp/c"``).

The XDG directories follow the XDG Base Directory specification on every
POSIX platform, macOS included: the variable when it is set to an absolute
path, otherwise the specification's default below the home directory. For
platform conventions instead (``~/Library/Caches`` on macOS), bind the anchor
to what a library such as platformdirs reports.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Final

from ._params import Absolute, Param


__all__ = ["CWD", "HOME", "XDG", "bindings"]


HOME: Final = Absolute("HOME")
"""The user's home directory: ``$HOME``, else the password database."""

CWD: Final = Absolute("CWD")
"""The process's working directory, ``os.getcwd()`` (not ``$PWD``)."""


class XDG:
    """The XDG base directories (anchors, not values): ``XDG.CACHE_HOME /
    "myapp"`` is ``{XDG_CACHE_HOME}/myapp``."""

    CONFIG_HOME: Final = Absolute("XDG_CONFIG_HOME")
    """User configuration: ``$XDG_CONFIG_HOME``, else ``~/.config``."""

    DATA_HOME: Final = Absolute("XDG_DATA_HOME")
    """User data: ``$XDG_DATA_HOME``, else ``~/.local/share``."""

    STATE_HOME: Final = Absolute("XDG_STATE_HOME")
    """User state (logs, history): ``$XDG_STATE_HOME``, else ``~/.local/state``."""

    CACHE_HOME: Final = Absolute("XDG_CACHE_HOME")
    """User caches: ``$XDG_CACHE_HOME``, else ``~/.cache``."""

    def __init__(self) -> None:
        raise TypeError("XDG is a namespace of anchors")


_XDG_DEFAULTS: dict[Param, str] = {
    XDG.CONFIG_HOME: ".config",
    XDG.DATA_HOME: ".local/share",
    XDG.STATE_HOME: ".local/state",
    XDG.CACHE_HOME: ".cache",
}

ANCHORS: Final = (HOME, CWD, *_XDG_DEFAULTS)
"""Every anchor parameter."""


def _home(environ: Mapping[str, str]) -> str:
    home = environ.get("HOME")
    if home and os.path.isabs(home):
        return home
    import pwd

    return pwd.getpwuid(os.getuid()).pw_dir


def bindings(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Every anchor's value, read now: an effect, unlike `render`.

    ``environ`` defaults to ``os.environ``. A variable that is unset, empty or
    relative falls back to its default, as the XDG specification requires.
    ``CWD`` is ``os.getcwd()``, and is left out if the working directory no
    longer exists, so only an expression that uses it fails to render.
    """
    env = os.environ if environ is None else environ
    home = _home(env)
    out: dict[str, Any] = {HOME.name: home}
    try:
        out[CWD.name] = os.getcwd()
    except FileNotFoundError:
        pass
    for p, rel in _XDG_DEFAULTS.items():
        v = env.get(p.name)
        out[p.name] = v if v and os.path.isabs(v) else os.path.join(home, rel)
    return out
