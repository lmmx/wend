# wend.anchors

Anchors: the standard places a path starts from, read from the environment only when asked.

Each anchor is an `Absolute` parameter named after its environment variable, so an expression built on one stays symbolic, portable and matchable::

```text
from wend import anchors
from wend.anchors import XDG

models = (P("models") / Param("name")).under(XDG.CACHE_HOME / "myapp")
models  # PathExpr('{XDG_CACHE_HOME}/myapp/models/{name}')
models.render(anchors.bindings(), name="bert")  # reads the environment now
```

`render` stays pure: nothing here is read until `bindings` is called, and a test binds the anchors like any parameter (`XDG_CACHE_HOME="/tmp/c"`).

The XDG directories follow the XDG Base Directory specification on every POSIX platform, macOS included: the variable when it is set to an absolute path, otherwise the specification's default below the home directory. For platform conventions instead (`~/Library/Caches` on macOS), bind the anchor to what a library such as platformdirs reports.

## CWD

```python
CWD: Final = Absolute('CWD')
```

The process's working directory, `os.getcwd()` (not `$PWD`).

## HOME

```python
HOME: Final = Absolute('HOME')
```

The user's home directory: `$HOME`, else the password database.

## XDG

```python
XDG()
```

The XDG base directories (anchors, not values): `XDG.CACHE_HOME / "myapp"` is `{XDG_CACHE_HOME}/myapp`.

### CONFIG\_HOME

```python
CONFIG_HOME: Final = Absolute('XDG_CONFIG_HOME')
```

User configuration: `$XDG_CONFIG_HOME`, else `~/.config`.

### DATA\_HOME

```python
DATA_HOME: Final = Absolute('XDG_DATA_HOME')
```

User data: `$XDG_DATA_HOME`, else `~/.local/share`.

### STATE\_HOME

```python
STATE_HOME: Final = Absolute('XDG_STATE_HOME')
```

User state (logs, history): `$XDG_STATE_HOME`, else `~/.local/state`.

### CACHE\_HOME

```python
CACHE_HOME: Final = Absolute('XDG_CACHE_HOME')
```

User caches: `$XDG_CACHE_HOME`, else `~/.cache`.

## bindings

```python
bindings(environ: Mapping[str, str] | None = None) -> dict[str, Any]
```

Every anchor's value, read now: an effect, unlike `render`.

`environ` defaults to `os.environ`. A variable that is unset, empty or relative falls back to its default, as the XDG specification requires. `CWD` is `os.getcwd()`, and is left out if the working directory no longer exists, so only an expression that uses it fails to render.
