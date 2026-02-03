from pathlib import Path
from wend import P, RelativePath, Param

def test_relative_path_rebase():
    root = Param("root")

    rel = RelativePath(
        base=root,
        relative=P("config") / "settings.yaml",
    )

    rebased = rel.rebase(P("/tmp/test"))

    assert rebased.resolve() == Path("/tmp/test/config/settings.yaml")
