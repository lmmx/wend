"""geodiag's library: the historical candidates it is calibrated on and regression-tested against.

  good   accepted incumbents (r12 on): their regions are the 'acceptable' distribution of every
         check, except the regions a later judge, cause record or the owner flagged in them
  bad    every recorded rejection cause (auto/causes.json: candidate, region, cause), the owner's
         flags on the final incumbent, and the named historical failures (the fused yellow T, the
         L05 double sphere, the right-valley dimple, the flat vertical seam)
  judged every blind-judged candidate from r12 with its incumbent: the agreement study, the only
         evidence on which a gate may ever be proposed (geodiag never gates by itself)

  calibrate  run geodiag on the library (cached), set each check's thresholds, write
             tools/geodiag_calib.json and auto/geodiag/EVIDENCE.md
  regress    re-run geodiag on the bad cases and report which recorded defects it flags
"""
import glob, json, os, re, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = "auto/geodiag/lib"

# a recorded cause -> the checks that should flag it (at its region, its junction or either side)
CAUSE_CHECKS = {
    "junction_pinch": ["contact_ripple", "pinch", "outline_ripple", "crease"],
    "crease": ["outline_ripple", "pinch", "crease", "bend"],
    "thinning": ["width_thin", "width_dev", "pinch"],
    "stray_blob": ["outline_offset", "ext_max", "taper_visible", "outline_ripple"],
    "flat_top": ["outline_offset", "outline_ripple", "ext_max", "width_dev"],
    "mass_distribution": ["width_dev", "width_bulge", "width_thin", "outline_offset"],
    "crossing_notch": ["contact_ripple", "outline_ripple", "contact_offset"],
    "fold": ["pinch", "bend", "outline_ripple", "crease", "contact_ripple"],
    "junction_seam": ["contact_ripple", "contact_offset", "outline_ripple"],
    "swelling": ["width_bulge", "width_dev", "seen_bead"],
    "collar": ["ext_max", "outline_offset", "taper_visible", "contact_ripple", "contact_offset", "width_dev"],
    "fused": ["contact_offset", "outline_offset", "width_dev", "missing"],
    "double_bulb": ["outline_ripple", "width_dev", "width_bulge", "width_thin"],
    "dimple": ["pinch", "outline_ripple", "contact_ripple", "crease", "width_thin"],
}
OWNER_FINAL = [  # the owner's flags on r28-hybR (2026-10-20)
    ("L01", "collar", "left head: blue scarf at the wrong height and shape"),
    ("H2|L16", "collar", "right head bumpy at the nape"),
    ("L15", "swelling", "RHS tubes non-cylindrical, irregularly puffy"),
    ("L16", "swelling", "RHS tubes non-cylindrical, irregularly puffy"),
]
NAMED = [  # (tag, colour, spec, extra, region, cause, note)
    ("poc-r2", "poc/renders/poc-r2-colour.png", None, None, "L04|L06", "fused", "the fused L04|L06 yellow T read as a flat bar"),
    ("poc-r7", "poc/renders/poc-r7-colour.png", None, None, "L05", "double_bulb", "L05 reads as two spheres"),
    ("r26-L15+L14", "auto/r26/renders/r26-L15+L14-colour.png", "auto/r26/spec-r26-L15+L14.json", "hybrid-hyb-L456.json", "L13", "dimple", "the right-valley dimple (eight handle attempts)"),
    ("r30-hybR2", "auto/r30/renders/r30-hybR2-colour.png", "auto/r26/spec-r26-L15+L14.json", "hybrid-r30-hybR2.json", "L12|L13", "junction_seam", "the flat vertical seam"),
]


