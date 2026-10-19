"""One round of the autonomous correction loop. Everything except the blind judge, which is a
separate agent that sees only the pair pages.

  propose  1. Rank the incumbent's lobes (tools/discrepancy.py, with the judges' and the owner's
              severities: auto/sev.json, auto/owner.json).
           2. Take up to N targets in rank order such that no target lies inside another's
              crop (each fit guards its crop).
           3. A target whose crop holds a head with a variant (HEAD_VARIANTS) is fitted twice:
              once with the incumbent's head, and once with the variant's (candidate key
              TARGET+NAME), so that a correction which uncovers that head's neck can bring the
              neck that suits it.
           4. For each candidate:
              - fit it from the incumbent (tools/lobefit.py);
              - render it for real (tools/audit_render.py);
              - measure it (tools/evaluate.py);
              - check the ledger gates against the incumbent: no feature's severity up by 2, no
                IoU down by more than 0.08, the silhouette not down by more than 0.01, and the
                target itself must improve (IoU up 0.02 or the worst contour arc 3 px smaller);
              - build its delta sheet and its blind pair pages, with the X / Y order random and
                recorded in ROUND/mapping.json.
  merge    1. Compose the handles of the accepted candidates onto the incumbent (their supports
              are disjoint; at most one candidate per target). An accepted head variant's params
              and head bake become the incumbent's. The owner's entries for the accepted targets
              lose one step of severity each, and are addressed at 1.
           2. Render the result, measure it, and gate it.
           3. If the gates pass, it becomes the incumbent; record the judged rejections.

Only one autoround runs at a time (auto/LOCK holds its pid; a second one exits).
State: auto/state.json holds:
  incumbent  {tag, spec, renders, metrics, params, heads, look}: params is the scene params file
             (snakes/) its renders use (the heads and necks; default w-final.params.json), heads
             that file's head bake for the flat fits (default heads-final.json), look the look file
             (default snakes/w-final.look.json)
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
OWNER = "auto/owner.json"
P0, H0 = "w-final.params.json", "heads-final.json"
# head variants: a pre-built alternative head and neck that a correction next to that head may
# switch to, as one more freedom. neck1 (snakes/w-neck1.params.json: a C2 cubic neck blend and a
# nape round-cone on the yellow head; tools/bake_heads.mjs bakes heads-neck1.json) removes the
# step in the yellow neck that the blue collar L01 uncovers when it comes down (r1-L01's
# rejection); judged alone (auto/neck1) it was neutral, the collar hiding that step. Off from
# round 14: the judges rejected it with the collar fitted too (r12, r13), the second time for a
# dark blob that neck1's head has in the zebra under the jaw, so every neck1 candidate carries a
# defect of its own until that head is fixed
NECK1 = dict(name="neck1", params="w-neck1.params.json", heads="heads-neck1.json")
HEAD_VARIANTS = {}


def ffd_env(params, heads):
    """the environment for a flat fit (lobefit.py's workers) with this params file and head bake"""
    return dict(os.environ, FFD_PARAMS=params, FFD_HEADS=heads)


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


def run(cmd, log, env=None):
    with open(log, "a") as fh:
        fh.write("$ " + (f"FFD_PARAMS={env['FFD_PARAMS']} FFD_HEADS={env['FFD_HEADS']} " if env else "") + " ".join(cmd) + "\n"); fh.flush()
        subprocess.run(cmd, check=True, stdout=fh, stderr=subprocess.STDOUT, env=env)


def render_and_measure(tag, spec, rdir, mdir, params="w-final.params.json", look=None):
    log = f"{mdir}/{tag}.log"
    env = dict(os.environ, **({"LOOK": look} if look else {}))
    with open(log, "a") as fh:
        fh.write(f"$ LOOK={look or '-'} audit_render.py {tag} {spec} {rdir} {params}\n"); fh.flush()
        subprocess.run([PY, "tools/audit_render.py", tag, spec, rdir, params], check=True, stdout=fh, stderr=subprocess.STDOUT, env=env)
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
    owner = json.load(open(OWNER)) if os.path.exists(OWNER) else None
    rows = rank(f"{inc['renders']}/{inc['tag']}-colour.png", S["tried"], sev, owner)
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
    # the candidates: (key, target, params, heads), each target with the incumbent's head and
    # with each head variant in its crop that the incumbent does not already use
    ip, ih = inc.get("params", P0), inc.get("heads", H0)
    jobs = []
    for t in chosen:
        jobs.append((t, t, ip, ih))
        for h, v in HEAD_VARIANTS.items():
            if h in guards(t) and v["params"] != ip:
                jobs.append((f"{t}+{v['name']}", t, v["params"], v["heads"]))
    print("candidates", [j[0] for j in jobs], flush=True)
    summary = {"round": A.round, "incumbent": inc["tag"], "targets": {}}
    for key, t, pp, hh in jobs:
        # a round interrupted (a container restart) resumes: finished fits and renders are kept
        if os.path.exists(f"{R}/{key}/fit.json"):
            continue
        run([PY, "tools/lobefit.py", t, inc["spec"], f"{R}/{key}", "--gens", str(A.gens)], f"{R}/{key}.log", env=ffd_env(pp, hh))
    def one(job):
        key, t, pp, hh = job
        fit = json.load(open(f"{R}/{key}/fit.json"))
        if "handle" not in fit:
            return key, dict(verdict="not controllable", attribution=fit.get("attribution"))
        tag = f"{A.round}-{key}"
        if not os.path.exists(f"{R}/metrics-{tag}.json"):
            render_and_measure(tag, f"{R}/{key}/spec.json", f"{R}/renders", R, pp, inc.get("look"))
        return key, dict(tag=tag, fit=fit, target=t, params=pp, heads=hh)
    with ThreadPoolExecutor(2) as ex:
        res = dict(ex.map(one, jobs))
    mb = json.load(open(inc["metrics"]))
    mapping = {}
    from discrepancy import rank as rk
    for key, r in res.items():
        if "tag" not in r:
            summary["targets"][key] = r; continue
        t = r["target"]
        tag = r["tag"]; mc = json.load(open(f"{R}/metrics-{tag}.json"))
        rc = rk(f"{R}/renders/{tag}-colour.png"); json.dump(rc, open(f"{R}/rank-{tag}.json", "w"), indent=1)
        fails, gains = gates(mc, mb, t, rc, rows)
        hv = f", head {r['params']}" if r["params"] != ip else ""
        run([PY, "tools/delta_sheet.py", inc["renders"], inc["tag"], f"{R}/renders", tag, f"{R}/delta-{tag}.png",
             f"{tag}: {t} handle ({r['fit']['describe']}{hv}) against {inc['tag']}"], f"{R}/{key}.log")
        xy = [inc["tag"], tag]; random.shuffle(xy)
        mapping[tag] = {"X": xy[0], "Y": xy[1]}
        src = {inc["tag"]: inc["renders"], tag: f"{R}/renders"}
        foc = [t] + sorted(f for f in guards(t) if abs(next(x for x in rc if x["id"] == f)["iou"] - next(x for x in rows if x["id"] == f)["iou"]) >= 0.02)
        run([PY, "tools/pair_pages.py", src[xy[0]], xy[0], src[xy[1]], xy[1], f"{R}/pair-{tag}", "--focus", ",".join(foc[:3])], f"{R}/{key}.log")
        rt = next(x for x in rc if x["id"] == t); rb = next(x for x in rows if x["id"] == t)
        summary["targets"][key] = dict(tag=tag, target=t, params=r["params"], heads=r["heads"],
                                     describe=r["fit"]["describe"] + hv, attribution=r["fit"]["attribution"], handle=r["fit"]["handle"],
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
    fid = lambda key: summ["targets"].get(key, {}).get("target", key.split("+")[0])
    if len({fid(k) for k in acc}) < len(acc):
        sys.exit(f"merge: at most one accepted candidate per target ({acc})")
    # the head: the incumbent's, or the one head variant among the accepted (a plain candidate
    # composes with it; the composite's render is gated)
    ip = inc.get("params", P0)
    var = {(summ["targets"][k].get("params", ip), summ["targets"][k].get("heads", inc.get("heads", H0))) for k in acc} - {(ip, inc.get("heads", H0))}
    if len(var) > 1:
        sys.exit(f"merge: the accepted candidates use different head variants ({acc})")
    # a target's tried count goes up once a round, however many of its candidates were rejected
    rej = {fid(t) for t in (A.rejected or "").split(",") if t}
    rej |= {fid(k) for k, s in summ["targets"].items() if s.get("verdict_gates") == "REJECT"}
    for t in rej - {fid(k) for k in acc}:
        S["tried"][t] = S["tried"].get(t, 0) + 1
    rnd = dict(round=A.round, incumbent_before=inc["tag"], accepted=acc, rejected=[t for t in summ["targets"] if t not in acc], verdict="no correction accepted")
    if acc:
        base = json.load(open(inc["spec"]))
        for n in ("yellow", "blue"):
            base[n].setdefault("disp", [])
        spec = K.apply(base, [summ["targets"][t]["handle"] for t in acc])
        tag = f"{A.round}-merged" if len(acc) > 1 else summ["targets"][acc[0]]["tag"]
        pp, hh = next(iter(var)) if var else (ip, inc.get("heads", H0))
        path = f"{R}/spec-{tag}.json"
        json.dump(spec, open(path, "w"))
        if len(acc) > 1:
            mc = render_and_measure(tag, path, f"{R}/renders", R, pp, inc.get("look"))
            fails, gains = gates(mc, json.load(open(inc["metrics"])))
            rnd.update(merged=tag, merged_fails=fails, merged_gains=gains)
            if fails:
                print("merged candidate fails the gates:", fails); rnd["verdict"] = "merged REJECT"
                S["rounds"].append(rnd); json.dump(S, open(STATE, "w"), indent=1); return
        S["incumbent"] = dict(tag=tag, spec=path, renders=f"{R}/renders", metrics=f"{R}/metrics-{tag}.json", params=pp, heads=hh, look=inc.get("look"))
        rnd["verdict"] = f"new incumbent {tag}"
        # an accepted correction of a feature the owner named takes one step off the owner's
        # severity (a judged step closer leaves it still wrong, less so); at 1 it is addressed
        if os.path.exists(OWNER):
            ow = json.load(open(OWNER))
            for k in acc:
                e = ow.get(fid(k))
                if e and not e.get("addressed"):
                    e["sev"] = e["sev"] - 1; e.setdefault("steps", []).append(A.round)
                    if e["sev"] <= 1:
                        e["addressed"] = A.round
            json.dump(ow, open(OWNER, "w"), indent=1)
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
