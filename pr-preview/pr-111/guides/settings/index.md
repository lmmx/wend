# Settings and anchors

An application declares where its files live once, at module level, and binds the values when it starts, from its settings. This guide gives parameters defaults, binds them from settings objects, overrides them with keywords, and starts paths from the standard directories: the home directory, the working directory and the XDG base directories. It needs Python 3.14 and wend, with no extras. The Pydantic example also needs Pydantic, which the `pydantic` extra installs ([Installation](<https://lmmx.github.io/wend/pr-preview/pr-111/getting-started/installation/#extras>)). The examples build on each other: run them in order.

## Declare the paths, with defaults

```python
from wend import Param, Segment, T

root = Param("root")
env = Segment("env", choices={"dev", "prod"}, default="dev")
version = Param("version", type=int, default=1)

CONFIG = root / "config" / T(t"{env}.toml")
MODEL = root / "models" / T(t"v{version}") / Param("model")
```

A parameter with `default=` takes that value when a path is rendered without a binding for it:

```pycon
>>> CONFIG.render(root="/srv/app")
'/srv/app/config/dev.toml'
>>> CONFIG.render(root="/srv/app", env="prod")
'/srv/app/config/prod.toml'
>>> MODEL.defaults
{'version': 1}
>>> sorted(MODEL.required_params())
['model', 'root']
```

`defaults` gives the defaults by name, and `required_params` the parameters that must be bound. Defaults apply when a path is rendered and nowhere else: `bind` leaves a defaulted parameter free, and `match` and `glob` read its value from the path ([Parameters](<https://lmmx.github.io/wend/pr-preview/pr-111/concepts/parameters/#type-choices-and-default>)).

## Bind from a dataclass

Every method that takes a mapping of bindings also takes an object whose fields are named after the parameters:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    root: Path
    env: str = "prod"
    workers: int = 4
```

```pycon
>>> settings = Settings(Path("/srv/app"))
>>> CONFIG.resolve(settings)
PosixPath('/srv/app/config/prod.toml')
```

The field `env` is a binding, so its value `prod` is used in place of the parameter's default. `wend.bindings` shows what an object binds. Fields that no expression uses, such as `workers`, are ignored where the bindings are used.

```pycon
>>> from wend import bindings
>>> bindings(settings)
{'root': PosixPath('/srv/app'), 'env': 'prod', 'workers': 4}
```

## Override with keywords

Keyword bindings take precedence over an object's fields:

```pycon
>>> CONFIG.render(settings, env="dev")
'/srv/app/config/dev.toml'
>>> bindings(settings, env="dev")
{'root': PosixPath('/srv/app'), 'env': 'dev', 'workers': 4}
```

## Bind from a named tuple

A named tuple binds its fields in the same way:

```python
from typing import NamedTuple


class Job(NamedTuple):
    root: str
    model: str
    version: int = 2
```

```pycon
>>> MODEL.render(Job("/srv/app", "bert"))
'/srv/app/models/v2/bert'
```

## Bind from a Pydantic model

A Pydantic model binds its fields. Properties, methods and computed fields bind nothing, so a computed field can render a path from its own model:

```python
from pydantic import BaseModel, computed_field


class AppSettings(BaseModel):
    root: Path
    env: str = "dev"

    @computed_field
    @property
    def config(self) -> Path:
        return CONFIG.resolve(self)
```

```pycon
>>> app = AppSettings(root="/srv/app")
>>> app.config
PosixPath('/srv/app/config/dev.toml')
>>> bindings(app)
{'root': PosixPath('/srv/app'), 'env': 'dev'}
```

attrs classes, and any other object with instance attributes, bind the same way ([SEMANTICS.md §3.2](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#32-environments>)). A class, or a path given in place of the bindings, raises `TypeError`:

```pycon
>>> CONFIG.render("/srv/app")
Traceback (most recent call last):
  ...
TypeError: Cannot take bindings from '/srv/app': bind a path by name, e.g. render(root=path), or pass a mapping
```

## Start from a standard directory

`wend.anchors` provides the directories a path usually starts from: `HOME`, `CWD` and the XDG base directories in `XDG`. Each is an `Absolute` parameter named after its environment variable, so an expression built on one stays symbolic:

```pycon
>>> from wend import P
>>> from wend.anchors import CWD, HOME, XDG
>>> models = (P("models") / Param("model")).under(XDG.CACHE_HOME / "myapp")
>>> models
PathExpr('{XDG_CACHE_HOME}/myapp/models/{model}')
>>> HOME / ".myapp.toml"
PathExpr('{HOME}/.myapp.toml')
```

An anchor is bound like any parameter, which is how a test points the application at a temporary directory. An absolute path is required:

```pycon
>>> models.render(XDG_CACHE_HOME="/tmp/test-cache", model="bert")
'/tmp/test-cache/myapp/models/bert'
>>> models.render(XDG_CACHE_HOME="cache", model="bert")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: XDG_CACHE_HOME='cache' must be an absolute path
```

## Read the anchors from the environment

`anchors.bindings` reads every anchor's value at the moment it is called. `render` never reads the environment itself. With no argument it reads `os.environ`. Given a mapping, it reads that instead:

```pycon
>>> from wend import anchors
>>> here = anchors.bindings({"HOME": "/home/ada"})
>>> for name, value in here.items():
...     if name != "CWD":
...         print(name, value)
HOME /home/ada
XDG_CONFIG_HOME /home/ada/.config
XDG_DATA_HOME /home/ada/.local/share
XDG_STATE_HOME /home/ada/.local/state
XDG_CACHE_HOME /home/ada/.cache
>>> models.render(here, model="bert")
'/home/ada/.cache/myapp/models/bert'
```

- An XDG variable that is set to an absolute path is used. One that is unset, empty or relative falls back to its default below the home directory, as the XDG specification requires.
- `HOME` is `$HOME`, or the home directory from the password database.
- `CWD` is `os.getcwd()` when `bindings` is called.

```pycon
>>> models.render(
...     anchors.bindings({"HOME": "/home/ada", "XDG_CACHE_HOME": "/var/cache/ada"}),
...     model="bert",
... )
'/var/cache/ada/myapp/models/bert'
>>> models.render(
...     anchors.bindings({"HOME": "/home/ada", "XDG_CACHE_HOME": "cache"}), model="bert"
... )
'/home/ada/.cache/myapp/models/bert'
>>> import os
>>> anchors.bindings()["CWD"] == os.getcwd()
True
```

The expression stays symbolic, so a path below an anchor matches back to the anchor's value:

```pycon
>>> models.match("/home/ada/.cache/myapp/models/bert")
Match('/home/ada/.cache/myapp/models/bert', {'XDG_CACHE_HOME': '/home/ada/.cache', 'model': 'bert'})
```

The XDG anchors follow the XDG specification on every POSIX platform, macOS included. For a platform's own conventions, such as `~/Library/Caches` on macOS, bind the anchor to the directory that a library such as platformdirs reports.

## See also

- [Parameters](<https://lmmx.github.io/wend/pr-preview/pr-111/concepts/parameters/index.md>): `default=`, and the absolute kind.
- [Rendering and matching](<https://lmmx.github.io/wend/pr-preview/pr-111/concepts/matching/index.md>): the ways bindings can be given.
- [Pydantic](<https://lmmx.github.io/wend/pr-preview/pr-111/integrations/pydantic/index.md>): path fields on Pydantic models.
- [SEMANTICS.md §3.1](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#31-defaults>) (defaults) and [§3.2](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#32-environments>) (environments).
- API reference: `wend.bindings`, `PathExpr.defaults`, `wend.anchors`.
