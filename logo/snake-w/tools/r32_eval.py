"""Round 32: evaluate the collar-fit candidates the way the loop evaluates any candidate, with the
existing gates; geodiag alongside, advisory. Real renders (the incumbent's look and overlay),
evaluate.py, autoround.gates against the incumbent, the targets' own change, geodiag against the
incumbent's diagnosis, the delta sheet, the defect close-ups and the blind pair pages.
Usage (from the logo root): r32_eval.py TAG=SPEC [TAG=SPEC ...]"""
import json, os, random, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autoround as AR

R = "auto/r32"
S = json.load(open(AR.STATE)); inc = S["incumbent"]
mb = json.load(open(inc["metrics"]))
TARGETS = ["L01", "L15", "L16", "H1", "H2"]
out = json.load(open(f"{R}/summary.json")) if os.path.exists(f"{R}/summary.json") else {"round": "r32", "incumbent": inc["tag"], "targets": {}}
mapping = json.load(open(f"{R}/mapping.json")) if os.path.exists(f"{R}/mapping.json") else {}
for arg in sys.argv[1:]:
    tag, spec = arg.split("=")
    if not os.path.exists(f"{R}/metrics-{tag}.json"):
        AR.render_and_measure(tag, spec, f"{R}/renders", R, inc.get("params", AR.P0), inc.get("look"), inc.get("extra"))
    mc = json.load(open(f"{R}/metrics-{tag}.json"))
    fails, gains = AR.gates(mc, mb)
    tg = {f: dict(iou=[round(mb["features"][f]["iou"], 3), round(mc["features"][f]["iou"], 3)], p95=[round(mb["features"][f]["sdist"]["p95"], 1), round(mc["features"][f]["sdist"]["p95"], 1)],
                  sev=[mb["features"][f]["severity"], mc["features"][f]["severity"]], crease=[mb["features"][f].get("crease"), mc["features"][f].get("crease")]) for f in TARGETS}
    gd = AR.geodiag_of(tag, f"{R}/renders", R, spec, inc.get("extra"), inc.get("geodiag"), inc.get("params", AR.P0))
    AR.run([AR.PY, "tools/delta_sheet.py", inc["renders"], inc["tag"], f"{R}/renders", tag, f"{R}/delta-{tag}.png", f"{tag} against {inc['tag']}"], f"{R}/{tag}.log")
    AR.run([AR.PY, "tools/collar_sheet.py", f"{R}/closeups-{tag}.png", f"{tag} vs the incumbent {inc['tag']}: the three defects (real renders)",
            f"{inc['renders']}/{inc['tag']}", f"{R}/renders/{tag}"], f"{R}/{tag}.log")
    if tag not in mapping:
        xy = [inc["tag"], tag]; random.shuffle(xy); mapping[tag] = {"X": xy[0], "Y": xy[1]}
    xy = [mapping[tag]["X"], mapping[tag]["Y"]]; src = {inc["tag"]: inc["renders"], tag: f"{R}/renders"}
    AR.run([AR.PY, "tools/pair_pages.py", src[xy[0]], xy[0], src[xy[1]], xy[1], f"{R}/pair-{tag}", "--focus", "L01,L16,H2|L16"], f"{R}/{tag}.log")
    out["targets"][tag] = dict(tag=tag, spec=spec, gate_fails=fails, gains=gains, verdict_gates="REJECT" if fails else "pass", targets=tg,
                               geodiag=dict(path=f"{R}/geodiag-{tag}.json", **{k: gd["summary"][k] for k in ("new", "regressed", "resolved")},
                                            improved=[f"{f['region']}:{f['check']}" for f in gd["findings"] if f.get("status") == "improved"]))
    print(tag, "gates:", "pass" if not fails else fails, "| gains", gains)
    for f, v in tg.items(): print("  ", f, v)
    print("  geodiag:", out["targets"][tag]["geodiag"])
json.dump(mapping, open(f"{R}/mapping.json", "w"), indent=1)
json.dump(out, open(f"{R}/summary.json", "w"), indent=1, default=float)
