"""Demo of symbolic path expressions."""

from wend import P, Param, SubPath, T


# Parameters are late-bound slots
root = Param("root")
dataset = Param("dataset")
idx = Param("idx", type=int)
total = Param("total", type=int)

# Build an expression; nothing touches the filesystem
chunk_file = root / "data" / dataset / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")
print(chunk_file)
# -> PathExpr('{root}/data/{dataset}/chunk_{idx:04d}-of-{total:04d}.parquet')

print("Required params:", sorted(chunk_file.required_params()))
# -> ['dataset', 'idx', 'root', 'total']

# Resolve with bindings
path = chunk_file.resolve(root="/mnt/storage", dataset="train", idx=7, total=100)
print("Resolved:", path)
# -> /mnt/storage/data/train/chunk_0007-of-0100.parquet

# ...and invert: match a concrete path back to typed bindings
print("Matched:", dict(chunk_file.match(path)))
# -> {'root': '/mnt/storage', 'dataset': 'train', 'idx': 7, 'total': 100}

# Structural operations need no bindings
print("Parent:", chunk_file.parent)  # -> PathExpr('{root}/data/{dataset}')
print("Suffix:", chunk_file.suffix)  # -> Text('.parquet')
print("Metadata:", chunk_file.with_suffix(".json"))

# Partial binding folds what becomes static
print("Partial:", chunk_file.bind(root="/mnt", total=100))
# -> PathExpr('/mnt/data/{dataset}/chunk_{idx:04d}-of-0100.parquet')

# Relations survive: rebase the whole tree onto a test directory
config = root / "config" / "settings.yaml"
print("Relative:", config.relative_to(root))  # -> PathExpr('config/settings.yaml')
print("Rebased:", config.rebase(root, "/tmp/test").render())
# -> /tmp/test/config/settings.yaml

# Values that would change the path's structure are rejected
try:
    chunk_file.render(root="/mnt", dataset="../../etc", idx=1, total=2)
except ValueError as e:
    print("Rejected:", e)

# Multi-segment parameters are declared explicitly; their parent is deferred
nested = P("/srv") / SubPath("rel") / "index.html"
print(nested.parent.parent, "->", nested.parent.parent.render(rel="a/b"))