def incumbents():
    """the accepted incumbents from r12, with the inputs geodiag needs"""
    S = json.load(open("auto/state.json")); out = []
    extra = None
    for r in S["rounds"]:
        v = r.get("verdict", "")
        if not v.startswith("new incumbent"): continue
        tag = v.split()[-1]; rd = r["round"]
        if tag.startswith("hyb-"): extra = "hybrid-hyb-L456.json"
        if tag == "r28-hybR": extra = "hybrid-r28-hybR.json"
        if not re.match(r"r(1[2-9]|[2-9]\d)|hyb", rd): continue
        spec = next((p for p in [f"auto/{rd}/spec-{tag}.json"] + glob.glob(f"auto/{rd}/*/spec.json") if os.path.exists(p) and (tag.endswith(os.path.basename(os.path.dirname(p))) or p.endswith(f"spec-{tag}.json"))), None)
        if tag == "r28-hybR": spec = "auto/r26/spec-r26-L15+L14.json"
        if tag == "hyb-L456": spec = "auto/r18/spec-r18-L12.json" if os.path.exists("auto/r18/spec-r18-L12.json") else spec
        col = f"auto/{rd}/renders/{tag}-colour.png"
        if os.path.exists(col): out.append(dict(tag=tag, round=rd, colour=col, spec=spec, extra=extra, metrics=f"auto/{rd}/metrics-{tag}.json"))
    return out


def judged():
    """every judged candidate from r12: (tag, round, verdict, incumbent tag, inputs)"""
    out = []
    before = {r["round"]: r.get("incumbent_before") for r in json.load(open("auto/state.json"))["rounds"]}
    for p in sorted(glob.glob("auto/r*/judge-*.md")):
        rd = p.split("/")[1]
        if not re.match(r"r(1[2-9]|[2-9]\d)$", rd): continue
        lines = open(p).read().splitlines()
        if not lines or not lines[0].startswith("verdict:"): continue
        verdict = lines[0].split(":")[1].strip().split()[0]
        m = re.search(r"([\w+.-]+) \(incumbent\)", lines[1] if len(lines) > 1 else "")
        tag = os.path.basename(p)[6:-3]
        key = tag[len(rd) + 1:]
        summ = json.load(open(f"auto/{rd}/summary.json")) if os.path.exists(f"auto/{rd}/summary.json") else {"targets": {}}
        t = summ["targets"].get(key, {})
        spec = f"auto/{rd}/{key}/spec.json" if os.path.exists(f"auto/{rd}/{key}/spec.json") else None
        if tag == "r28-hybR" or tag.startswith("r30-") or tag.startswith("r31-"): spec = "auto/r26/spec-r26-L15+L14.json"
        extra = {"r28-hybR": "hybrid-r28-hybR.json", "r30-hybR2": "hybrid-r30-hybR2.json", "r31-hybR3": "hybrid-r31-hybR3.json"}.get(tag)
        if extra is None and rd in ("r24", "r26"): extra = "hybrid-hyb-L456.json"
        col = f"auto/{rd}/renders/{tag}-colour.png"
        if os.path.exists(col):
            out.append(dict(tag=tag, round=rd, verdict=verdict, incumbent=m.group(1) if m else before.get(rd), colour=col, spec=spec, extra=extra,
                            params=t.get("params", "w-final.params.json"), metrics=f"auto/{rd}/metrics-{tag}.json"))
    return out


def _one(c):
    import geodiag as G
    path = f"{OUT}/geodiag-{c['tag']}.json"
    # --quick reuses the library's previous runs; by default every run is redone with the current
    # code (the strands and rings stay cached by spec content, auto/geodiag/cache)
    if os.path.exists(path) and os.environ.get("GEODIAG_QUICK"): return path
    try:
        G.run(c["tag"], c["colour"], c.get("spec"), OUT, f"snakes/{c['extra']}" if c.get("extra") else None, metrics=c.get("metrics") if c.get("metrics") and os.path.exists(c["metrics"]) else None,
              params=c.get("params") or "w-final.params.json", draw=False)
    except Exception as e:
        open(f"{OUT}/error-{c['tag']}.txt", "w").write(repr(e)); return None
    return path


def run_all(cases, procs=3):
    os.makedirs(OUT, exist_ok=True)
    uniq = {c["tag"]: c for c in cases}
    with ProcessPoolExecutor(procs) as ex:
        res = dict(zip(uniq, ex.map(_one, uniq.values())))
    return {t: json.load(open(p)) for t, p in res.items() if p}


