"""Directory schemas: declare a layout, scaffold it, validate it, infer it back.

The Future Paths MLProject: data, models and a config file, with checkpoints
numbered per run. The schema is declared once; a bound instance gives typed
paths, creates the directories, and reports how a tree departs from it.
"""

import os
import tempfile
from pathlib import Path

from wend import Dir, File, Param, T
from wend.infer import infer
from wend.schema import Tree, from_inferred


index = Param("index", type=int)


class MLProject(Tree):
    data = Dir("data")
    raw = Dir(data / "raw")
    processed = Dir(data / "processed")
    models = Dir("models")
    checkpoints = File(models / T(t"model-{index:03d}.pt"), many=True, optional=True)
    config = File("config.yaml")


with tempfile.TemporaryDirectory() as tmp:
    project = MLProject(tmp)
    print("config:", project.config)
    print("checkpoint 7:", Path(project.checkpoints.render(index=7)).relative_to(tmp))

    created = project.scaffold(files=True)
    print("\nscaffolded:", [p.relative_to(tmp).as_posix() for p in created])
    print("valid:", project.validate().ok)

    # A few mistakes: a stray checkpoint name, a config file in the wrong place,
    # and an undeclared directory.
    for name in ["models/model-001.pt", "models/model-2.pt", "data/raw/config.yaml"]:
        Path(tmp, name).write_text("")
    Path(tmp, "scratch").mkdir()
    print("\nafter some mistakes:")
    for problem in project.validate().problems:
        print(
            f"  {problem.kind:9} {os.path.relpath(problem.path, tmp):22} {problem.entry or ''}"
        )

    # Infer the layout of the tree as it is, and print it as a declaration.
    print("\ninferred from the tree:\n")
    print(from_inferred(infer(tmp), "Observed").source())
