"""Demo of deferred path expressions."""

from wend import P, Param, RelativePath, T


# Define parameters (late-bound)
root = Param("root")
dataset = Param("dataset")
idx = Param("idx")
total = Param("total")

# Build expressions - these don't touch the filesystem
data_dir = root / "data" / dataset
chunk_file = data_dir / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")

# Inspect what's needed
print("Required params:", chunk_file.required_params())
# -> {'root', 'dataset', 'idx', 'total'}

# Resolve with bindings
path = chunk_file.resolve(
    {
        "root": "/mnt/storage",
        "dataset": "train",
        "idx": 7,
        "total": 100,
    }
)
print("Resolved:", path)
# -> /mnt/storage/data/train/chunk_0007-of-0100.parquet

# Constant folding happens at construction
folded = P("/home") / "user" / "data"
print("Folded type:", type(folded).__name__)
# -> LiteralExpr (not nested JoinExprs)

# Parent simplification
expr = root / "a" / "b"
print("Parent of join:", expr.parent)
# -> JoinExpr(ParamExpr, LiteralExpr("a")) — the "b" is gone structurally

# Suffix chain collapse
double_suffix = (root / "file.txt").with_suffix(".tmp").with_suffix(".json")
print("Suffix chain:", double_suffix)
# -> WithSuffixExpr(base=JoinExpr(...), suffix='.json') — .tmp is gone

# Connectivity: rebasing
config = RelativePath(base=root, relative=P("config") / "settings.yaml")
print("Config path:", config.resolve({"root": "/project"}))
# -> /project/config/settings.yaml

# Rebase to test environment
test_config = config.rebase(P("/tmp/test"))
print("Test config:", test_config.resolve({}))
# -> /tmp/test/config/settings.yaml
