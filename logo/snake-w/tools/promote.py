"""Promote the loop's accepted incumbent to the production files, and render the production page
(index.html, the frozen production look) as the stable current-best render.

  snakes/w-final.spec.json   <- the incumbent's spec (the previous one kept in snakes/checkpoints/)
  snakes/w-final.extra.json  <- the incumbent's overlay (unchanged when it is the same file)
  snakes/heads-w-final.json  <- re-baked for the new spec (tools/bake_heads.mjs)
  progress/current-best/production.png, production.json

Only for an accepted incumbent (autoround merge). Usage (from the logo root): promote.py"""
import json, os, shutil, subprocess, time

S = json.load(open("auto/state.json")); inc = S["incumbent"]
prev = json.load(open("snakes/w-final.spec.json"))
new = json.load(open(inc["spec"]))
if prev != new:
    os.makedirs("snakes/checkpoints", exist_ok=True)
    shutil.copy("snakes/w-final.spec.json", f"snakes/checkpoints/w-final.spec.before-{inc['tag']}.json")
    json.dump(new, open("snakes/w-final.spec.json", "w"))
if inc.get("extra") and open(f"snakes/{inc['extra']}", "rb").read() != open("snakes/w-final.extra.json", "rb").read():
    shutil.copy("snakes/w-final.extra.json", f"snakes/checkpoints/w-final.extra.before-{inc['tag']}.json")
    shutil.copy(f"snakes/{inc['extra']}", "snakes/w-final.extra.json")
subprocess.run(["node", "../tools/bake_heads.mjs", "w-final.params.json", "heads-w-final.json", "w-final.spec.json"], cwd="snakes", check=True, capture_output=True)
os.makedirs("progress/current-best", exist_ok=True)
r = subprocess.run(["node", "../tools/check_page.mjs", "index.html", os.path.abspath("progress/current-best/production.png"), "1448", "1086"], cwd="snakes", check=True, capture_output=True, text=True)
errs = [l for l in r.stdout.splitlines() if "pageerror" in l or "warn" in l.lower()]
json.dump(dict(tag=inc["tag"], spec=inc["spec"], extra=inc.get("extra"), look="snakes/w-final.look.json", date=time.strftime("%Y-%m-%d"), page_messages=errs),
          open("progress/current-best/production.json", "w"), indent=1)
print("promoted", inc["tag"], "page messages:", errs or "none")
