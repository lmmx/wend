"""A project's directory layout declared once, bound per environment.

Module-level expressions describe where things live relative to a root that
is not known yet. Production binds the real root at startup; tests bind a
temporary directory. Relations between paths survive, so code can ask where
something lives relative to something else without any bindings.
"""

import tempfile

from wend import Param, T


ROOT = Param("root")
RUN = Param("run")
CONFIG = ROOT / "config" / "settings.yaml"
DATA = ROOT / "data"
RAW = DATA / "raw" / T(t"{Param('day')}.csv")
CHECKPOINT = ROOT / "runs" / RUN / T(t"epoch_{Param('epoch', type=int):03d}.pt")

print("checkpoint layout:", CHECKPOINT)
print("relative to root:", CHECKPOINT.relative_to(ROOT))
print("run directory:", CHECKPOINT.parent)
print("needs:", sorted(CHECKPOINT.required_params()))

# Production: bind the root once, at startup.
prod = {
    name: expr.bind(root="/srv/app")
    for name, expr in [("config", CONFIG), ("raw", RAW)]
}
print("prod config:", prod["config"].resolve())

# A test: same declarations, a temporary root.
with tempfile.TemporaryDirectory() as tmp:
    cfg = CONFIG.bind(root=tmp)
    print("test config is under tmp:", cfg.resolve().is_relative_to(tmp))
    print("rebased raw:", RAW.rebase(DATA, "/mnt/archive").render(day="2026-10-17"))
