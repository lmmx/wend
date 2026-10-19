"""One round of the autonomous correction loop. Everything except the blind judge, which is a
separate agent that sees only the pair pages.

  propose  1. Rank the incumbent's lobes (tools/discrepancy.py).
           2. Take up to N targets in rank order such that no target lies inside another's
              crop (each fit guards its crop).
           3. For each target:
              - fit it from the incumbent (tools/lobefit.py);
              - render it for real (tools/audit_render.py);
              - measure it (tools/evaluate.py);
              - check the ledger gates against the incumbent: no feature's severity up by 2, no
                IoU down by more than 0.08, the silhouette not down by more than 0.01, and the
                target itself must improve (IoU up 0.02 or the worst contour arc 3 px smaller);
              - build its delta sheet and its blind pair pages, with the X / Y order random and
                recorded in ROUND/mapping.json.
  merge    1. Compose the handles of the accepted targets onto the incumbent (their supports
              are disjoint).
           2. Render the result, measure it, and gate it.
           3. If the gates pass, it becomes the incumbent; record the judged rejections.

Only one autoround runs at a time (auto/LOCK holds its pid; a second one exits).
State: auto/state.json holds:
  incumbent  {tag, spec, renders, metrics, params}: params is the scene params file (snakes/) its
             renders use (the heads and necks; default w-final.params.json)
  tried      {fid: rejected attempts}; the ranking halves a feature's score per rejection
  rounds     the summary of every round

Usage (from the logo root):
  autoround.py propose ROUND [--n 3] [--gens 18]
  autoround.py merge ROUND TAG,TAG,... [--rejected TAG,...]"""
import argparse, json, os, random, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lobekit as K
from evaluate import window

PY = sys.executable
STATE = "auto/state.json"


def guards(fid, pad=80):
    f = K.FEATS[K.FIDS.index(fid)]
    x0, y0, x1, y1 = window(f, pad)
    out = set()
    for g in K.FEATS:
        bx = g["bbox"]
        ix = max(0, min(bx[2], x1) - max(bx[0], x0)) * max(0, min(bx[3], y1) - max(bx[1], y0))
        if g["id"] != fid and ix > 0.3 * (bx[2] - bx[0]) * (bx[3] - bx[1]):
            out.add(g["id"])
    return out


def run(cmd, log):
    with open(log, "a") as fh:
        fh.write("$ " + " ".join(cmd) + "\n"); fh.flush()
        subprocess.run(cmd, check=True, stdout=fh, stderr=subprocess.STDOUT)


def render_and_measure(tag, spec, rdir, mdir, params="w-final.params.json"):
    log = f"{mdir}/{tag}.log"
    run([PY, "tools/audit_render.py", tag, spec, rdir, params], log)
    run([PY, "tools/evaluate.py", f"{rdir}/{tag}-colour.png", "--clay", f"{rdir}/{tag}-clay-full.png", "--folds", f"{rdir}/{tag}-mesh.json",
         "--out", f"{mdir}/metrics-{tag}.json"], log)
    return json.load(open(f"{mdir}/metrics-{tag}.json"))


