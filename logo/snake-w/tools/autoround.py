"""One round of the autonomous correction loop. Everything except the blind judge, which is a
separate agent that sees only the pair pages.

  propose  1. Rank the incumbent's lobes (tools/discrepancy.py, with the judges' and the owner's
              severities: auto/sev.json, auto/owner.json).
           2. Take up to N targets: first the seeded ones (below), then in rank order, such that
              no target lies inside another's crop (each fit guards its crop).
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
  merge    0. --seed FID,...: a rejected candidate that its judge found closer at its target by 2
              or more, rejected only for a small defect it named, seeds a repair: the next
              round re-fits that target from its handle (lobefit --init, sigma 0.4, crease
              tolerance 1.15) and the rejection does not count against the target's rank.
           1. Compose the handles of the accepted candidates onto the incumbent (their supports
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
  seeds      {fid: {handle, round}}: repairs for the next round (merge --seed)
  rounds     the summary of every round

Usage (from the logo root):
  autoround.py propose ROUND [--n 3] [--gens 18] [--plan plan.json]
    --plan: the round's corrections from its visual diagnosis, [{key, target, joint?, controls?,
    edge? "x,y,r", diagnosis, correction}]; replaces the ranked choice of targets
  autoround.py merge ROUND TAG,TAG,... [--rejected TAG,...] [--seed FID,...]"""
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


