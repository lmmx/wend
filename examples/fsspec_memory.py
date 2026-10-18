"""A partitioned dataset in object storage: discover, check for gaps, infer.

fsspec's memory filesystem stands in for a bucket, so this runs without a
network. With s3fs installed, ``url_to_fs("s3://bucket/events")`` works the
same way: the expressions and calls below do not change.
"""

import datetime as dt

from wend import Param, T
from wend.fs import url_to_fs
from wend.infer import infer


# The URL splits into a filesystem and a path in its namespace, bound as the
# root. ("memory://..." is "/..."; "s3://bucket/x" would be "bucket/x".)
fs, root = url_to_fs("memory://wend-example/events")
print("root:", root)

events, year, month, day = (
    Param("events"),
    Param("year", type=int),
    Param("month", type=int),
    Param("day", type=int),
)
part = (
    events
    / T(t"year={year:d}")
    / T(t"month={month:02d}")
    / T(t"day={day:02d}")
    / "part-0.parquet"
)

# A writer that skipped two days in March.
store = fs.fs  # the fsspec filesystem itself
start = dt.date(2026, 2, 20)
for i in range(30):
    d = start + dt.timedelta(days=i)
    if d not in (dt.date(2026, 3, 4), dt.date(2026, 3, 11)):
        store.pipe(part.render(events=root, year=d.year, month=d.month, day=d.day), b"")

try:
    # Binding year and month extends the literal prefix, so the store is
    # listed once, below .../year=2026/month=03, and matched in memory.
    march = part.glob(events=root, year=2026, month=3, fs=fs)
    days = [m["day"] for m in march]
    print("march days:", days)
    print("missing:", sorted(set(range(1, max(days) + 1)) - set(days)))

    # Inference reads the same store with one listing.
    print(infer(root, fs=fs))
finally:
    store.rm("/wend-example", recursive=True)
