"""Pipeline effects: what a pipeline's steps do to each other, before any binding.

Seven steps share one data root: ingest a day's CSV, clean it, featurise it,
summarise the cleaned data beside the features, train a model on everything in
the features directory, report on a day, and purge the raw CSV. Each step
declares its paths with conditions, and from those declarations alone wend works
out which step feeds which, the order to run them in, which may run at once, and
what to look out for, without binding a root or a day.

The graph promises only what the declarations say: a step whose code touches a
path it does not declare is outside it.
"""

from wend import (
    Absent,
    Creatable,
    Exists,
    File,
    Listable,
    P,
    Param,
    Readable,
    Step,
    T,
    relate,
)
from wend.effects import EffectGraph


root, day, model = Param("root"), Param("day", type=str), Param("model", type=str)
raw = P(root) / "raw" / T(t"{day}.csv")
clean = P(root) / "clean" / T(t"{day}.parquet")
features = P(root) / "features"
weights = P(root) / "models" / T(t"{model}.pkl")

steps = {
    "ingest": Step(out=raw.ensures(Exists)),
    "clean": Step(
        src=raw.requires(Readable), dst=clean.requires(Creatable).ensures(File)
    ),
    "featurise": Step(
        src=clean.requires(Readable),
        dst=(features / T(t"{day}.npz")).requires(Creatable).ensures(File),
    ),
    "stats": Step(
        src=clean.requires(Readable),
        out=(features / "summary.json").requires(Creatable).ensures(File),
    ),
    "train": Step(
        days=features.requires(Listable), out=weights.requires(Creatable).ensures(File)
    ),
    "report": Step(
        src=clean.requires(Readable),
        model=weights.requires(Readable),
        out=(P(root) / "reports" / T(t"{day}.html")).requires(Creatable).ensures(File),
    ),
    "purge": Step(old=raw.ensures(Absent)),
}

if __name__ == "__main__":
    # Two families of paths, related for every root and day at once.
    print("raw vs clean:      ", relate(raw, clean).kind)
    print("a day's features:  ", relate(features / T(t"{day}.npz"), features).kind)
    print(
        "another day's raw: ",
        relate(raw, P(root) / "raw" / T(t"{Param('d')}.csv")).kind,
    )

    # The data root exists before the pipeline runs; the directories below it
    # may not, and a step that creates a file may make its missing parents.
    graph = EffectGraph(steps, existing=[P(root)])
    print("\n" + repr(graph))
    print("order: ", graph.order())
    print("stages:", graph.stages())
    print("featurise and report independent:", graph.independent("featurise", "report"))
    for name in ("clean", "train", "purge", "stats"):
        print(f"\nwhy {name} is where it is:")
        for line in graph.explain(name):
            print(" -", line)

    # featurise and stats both check they may create a file in features/, which
    # either may be making: they run apart until features/ is known to exist.
    known = EffectGraph(steps, existing=[P(root), features])
    print("\nwith features/ existing too, stages:", known.stages())
    print("the pipeline's results:", [str(p) for p in graph.terminal_outputs()])