def render_and_measure(tag, spec, rdir, mdir, params="w-final.params.json", look=None, extra=None):
    log = f"{mdir}/{tag}.log"
    # extra: the incumbent's fixed overlay (scene.js extra, a file in snakes/: the hybrid valley, tools/hybrid.py)
    env = dict(os.environ, **({"LOOK": look} if look else {}), **({"EXTRA": extra} if extra else {}))
    with open(log, "a") as fh:
        fh.write(f"$ LOOK={look or '-'} EXTRA={extra or '-'} audit_render.py {tag} {spec} {rdir} {params}\n"); fh.flush()
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
    gpath = inc_geodiag(S, R); geo = json.load(open(gpath))
    rows = rank(f"{inc['renders']}/{inc['tag']}-colour.png", S["tried"], sev, owner, geo)
    json.dump(rows, open(f"{R}/rank.json", "w"), indent=1)
    import geodiag
    open(f"{R}/rank.md", "w").write(f"Incumbent {inc['tag']}\n\n" + table(rows) + "\n\n## geodiag (advisory) on the incumbent\n\n```\n" + geodiag.report(geo, 12) + "\n```\n"
                                    + "\n".join(f"- next: {e['region']} ({e['cause']}): {e['try_']}; evidence {'; '.join(e['evidence'])}" for e in geo["next"]) + "\n")
    seeds = S.get("seeds", {})
    plan = json.load(open(A.plan)) if A.plan else None
    chosen = [] if not plan else [p_["target"] for p_ in plan]
    for r in ([] if plan else [r for r in rows if r["id"] in seeds] + [r for r in rows if r["id"] not in seeds]):
        # features under the incumbent's fixed overlay (the hybrid valley) are not targets while it stands
        if not r["id"].startswith("L") or len(chosen) >= A.n or r["id"] in inc.get("frozen", []):
            continue
        if any(r["id"] in guards(c) or c in guards(r["id"]) for c in chosen):
            continue
        chosen.append(r["id"])
    print("targets", chosen, "repairs", [t for t in chosen if t in seeds], flush=True)
    # the candidates: (key, target, params, heads), each target with the incumbent's head and
    # with each head variant in its crop that the incumbent does not already use
    ip, ih = inc.get("params", P0), inc.get("heads", H0)
    jobs = []
    for t in ([] if plan else chosen):
        jobs.append((t, t, ip, ih))
        for h, v in HEAD_VARIANTS.items():
            if h in guards(t) and v["params"] != ip:
                jobs.append((f"{t}+{v['name']}", t, v["params"], v["heads"]))
    # a planned round (the round's visual diagnosis, LOOP.md): one job per planned correction,
    # with the controls, joint neighbour and diagnosed location it names
    pe = {}
    for p_ in plan or []:
        jobs.append((p_["key"], p_["target"], ip, ih)); pe[p_["key"]] = p_
    print("candidates", [j[0] for j in jobs], flush=True)
    summary = {"round": A.round, "incumbent": inc["tag"], "targets": {}}
    for key, t, pp, hh in jobs:
        # a round interrupted (a container restart) resumes: finished fits and renders are kept
        if os.path.exists(f"{R}/{key}/fit.json"):
            continue
        rep = ["--init", seeds[t]["handle"], "--sigma", "0.4", "--crease-tol", "1.15"] if t in seeds and key == t and not plan else []
        rep += ["--causes", "auto/causes.json"] + (["--extra", inc["extra"]] if inc.get("extra") else [])
        if key in pe:
            rep += sum(([f"--{k}", str(pe[key][k])] for k in ("controls", "joint", "edge") if pe[key].get(k)), [])
        # each round's own seed: the fit is deterministic, and the same seed from an unchanged incumbent re-found r19-L01's rejected handle in r20
        seed = ["--seed", str(int("".join(ch for ch in A.round if ch.isdigit()) or 0))]
        run([PY, "tools/lobefit.py", t, inc["spec"], f"{R}/{key}", "--gens", str(A.gens)] + seed + rep, f"{R}/{key}.log", env=ffd_env(pp, hh))
    def one(job):
        key, t, pp, hh = job
        fit = json.load(open(f"{R}/{key}/fit.json"))
        if "handle" not in fit:
            return key, dict(verdict="not controllable", attribution=fit.get("attribution"))
        tag = f"{A.round}-{key}"
        if not os.path.exists(f"{R}/metrics-{tag}.json"):
            render_and_measure(tag, f"{R}/{key}/spec.json", f"{R}/renders", R, pp, inc.get("look"), inc.get("extra"))
        return key, dict(tag=tag, fit=fit, target=t, params=pp, heads=hh, plan=pe.get(key))
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
        gd = geodiag_of(tag, f"{R}/renders", R, f"{R}/{key}/spec.json", inc.get("extra"), gpath, r["params"])
        hv = f", head {r['params']}" if r["params"] != ip else ""
        run([PY, "tools/delta_sheet.py", inc["renders"], inc["tag"], f"{R}/renders", tag, f"{R}/delta-{tag}.png",
             f"{tag}: {t} handle ({r['fit']['describe']}{hv}) against {inc['tag']}"], f"{R}/{key}.log")
        xy = [inc["tag"], tag]; random.shuffle(xy)
        mapping[tag] = {"X": xy[0], "Y": xy[1]}
        src = {inc["tag"]: inc["renders"], tag: f"{R}/renders"}
        foc = [t] + sorted(f for f in guards(t) if abs(next(x for x in rc if x["id"] == f)["iou"] - next(x for x in rows if x["id"] == f)["iou"]) >= 0.02)
        pj = (r.get("plan") or {}).get("joint")
        if pj:
            foc = [t, pj, "|".join(sorted((t, pj)))] + [f for f in foc if f not in (t, pj)]
        run([PY, "tools/pair_pages.py", src[xy[0]], xy[0], src[xy[1]], xy[1], f"{R}/pair-{tag}", "--focus", ",".join(foc[:3])], f"{R}/{key}.log")
        rt = next(x for x in rc if x["id"] == t); rb = next(x for x in rows if x["id"] == t)
        summary["targets"][key] = dict(tag=tag, target=t, params=r["params"], heads=r["heads"], plan=r.get("plan"),
                                     describe=r["fit"]["describe"] + hv, attribution=r["fit"]["attribution"], handle=r["fit"]["handle"],
                                     handles=r["fit"].get("handles") or [r["fit"]["handle"]],
                                     target_before=dict(iou=rb["iou"], arc=rb["arc"], what=rb["what"]), target_after=dict(iou=rt["iou"], arc=rt["arc"], what=rt["what"]),
                                     gate_fails=fails, gains=gains, verdict_gates="REJECT" if fails else "pass",
                                     geodiag=dict(path=f"{R}/geodiag-{tag}.json", **{k: gd["summary"][k] for k in ("new", "regressed", "resolved")},
                                                  improved=[f"{f['region']}:{f['check']}" for f in gd["findings"] if f.get("status") == "improved"]))
    json.dump(mapping, open(f"{R}/mapping.json", "w"), indent=1)
    json.dump(summary, open(f"{R}/summary.json", "w"), indent=1, default=float)
    for t, s in summary["targets"].items():
        print(t, s.get("verdict_gates", s.get("verdict")), s.get("describe", ""), s.get("target_before", {}).get("iou"), "->", s.get("target_after", {}).get("iou"), s.get("gate_fails", ""))


def geodiag_of(tag, rdir, mdir, spec, extra=None, inc_geo=None, params=P0):
    """the advisory geometry diagnosis of a rendered candidate (tools/geodiag.py): every region,
    against the reference and against the incumbent's own diagnosis. Never a gate: its findings
    rank the next experiment and are logged against the judge's verdict (auto/geodiag/judge_log.jsonl)."""
    path = f"{mdir}/geodiag-{tag}.json"
    if os.path.exists(path):
        return json.load(open(path))
    import geodiag
    D = geodiag.run(tag, f"{rdir}/{tag}-colour.png", spec, mdir, f"snakes/{extra}" if extra else None, f"{rdir}/{tag}-clay-full.png",
                    f"{rdir}/{tag}-zebra-full.png", f"{mdir}/metrics-{tag}.json", inc_geo, params)
    print(geodiag.report(D, 6), flush=True)
    return D


