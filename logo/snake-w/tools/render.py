"""Render a spline spec through the real scene: colour (still-spline.html) and clay / zebra
(diag-clay.html) for the full frame, the right valley and a tight crop of the blue curl.
Usage (from logo/): render.py TAG spec.json [views-json]"""
import json, subprocess, sys, shutil, os
tag, spec = sys.argv[1], sys.argv[2]
views = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {"full": [0, 0, 1448, 1086], "rvalley": [800, 540, 1080, 800], "curl": [860, 610, 1010, 760], "lvalley": [420, 560, 700, 800]}
os.makedirs("jfit/r", exist_ok=True)
name = f"spline-{tag}.json"
if spec == "-":   # the baseline: the old body (geometry.js centrelines), through the same pages
    name = None
elif os.path.abspath(spec) != os.path.abspath(f"snakes/{name}"):
    shutil.copy(spec, f"snakes/{name}")
withspec = (lambda q: {**q, "spec": name}) if name else (lambda q: {k: v for k, v in q.items() if k != "spec"})
look = open("snakes/w-final.look.json").read()
cj = {"query": {"look": look, "ss": "2", "heads": "heads-final.json"}}
col = [{"out": f"../jfit/r/{tag}-colour.png", "params": "w-final.params.json", "query": withspec(cj["query"]), **({} if name else {"page": "still.html"})}]
json.dump(col, open(f"jfit/r/{tag}-colourjob.json", "w"))
dq = withspec({"look": look, "heads": "heads-final.json", "modes": "clay,zebra", "bars": "8", "ss": "2", "cs": "3", "views": json.dumps(views)})
json.dump([{"prefix": f"../jfit/r/{tag}-", "params": "w-final.params.json", "query": dq}], open(f"jfit/r/{tag}-diagjob.json", "w"))
# the 3/4 side view (yaw 35 degrees about the frame centre), colour and clay
col.append({"out": f"../jfit/r/{tag}-colour-side.png", "params": "w-final.params.json", "query": {**withspec(cj["query"]), "yaw": "35"}, **({} if name else {"page": "still.html"})})
json.dump(col, open(f"jfit/r/{tag}-colourjob.json", "w"))
side = {**dq, "modes": "clay", "views": json.dumps({"side": [0, 0, 1448, 1086]}), "yaw": "35", "cs": "1"}
json.dump([{"prefix": f"../jfit/r/{tag}-", "params": "w-final.params.json", "query": dq},
           {"prefix": f"../jfit/r/{tag}-", "params": "w-final.params.json", "query": side}], open(f"jfit/r/{tag}-diagjob.json", "w"))
subprocess.run(["node", "../tools/spline_batch.mjs", f"../jfit/r/{tag}-colourjob.json"], cwd="snakes", check=True)
subprocess.run(["node", "../tools/diag_still.mjs", "--jobs", f"../jfit/r/{tag}-diagjob.json"], cwd="snakes", check=True)
