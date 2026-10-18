"""The autonomous loop's ledger (auto/LEDGER.md), built from auto/state.json, each round's
summary.json and the blind judges' verdicts. A verdict file is auto/ROUND/judge-TAG.md; its
first line reads "verdict: ACCEPT|REJECT". Per round, the file gives:
  - the incumbent;
  - the ranking's top 8, discovered (tools/discrepancy.py);
  - each target with its station run (attribution), the handle's settings, the target's IoU and
    worst contour arc before -> after (real renders), the gates and the judge;
  - the outcome.
Usage (from the logo root): autoledger.py"""
import json, os

S = json.load(open("auto/state.json"))
out = ["# Autonomous correction loop: ledger", "",
       "Each round: rank every lobe of the incumbent's real render by its discrepancy from the reference (tools/discrepancy.py); "
       "take the top targets that are not each other's neighbours; attribute each to the run of strand stations that draws it "
       "(the surface-point buffer, tools/lobekit.py); fit that run's lobe handle with the neighbours guarded (tools/lobefit.py); "
       "render for real, measure, gate (tools/autoround.py); blind paired judge (images only); accept or reject; merge the accepted.", ""]
rounds = sorted(d for d in os.listdir("auto") if d.startswith("r") and os.path.isdir(f"auto/{d}") and os.path.exists(f"auto/{d}/summary.json"))
done = {r["round"]: r for r in S["rounds"]}
for rd in rounds:
    sm = json.load(open(f"auto/{rd}/summary.json"))
    rank = json.load(open(f"auto/{rd}/rank.json"))
    out += [f"## Round {rd} (incumbent {sm['incumbent']})", "", "Ranking (top 8):", ""]
    for k, r in enumerate([r for r in rank if r["id"].startswith("L")][:8]):
        out.append(f"{k + 1}. {r['id']} score {r['score']:.1f}: IoU {r['iou']:.2f}, {r['what']}")
    out += ["", "| target | station run | handle | IoU | worst arc | gates | judge | verdict |", "|---|---|---|---|---|---|---|---|"]
    for t, s in sm["targets"].items():
        if "tag" not in s:
            out.append(f"| {t} | {s.get('attribution', {}).get('error', '?')} | - | - | - | - | - | not controllable |"); continue
        a = s["attribution"]; tb, ta = s["target_before"], s["target_after"]
        jf = f"auto/{rd}/judge-{s['tag']}.md"
        jv = open(jf).readline().split(":", 1)[1].strip() if os.path.exists(jf) else "-"
        g = "pass" if not s["gate_fails"] else "fail: " + "; ".join(s["gate_fails"])
        acc = done.get(rd, {}).get("accepted", None)
        verdict = "-" if acc is None else ("ACCEPT" if t in acc else "REJECT")
        out.append(f"| {t} | {a['strand']} {a['a']:.0f}-{a['b']:.0f} | {s['describe']} | {tb['iou']:.2f} -> {ta['iou']:.2f} | {tb['arc']:+.0f} -> {ta['arc']:+.0f} | {g} | {jv} | {verdict} |")
    if rd in done:
        out += ["", f"Outcome: {done[rd].get('verdict', '-')}"]
    out.append("")
out.append(f"Current incumbent: {S['incumbent']['tag']} ({S['incumbent']['spec']})")
open("auto/LEDGER.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
