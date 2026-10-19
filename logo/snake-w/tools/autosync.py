"""Copy the autonomous loop's records from a workspace into the repository's logo/snake-w/auto/:
the state, ledger, visual severities (the judges' and the owner's), and per round the ranking,
summary, X/Y mapping, judge verdicts, metrics, each target's fit report and handle, and the
accepted specs. Not the renders, pair pages, sheets or surface-point buffers (regenerable, and
large).
Usage (from the workspace's logo root): autosync.py REPO_LOGO_DIR"""
import glob, os, shutil, sys
dst = os.path.join(sys.argv[1], "auto")
keep = ["auto/state.json", "auto/LEDGER.md", "auto/sev.json", "auto/owner.json", "auto/JUDGE_PROMPT.md", "auto/NEXT.md"]
for rd in sorted(glob.glob("auto/r[0-9]*/")):
    for pat in ("rank*.json", "rank.md", "summary.json", "mapping.json", "judge-*.md", "metrics-*.json", "spec-*.json", "*/fit.json", "*/handle.json"):
        keep += glob.glob(rd + pat)
n = 0
for p in keep:
    if not os.path.exists(p):
        continue
    q = os.path.join(dst, os.path.relpath(p, "auto"))
    os.makedirs(os.path.dirname(q), exist_ok=True)
    shutil.copy(p, q); n += 1
    # the repository's pre-commit hooks want text files to end in one newline, without trailing blanks
    t = open(q).read(); u = "\n".join(l.rstrip() for l in t.split("\n")).rstrip("\n") + "\n"
    if u != t:
        open(q, "w").write(u)
print(n, "files ->", dst)