def values(D):
    """every (region, check) -> badness value of one geodiag run (all regions, not just findings)"""
    v = {}
    for f, F in D["image"]["features"].items():
        if F.get("missing"): v[(f, "missing")] = 1.0; continue
        for k in ("outline_ripple", "outline_offset", "width_dev", "width_bulge", "width_thin", "ext_max", "centroid"): v[(f, k)] = F[k]
        c = D.get("metrics", {}).get(f, {}).get("crease")
        if c is not None: v[(f, "crease")] = c
    for f, L in D["strands"].get("lobes", {}).items():
        for k in ("seen_bead", "ell_p90", "lumps_p90", "pinch", "interpen", "bend"): v[(f, k)] = L[k]
    for j, J in D["image"]["junctions"].items():
        for k in ("contact_ripple", "contact_offset"): v[(j, k)] = J[k]
    for nm, M in D["image"]["macro"].items():
        v[(nm, "spine_p90")] = M["spine_p90"]; v[(nm, "width_dev_macro")] = M["width_dev"]; v[(nm, "phase_max")] = M["phase_max"]
    for n, T in D["strands"].get("tails", {}).items(): v[(f"tail:{n}", "taper_visible")] = T["taper_visible"]
    for k, Ed in D.get("edges", {}).items():
        if not Ed.get("unavailable"): v[(k, "edge_dir")] = Ed["dtan"]; v[(k, "edge_len")] = abs(Ed["dlen"]); v[(k, "edge_pos")] = Ed["pos"]
    return v


def region_hits(region, key):
    """does value key (region, check) belong to a recorded region (a feature, or a junction 'A|B')?"""
    r = key[0]
    tail_of = {"tail:blue": "L01", "tail:yellow": "L16"}
    if "|" in region:
        a, b = region.split("|")
        return r in (f"{a}|{b}", f"{b}|{a}", a, b) or tail_of.get(r) in (a, b)
    return r == region or tail_of.get(r) == region or ("|" in r and region in r.split("|"))


def bad_cases():
    c = json.load(open("auto/causes.json")); out = []
    for x in c:
        rd, cand = x["round"], x["candidate"]; key = cand[len(rd) + 1:]
        spec = f"auto/{rd}/{key}/spec.json" if os.path.exists(f"auto/{rd}/{key}/spec.json") else None
        if cand.startswith("r30-"): spec = "auto/r26/spec-r26-L15+L14.json"
        extra = {"r30-hybR2": "hybrid-r30-hybR2.json"}.get(cand) or ("hybrid-hyb-L456.json" if rd in ("r24", "r26") else None)
        out.append(dict(tag=cand, round=rd, colour=f"auto/{rd}/renders/{cand}-colour.png", spec=spec, extra=extra,
                        metrics=f"auto/{rd}/metrics-{cand}.json", region=x["where"], cause=x["cause"], note=x["note"]))
    for reg, cause, note in OWNER_FINAL:
        out.append(dict(tag="r28-hybR", round="r28", colour="auto/r28/renders/r28-hybR-colour.png", spec="auto/r26/spec-r26-L15+L14.json",
                        extra="hybrid-r28-hybR.json", metrics="auto/r28/metrics-r28-hybR.json", region=reg, cause=cause, note="owner: " + note))
    for tag, col, spec, extra, reg, cause, note in NAMED:
        out.append(dict(tag=tag, round=tag.split("-")[0], colour=col, spec=spec, extra=extra, metrics=None, region=reg, cause=cause, note=note))
    return [c for c in out if os.path.exists(c["colour"])]


