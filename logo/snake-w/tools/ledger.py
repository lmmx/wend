"""The discrepancy ledger of one audit iteration: per registry feature, the evaluator's metric
severity and the blind critic's severity for every candidate, combined into a ranking; and the
regression gates of a candidate against the current best.

  rank      combined severity = metric severity + critic severity (each 0-5), ties broken by IoU;
            the critic's discrepancy and suggested correction are quoted for the ranked candidate
  gates     a candidate is rejected against the best if any feature's metric severity rises by 2
            or more, or its IoU falls by more than 0.08, or the critic's severity for it rises by 2
            or more, or the silhouette IoU falls by more than 0.01

Usage (from the logo root):
  ledger.py ITERDIR --rank TAG [--against BEST]    writes ITERDIR/ledger.md
ITERDIR holds metrics-<tag>.json, mapping.json (tag -> letter) and critic-<letter>.md (the
critic's reply: its ledger table rows start with "| <ID> |")."""
import argparse, json, os, re

FEATS = ["H1"] + [f"L{i:02d}" for i in range(1, 17)] + ["H2"]


def critic_rows(path):
    rows = {}
    if not os.path.exists(path):
        return rows
    for line in open(path):
        m = re.match(r"\|\s*\**(H1|H2|L\d\d)\**\s*\|\s*\**(\d)", line)
        if m:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[m.group(1)] = {"sev": int(m.group(2)), "cells": cells}
    return rows


def load(d, tag, mapping):
    m = json.load(open(f"{d}/metrics-{tag}.json"))
    c = critic_rows(f"{d}/critic-{mapping[tag]}.md")
    return m, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--rank", required=True); ap.add_argument("--against")
    A = ap.parse_args()
    mapping = json.load(open(f"{A.dir}/mapping.json"))
    tags = list(mapping)
    data = {t: load(A.dir, t, mapping) for t in tags}
    out = [f"# Discrepancy ledger: {os.path.basename(A.dir.rstrip('/'))}", "",
           "Severity 0 (matches the reference) to 5 (wrong). m = evaluator (tools/evaluate.py, real renders), "
           "c = blind critic (images only, anonymised). Combined = m + c.", ""]
    hdr = "| ID | " + " | ".join(f"{t} m / c" for t in tags) + f" | {A.rank} combined | {A.rank} IoU | critic: discrepancy | critic: correction |"
    out += [hdr, "|" + "---|" * (len(tags) + 5)]
    rank = []
    for f in FEATS:
        cells = []
        for t in tags:
            m, c = data[t]
            ms = m["features"][f]["severity"]; cs = c.get(f, {}).get("sev")
            cells.append(f"{ms} / {'?' if cs is None else cs}")
        m, c = data[A.rank]
        ms = m["features"][f]["severity"]; cs = c.get(f, {}).get("sev", 0)
        iou = m["features"][f].get("iou", 0.0)
        cc = c.get(f, {}).get("cells", [])
        disc = cc[4] if len(cc) > 4 else ""; corr = cc[5] if len(cc) > 5 else ""
        rank.append((ms + cs, -iou, f, disc, corr))
        out.append(f"| {f} | " + " | ".join(cells) + f" | {ms + cs} | {iou:.2f} | {disc} | {corr} |")
    out += ["", f"## Ranking for {A.rank} (largest first)", ""]
    for k, (s, niou, f, disc, corr) in enumerate(sorted(rank, key=lambda r: (-r[0], r[1]))):
        out.append(f"{k + 1}. **{f}** combined {s}, IoU {-niou:.2f}: {disc}")
    for t in tags:
        g = data[t][0]["global"]
        out.append(f"\n{t}: silhouette IoU {g['silhouette_iou']:.3f}, boundary p95 {g['silhouette_dist']['p95']:.1f} px, blue IoU {g['blue_iou']:.3f}, yellow IoU {g['yellow_iou']:.3f}")
    if A.against:
        out += ["", f"## Regression gates: {A.rank} against {A.against}", ""]
        (ma, ca), (mb, cb) = data[A.rank], data[A.against]
        fails, gains = [], []
        for f in FEATS:
            a, b = ma["features"][f], mb["features"][f]
            dm = a["severity"] - b["severity"]; di = a.get("iou", 0) - b.get("iou", 0)
            dc = ca.get(f, {}).get("sev", 0) - cb.get(f, {}).get("sev", 0)
            if dm >= 2 or di < -0.08 or dc >= 2:
                fails.append(f"{f}: metric severity {b['severity']} -> {a['severity']}, IoU {b.get('iou', 0):.2f} -> {a.get('iou', 0):.2f}, critic {cb.get(f, {}).get('sev', '?')} -> {ca.get(f, {}).get('sev', '?')}")
            elif dm < 0 or di > 0.05 or dc < 0:
                gains.append(f"{f}: metric severity {b['severity']} -> {a['severity']}, IoU {b.get('iou', 0):.2f} -> {a.get('iou', 0):.2f}, critic {cb.get(f, {}).get('sev', '?')} -> {ca.get(f, {}).get('sev', '?')}")
        ds = ma["global"]["silhouette_iou"] - mb["global"]["silhouette_iou"]
        if ds < -0.01:
            fails.append(f"silhouette IoU {mb['global']['silhouette_iou']:.3f} -> {ma['global']['silhouette_iou']:.3f}")
        out.append("**Regressions (gate failures):** " + ("none" if not fails else ""))
        out += [f"- {x}" for x in fails]
        out.append("\n**Improvements:** " + ("none" if not gains else ""))
        out += [f"- {x}" for x in gains]
        out.append(f"\n**Verdict:** {'REJECT' if fails else 'ACCEPT (if the critic page review agrees)'}")
    open(f"{A.dir}/ledger.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
