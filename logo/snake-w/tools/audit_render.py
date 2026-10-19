"""Render one candidate for the audit, through the real scene: colour (hero), clay and zebra of
the whole frame and of every registry feature's window (each rendered with its own camera, x2),
and the mesh check's visible fold / self-penetration points.
Usage (from the logo root): audit_render.py TAG spec.json|- OUTDIR [params.json]
  "-" renders the baseline (the old body, geometry.js centrelines)."""
import json, os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import window
tag, spec, out = sys.argv[1], sys.argv[2], sys.argv[3]
params = sys.argv[4] if len(sys.argv) > 4 else "w-final.params.json"   # a variant of the parametric body
os.makedirs(out, exist_ok=True)
reg = json.load(open("audit/registry.json"))
views = {"full": [0, 0, 1448, 1086]}
for f in reg["features"]:
    views[f["id"]] = list(window(f, 30))
views.update(json.loads(os.environ.get("VIEWS_EXTRA", "{}")))   # more windows: {"name": [x0, y0, x1, y1]}
look = open(os.environ.get("LOOK", "snakes/w-final.look.json")).read()   # LOOK: a look variant (a render-only experiment)
name = None
if spec != "-":
    name = f"spline-audit-{tag}.json"
    shutil.copy(spec, f"snakes/{name}")
rel = os.path.relpath(out, "snakes")
q = {"look": look, "ss": "2", "heads": "heads-final.json"}
# EXTRA: a file in snakes/ with scene.js's extra {cut, meshes} (tools/cushions.py): the region's
# tube is cut out and its meshes put in place (the mesh check below sees the cut tube only)
if os.environ.get("EXTRA"):
    q["extra"] = os.environ["EXTRA"]
col = {"out": f"{rel}/{tag}-colour.png", "params": params, "query": {**q, **({"spec": name} if name else {})}}
if not name:
    col["page"] = "still.html"
json.dump([col], open(f"{out}/{tag}-colourjob.json", "w"))
dq = {"look": look, "heads": "heads-final.json", "modes": "clay,zebra", "bars": "8", "ss": "2", "cs": "2", "views": json.dumps(views)}
if name:
    dq["spec"] = name
if os.environ.get("EXTRA"):
    dq["extra"] = os.environ["EXTRA"]
json.dump([{"prefix": f"{rel}/{tag}-", "params": params, "query": dq}], open(f"{out}/{tag}-diagjob.json", "w"))
subprocess.run(["node", "../tools/spline_batch.mjs", f"{rel}/{tag}-colourjob.json"], cwd="snakes", check=True, capture_output=True)
subprocess.run(["node", "../tools/diag_still.mjs", "--jobs", f"{rel}/{tag}-diagjob.json"], cwd="snakes", check=True, capture_output=True)
mc = ["node", "../tools/mesh_check.mjs", params, name or "-", "0,0,1448,1086", "--dump", f"{rel}/{tag}-mesh.json"]
r = subprocess.run(mc, cwd="snakes", check=True, capture_output=True, text=True)
open(f"{out}/{tag}-meshsummary.json", "w").write(r.stdout)
print("rendered", tag)