def gates(mc, mb, target=None, rank_c=None, rank_b=None):
    fails, gains = [], []
    for f in [g["id"] for g in K.FEATS]:
        a, b = mc["features"][f], mb["features"][f]
        dm = a["severity"] - b["severity"]; di = a.get("iou", 0) - b.get("iou", 0)
        # where the candidate's lobe split is flagged (merged / unstable: the watershed joined two
        # same-colour lobes, r5-L05's L04 + L06), its IoU measures the split, not the shape: gate on
        # the reference region's cover by the right colour instead, which needs no split
        if set(a.get("seg") or []) & {"merged", "unstable"} and (dm >= 2 or di < -0.08):
            dc = a["cover"]["same"] - b["cover"]["same"]
            if dc < -0.02:
                fails.append(f"{f}: split flagged {','.join(a['seg'])}; colour cover {b['cover']['same']:.3f} -> {a['cover']['same']:.3f}")
            continue
        if dm >= 2 or di < -0.08:
            fails.append(f"{f}: severity {b['severity']} -> {a['severity']}, IoU {b.get('iou', 0):.2f} -> {a.get('iou', 0):.2f}")
        elif dm < 0 or di > 0.02:
            gains.append(f"{f}: severity {b['severity']} -> {a['severity']}, IoU {b.get('iou', 0):.2f} -> {a.get('iou', 0):.2f}")
    ds = mc["global"]["silhouette_iou"] - mb["global"]["silhouette_iou"]
    if ds < -0.01:
        fails.append(f"silhouette IoU {mb['global']['silhouette_iou']:.3f} -> {mc['global']['silhouette_iou']:.3f}")
    if target:
        rc = next(r for r in rank_c if r["id"] == target); rb = next(r for r in rank_b if r["id"] == target)
        if not (rc["iou"] - rb["iou"] >= 0.02 or abs(rb["arc"]) - abs(rc["arc"]) >= 3):
            fails.append(f"{target} (the target) not improved: IoU {rb['iou']:.2f} -> {rc['iou']:.2f}, worst arc {rb['arc']:+.0f} -> {rc['arc']:+.0f} px")
    return fails, gains


def propose(A, S):
    inc = S["incumbent"]; R = f"auto/{A.round}"
    os.makedirs(f"{R}/renders", exist_ok=True)
    from discrepancy import rank, table
    sev = json.load(open("auto/sev.json")) if os.path.exists("auto/sev.json") else None
    rows = rank(f"{inc['renders']}/{inc['tag']}-colour.png", S["tried"], sev)
    json.dump(rows, open(f"{R}/rank.json", "w"), indent=1)
    open(f"{R}/rank.md", "w").write(f"Incumbent {inc['tag']}\n\n" + table(rows) + "\n")
    chosen = []
    for r in rows:
        if not r["id"].startswith("L") or len(chosen) >= A.n:
            continue
        if any(r["id"] in guards(c) or c in guards(r["id"]) for c in chosen):
            continue
        chosen.append(r["id"])
    print("targets", chosen, flush=True)
    summary = {"round": A.round, "incumbent": inc["tag"], "targets": {}}
    for t in chosen:
        run([PY, "tools/lobefit.py", t, inc["spec"], f"{R}/{t}", "--gens", str(A.gens)], f"{R}/{t}.log")
    def one(t):
        fit = json.load(open(f"{R}/{t}/fit.json"))
        if "handle" not in fit:
            return t, dict(verdict="not controllable", attribution=fit.get("attribution"))
        tag = f"{A.round}-{t}"
        mc = render_and_measure(tag, f"{R}/{t}/spec.json", f"{R}/renders", R, inc.get("params", "w-final.params.json"))
        return t, dict(tag=tag, fit=fit)
    with ThreadPoolExecutor(2) as ex:
        res = dict(ex.map(one, chosen))
    mb = json.load(open(inc["metrics"]))
    mapping = {}
    from discrepancy import rank as rk
    for t, r in res.items():
        if "tag" not in r:
            summary["targets"][t] = r; continue
        tag = r["tag"]; mc = json.load(open(f"{R}/metrics-{tag}.json"))
        rc = rk(f"{R}/renders/{tag}-colour.png"); json.dump(rc, open(f"{R}/rank-{tag}.json", "w"), indent=1)
        fails, gains = gates(mc, mb, t, rc, rows)
        run([PY, "tools/delta_sheet.py", inc["renders"], inc["tag"], f"{R}/renders", tag, f"{R}/delta-{tag}.png",
             f"{tag}: {t} handle ({r['fit']['describe']}) against {inc['tag']}"], f"{R}/{t}.log")
        xy = [inc["tag"], tag]; random.shuffle(xy)
        mapping[tag] = {"X": xy[0], "Y": xy[1]}
        src = {inc["tag"]: inc["renders"], tag: f"{R}/renders"}
        foc = [t] + sorted(f for f in guards(t) if abs(next(x for x in rc if x["id"] == f)["iou"] - next(x for x in rows if x["id"] == f)["iou"]) >= 0.02)
        run([PY, "tools/pair_pages.py", src[xy[0]], xy[0], src[xy[1]], xy[1], f"{R}/pair-{tag}", "--focus", ",".join(foc[:3])], f"{R}/{t}.log")
        rt = next(x for x in rc if x["id"] == t); rb = next(x for x in rows if x["id"] == t)
        summary["targets"][t] = dict(tag=tag, describe=r["fit"]["describe"], attribution=r["fit"]["attribution"], handle=r["fit"]["handle"],
                                     target_before=dict(iou=rb["iou"], arc=rb["arc"], what=rb["what"]), target_after=dict(iou=rt["iou"], arc=rt["arc"], what=rt["what"]),
                                     gate_fails=fails, gains=gains, verdict_gates="REJECT" if fails else "pass")
    json.dump(mapping, open(f"{R}/mapping.json", "w"), indent=1)
    json.dump(summary, open(f"{R}/summary.json", "w"), indent=1, default=float)
    for t, s in summary["targets"].items():
        print(t, s.get("verdict_gates", s.get("verdict")), s.get("describe", ""), s.get("target_before", {}).get("iou"), "->", s.get("target_after", {}).get("iou"), s.get("gate_fails", ""))