def calibrate(A):
    import geodiag as G
    if A.quick: os.environ["GEODIAG_QUICK"] = "1"
    goods, bads, jd = incumbents(), bad_cases(), judged()
    runs = run_all(goods + bads + jd + [dict(tag=j["incumbent"], colour=None) for j in []])
    flagged = {(b["tag"], b["region"]) for b in bads}
    ok, bad = {}, {}
    for g in goods:
        if g["tag"] not in runs: continue
        for key, val in values(runs[g["tag"]]).items():
            if any(region_hits(reg, key) for t, reg in flagged if t == g["tag"]): continue
            ok.setdefault(key[1], []).append(val)
    for b in bads:
        if b["tag"] not in runs: continue
        vv = values(runs[b["tag"]])
        for key, val in vv.items():
            if key[1] in CAUSE_CHECKS.get(b["cause"], []) and region_hits(b["region"], key):
                bad.setdefault(key[1], []).append(val)
    T = {}
    rows = ["| check | n ok | ok p50 / p90 / p97 | n bad | bad p50 | sev1 / sev2 / sev3 | TPR@2 | FPR@2 |", "|---|---|---|---|---|---|---|---|"]
    for k in sorted(set(ok) | set(bad)):
        o = np.array(ok.get(k, [])); b = np.array(bad.get(k, []))
        if len(o) < 8:
            continue
        t1 = float(np.percentile(o, 90)); t2 = float(np.percentile(o, 97.5))
        if len(b) >= 3:
            # move sev2 down towards the bad cases only while it stays above the ok set's 95th percentile
            cand = np.unique(np.r_[o, b]); cand = cand[(cand >= np.percentile(o, 95)) & (cand <= t2)]
            if len(cand):
                j = [((b >= c).mean() - (o >= c).mean()) for c in cand]; t2 = float(cand[int(np.argmax(j))])
        t3 = float(max(np.percentile(o, 99.5), t2 * 1.25))
        t1 = min(t1, t2 * 0.999)
        T[k] = (t1, t2, t3)
        rows.append(f"| {k} | {len(o)} | {np.percentile(o, 50):.3g} / {np.percentile(o, 90):.3g} / {np.percentile(o, 97):.3g} | {len(b)} | {np.median(b) if len(b) else float('nan'):.3g} | "
                    f"{t1:.3g} / {t2:.3g} / {t3:.3g} | {(b >= t2).mean() if len(b) else float('nan'):.2f} | {(o >= t2).mean():.2f} |")
    # change thresholds: judged candidates against their incumbents, at regions with no recorded
    # defect (ok) and at the recorded defects (bad)
    dok, dbad = {}, {}
    defects = {}
    for b in bads: defects.setdefault(b["tag"], []).append(b)
    for j in jd:
        if j["tag"] not in runs or j["incumbent"] not in runs: continue
        vc, vi = values(runs[j["tag"]]), values(runs[j["incumbent"]])
        for key, val in vc.items():
            if key not in vi: continue
            d = val - vi[key]
            hits = [b for b in defects.get(j["tag"], []) if region_hits(b["region"], key) and key[1] in CAUSE_CHECKS.get(b["cause"], [])]
            if hits: dbad.setdefault(key[1], []).append(d)
            elif not any(region_hits(b["region"], key) for b in defects.get(j["tag"], [])): dok.setdefault(key[1], []).append(d)
    DT = {k: float(np.percentile(np.abs(v), 97.5)) for k, v in dok.items() if len(v) >= 20}
    drows = ["## Change thresholds (candidate - its incumbent, same region)", "", "| check | n ok | ok |delta| p97.5 = threshold | n bad | bad delta > threshold |", "|---|---|---|---|---|"]
    for k in sorted(DT):
        b = np.array(dbad.get(k, []))
        drows.append(f"| {k} | {len(dok[k])} | {DT[k]:.3g} | {len(b)} | {(b > DT[k]).mean() if len(b) else float('nan'):.2f} |")
    rows += [""] + drows
    json.dump(dict(thresholds=T, delta=DT, note="geodiag_lib.calibrate: sev1 = p90 of the accepted incumbents' regions, sev2 between their p95 and p97.5 where it best separates the recorded defects, sev3 = max(p99.5, 1.25 x sev2)",
                   n_good=len(goods), n_bad=len(bads)), open(G.CALIB, "w"), indent=1)
    # with the thresholds set, the regression table and the judge agreement study
    reg = regress_table(runs, bads, jd); ag = agreement(runs, jd)
    open("auto/geodiag/EVIDENCE.md", "w").write("# geodiag calibration evidence\n\n" + "\n".join(rows) + "\n\n" + reg + "\n\n" + ag + "\n")
    print("\n".join(rows)); print(reg); print(ag)