def inc_geodiag(S, R):
    """the incumbent's geodiag json (run once and recorded in the state)"""
    inc = S["incumbent"]
    if not (inc.get("geodiag") and os.path.exists(inc["geodiag"])):
        mdir = os.path.dirname(inc["metrics"])
        geodiag_of(inc["tag"], inc["renders"], mdir, inc["spec"], inc.get("extra"), None, inc.get("params", P0))
        inc["geodiag"] = f"{mdir}/geodiag-{inc['tag']}.json"
        json.dump(S, open(STATE, "w"), indent=1)
    return inc["geodiag"]


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
    # seeds: this round's repairs are used up; the new ones are recorded and not counted as rejections
    used = {t for t in S.get("seeds", {}) if t in {fid(k) for k in summ["targets"]}}
    S["seeds"] = {t: v for t, v in S.get("seeds", {}).items() if t not in used}
    new = [t for t in (A.seed or "").split(",") if t]
    for t in new:
        S["seeds"][t] = dict(handle=f"{R}/{t}/handle.json", round=A.round)
    rej = {fid(t) for t in (A.rejected or "").split(",") if t} - set(new)
    rej |= {fid(k) for k, s in summ["targets"].items() if s.get("verdict_gates") == "REJECT"} - set(new)
    for t in rej - {fid(k) for k in acc}:
        S["tried"][t] = S["tried"].get(t, 0) + 1
    rnd = dict(round=A.round, incumbent_before=inc["tag"], accepted=acc, rejected=[t for t in summ["targets"] if t not in acc], verdict="no correction accepted")
    judge_log(A.round, summ, acc)
    if acc:
        base = json.load(open(inc["spec"]))
        for n in ("yellow", "blue"):
            base[n].setdefault("disp", [])
        spec = K.apply(base, [hh for t in acc for hh in (summ["targets"][t].get("handles") or [summ["targets"][t]["handle"]])])
        tag = f"{A.round}-merged" if len(acc) > 1 else summ["targets"][acc[0]]["tag"]
        pp, hh = next(iter(var)) if var else (ip, inc.get("heads", H0))
        path = f"{R}/spec-{tag}.json"
        json.dump(spec, open(path, "w"))
        if len(acc) > 1:
            mc = render_and_measure(tag, path, f"{R}/renders", R, pp, inc.get("look"), inc.get("extra"))
            fails, gains = gates(mc, json.load(open(inc["metrics"])))
            rnd.update(merged=tag, merged_fails=fails, merged_gains=gains)
            if fails:
                print("merged candidate fails the gates:", fails); rnd["verdict"] = "merged REJECT"
                S["rounds"].append(rnd); json.dump(S, open(STATE, "w"), indent=1); return
        S["incumbent"] = dict(tag=tag, spec=path, renders=f"{R}/renders", metrics=f"{R}/metrics-{tag}.json", params=pp, heads=hh, look=inc.get("look"),
                              **{k: inc[k] for k in ("extra", "frozen") if k in inc})
        if os.path.exists(f"{R}/geodiag-{tag}.json"):
            S["incumbent"]["geodiag"] = f"{R}/geodiag-{tag}.json"
        current_best(S["incumbent"])
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


def judge_log(rnd, summ, acc):
    """one line per judged candidate: the judge's verdict beside geodiag's advisory changes. Where
    they disagree (accepted with regressions, rejected with none), the line says so: the evidence
    for recalibrating geodiag, or for a gate proposal to the owner (never applied automatically)"""
    os.makedirs("auto/geodiag", exist_ok=True)
    with open("auto/geodiag/judge_log.jsonl", "a") as fh:
        for key, s in summ["targets"].items():
            g = s.get("geodiag")
            if not g or "tag" not in s: continue
            v = "ACCEPT" if key in acc else "REJECT"
            worse = g["new"] + g["regressed"]
            fh.write(json.dumps(dict(round=rnd, tag=s["tag"], verdict=v, worse=worse, improved=g["improved"], resolved=g["resolved"],
                                     disagree=(v == "ACCEPT" and bool(worse)) or (v == "REJECT" and not worse))) + "\n")


def current_best(inc):
    """the stable current-best render: the accepted incumbent's colour, clay and zebra, full frame,
    copied to progress/current-best/ (synced to the PR), with what it is"""
    os.makedirs("progress/current-best", exist_ok=True)
    import shutil
    for kind, suf in (("colour", "colour"), ("clay", "clay-full"), ("zebra", "zebra-full")):
        src = f"{inc['renders']}/{inc['tag']}-{suf}.png"
        if os.path.exists(src):
            shutil.copy(src, f"progress/current-best/{kind}.png")
    json.dump(dict(tag=inc["tag"], spec=inc["spec"], extra=inc.get("extra"), note="refreshed by autoround merge on every accepted candidate (loop look); "
                   "tools/promote.py writes the production files and the look-6 render, production.png"), open("progress/current-best/current-best.json", "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd"); ap.add_argument("round"); ap.add_argument("accepted", nargs="?", default="")
    ap.add_argument("--n", type=int, default=3); ap.add_argument("--gens", type=int, default=18); ap.add_argument("--rejected"); ap.add_argument("--seed")
    ap.add_argument("--plan")
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