def merge(A, S):
    inc = S["incumbent"]; R = f"auto/{A.round}"
    summ = json.load(open(f"{R}/summary.json"))
    acc = [t for t in A.accepted.split(",") if t]
    for t in (A.rejected or "").split(","):
        if t:
            S["tried"][t] = S["tried"].get(t, 0) + 1
    for t, s in summ["targets"].items():
        if s.get("verdict_gates") == "REJECT":
            S["tried"][t] = S["tried"].get(t, 0) + 1
    rnd = dict(round=A.round, incumbent_before=inc["tag"], accepted=acc, rejected=[t for t in summ["targets"] if t not in acc])
    if acc:
        base = json.load(open(inc["spec"]))
        for n in ("yellow", "blue"):
            base[n].setdefault("disp", [])
        spec = K.apply(base, [summ["targets"][t]["handle"] for t in acc])
        tag = f"{A.round}-merged" if len(acc) > 1 else summ["targets"][acc[0]]["tag"]
        path = f"{R}/spec-{tag}.json"
        json.dump(spec, open(path, "w"))
        if len(acc) > 1:
            mc = render_and_measure(tag, path, f"{R}/renders", R, inc.get("params", "w-final.params.json"))
            fails, gains = gates(mc, json.load(open(inc["metrics"])))
            rnd.update(merged=tag, merged_fails=fails, merged_gains=gains)
            if fails:
                print("merged candidate fails the gates:", fails); rnd["verdict"] = "merged REJECT"
                S["rounds"].append(rnd); json.dump(S, open(STATE, "w"), indent=1); return
        S["incumbent"] = dict(tag=tag, spec=path, renders=f"{R}/renders", metrics=f"{R}/metrics-{tag}.json", params=inc.get("params", "w-final.params.json"))
        rnd["verdict"] = f"new incumbent {tag}"
    S["rounds"].append(rnd)
    json.dump(S, open(STATE, "w"), indent=1)
    print(rnd)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd"); ap.add_argument("round"); ap.add_argument("accepted", nargs="?", default="")
    ap.add_argument("--n", type=int, default=3); ap.add_argument("--gens", type=int, default=18); ap.add_argument("--rejected")
    A = ap.parse_args()
    # one round at a time: a wake-up must not start a round while another is alive
    LOCK = "auto/LOCK"
    if os.path.exists(LOCK):
        pid = int(json.load(open(LOCK))["pid"])
        try:
            os.kill(pid, 0); alive = True
        except OSError:
            alive = False
        if alive:
            sys.exit(f"autoround: {json.load(open(LOCK))} is still running")
    json.dump({"pid": os.getpid(), "cmd": A.cmd, "round": A.round}, open(LOCK, "w"))
    try:
        S = json.load(open(STATE))
        (propose if A.cmd == "propose" else merge)(A, S)
    finally:
        os.remove(LOCK)