def detect(D, region, cause, T):
    """the strongest severity among the checks a cause maps to, at its region"""
    import geodiag as G
    best = (0, None)
    for key, val in values(D).items():
        if key[1] in CAUSE_CHECKS.get(cause, []) and region_hits(region, key):
            t = T.get(key[1]) or G.DEFAULT_T.get(key[1])
            if t is None: continue
            s = G.sev_of(val, t)
            if s > best[0]: best = (s, f"{key[0]}:{key[1]}={val:.3g}")
    return best


def regress_table(runs, bads, jd=None):
    """per recorded defect: the strongest absolute severity among its cause's checks at its region,
    and (where its incumbent was run) whether any of them moved past its change threshold"""
    import geodiag as G
    T = G.thresholds(); DT = G.delta_thresholds()
    inc_of = {j["tag"]: j["incumbent"] for j in (jd or judged())}
    rows = ["## Regression library: recorded defects and whether geodiag flags them", "",
            "| case | region | cause | strongest check (absolute) | sev | worse than its incumbent (beyond the change threshold) |", "|---|---|---|---|---|---|"]
    hit = dh = n = nd = 0
    for b in bads:
        if b["tag"] not in runs: continue
        s, why = detect(runs[b["tag"]], b["region"], b["cause"], T); n += 1; hit += s >= 2
        dl = "-"
        it = inc_of.get(b["tag"])
        if it in runs:
            vc, vi = values(runs[b["tag"]]), values(runs[it]); nd += 1
            moved = [f"{k[0]}:{k[1]} {vi[k]:.3g}->{v:.3g}" for k, v in vc.items() if k in vi and k[1] in CAUSE_CHECKS.get(b["cause"], [])
                     and region_hits(b["region"], k) and k[1] in DT and v - vi[k] > DT[k[1]]]
            dh += bool(moved); dl = ", ".join(moved[:3]) or "no"
        rows.append(f"| {b['tag']} | {b['region']} | {b['cause']} | {why or '-'} | {s} | {dl} |")
    rows.insert(1, f"absolute: flagged at sev >= 2 in {hit} of {n}; relative: worse than the incumbent beyond the change threshold in {dh} of {nd} (cases with a judged incumbent)")
    return "\n".join(rows)


def agreement(runs, jd):
    """per judged candidate: the regions geodiag finds worse than the incumbent (beyond the change
    threshold, at sev >= 2), and the judge's verdict. Evidence for a gate proposal, never a gate."""
    import geodiag as G
    T = G.thresholds(); DT = G.delta_thresholds()
    rows = ["## Judge agreement: would 'no region worse than the incumbent (beyond its change threshold, at sev >= 2)' have agreed with the blind judge?", "",
            "| candidate | judge | worse regions |", "|---|---|---|"]
    stats = {"ACCEPT": [0, 0], "REJECT": [0, 0]}
    for j in jd:
        if j["tag"] not in runs or not j["incumbent"] or j["incumbent"] not in runs: continue
        vc, vi = values(runs[j["tag"]]), values(runs[j["incumbent"]])
        new = []
        for key, val in vc.items():
            t = T.get(key[1]) or G.DEFAULT_T.get(key[1])
            if t is None or key not in vi or key[1] not in DT: continue
            if G.sev_of(val, t) >= 2 and val - vi[key] > DT[key[1]]: new.append(f"{key[0]}:{key[1]} {vi[key]:.3g}->{val:.3g}")
        stats[j["verdict"]][0] += 1; stats[j["verdict"]][1] += bool(new)
        rows.append(f"| {j['tag']} | {j['verdict']} | {', '.join(new[:6]) or '-'} |")
    rows.insert(1, f"accepted candidates with a worse region: {stats['ACCEPT'][1]} of {stats['ACCEPT'][0]}; rejected: {stats['REJECT'][1]} of {stats['REJECT'][0]}")
    return "\n".join(rows)


def regress(A):
    if A.quick: os.environ["GEODIAG_QUICK"] = "1"
    bads = bad_cases(); jd = judged()
    incs = [j for j in jd if j["tag"] in {j2["incumbent"] for j2 in jd}] + incumbents()
    runs = run_all(bads + [j for j in jd if j["tag"] in {b["tag"] for b in bads}] + incs)
    print(regress_table(runs, bads, jd))
