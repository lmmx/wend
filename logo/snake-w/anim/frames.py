"""The progress animation's milestones, oldest first: each a tag, a caption, the page that renders
it and its query (params, look, spec, extra). Writes anim/jobsN.json for tools/spline_batch.mjs
and anim/captions.json; then render the jobs from snakes/ and run anim/assemble.py.
Usage (from the logo root): frames.py [N batches, default 2]"""

import json
import os
import shutil


CK = "checkpoints/"


def L(p):
    return open(f"snakes/{p}").read()


LOOK0 = CK + "look-final-art.json"
F = []


def patch(path):
    """a look/ patch over the loop's base look, one level deep (as look-lab.html composes them)"""
    base = json.load(open("snakes/w-meshshadow.look.json"))
    for k, v in json.load(open(path)).items():
        base[k] = (
            {**base[k], **v}
            if isinstance(v, dict) and isinstance(base.get(k), dict)
            else v
        )
    return base


def para(tag, cap, params, look):
    F.append(
        dict(
            tag=tag,
            cap=cap,
            page="still.html",
            params=CK + params,
            query=dict(look=L(CK + look), ss="2"),
        )
    )


def spline(tag, cap, spec, look, extra=None, lookpath=False):
    q = dict(look=json.dumps(patch(look)) if lookpath else L(look), ss="2", spec=spec)
    if extra:
        q["extra"] = extra
    F.append(
        dict(
            tag=tag,
            cap=cap,
            page="still-spline.html",
            params="w-final.params.json",
            query=q,
        )
    )


para(
    "a01", "parametric body: the first fit", "pre-bead-best.json", "pre-bead-look.json"
)
para(
    "a02",
    "parametric: head field v2",
    "heads2-fieldfix.json",
    "look-H-pre-artpass.json",
)
para("a03", "parametric: head art pass", "artpass-best.json", "look-artpass-best.json")
para("a04", "parametric: fold pinch", "body-fold.json", "look-final.json")
para("a05", "parametric: contact press", "body-press18.json", "look-final.json")
para("a06", "parametric: right valley", "body-rvalley1.json", "look-final.json")
para("a07", "parametric: both valleys", "body-valleys.json", "look-final.json")
para("a08", "parametric: first final", "final.json", "look-final.json")
for i, lk in zip(range(1, 6), ["look-art1.json"] * 2 + ["look-art2.json"] * 3):
    para(f"a1{i}", f"art-direction pass {i}", f"body-art{i}.json", lk)
para("a16", "parametric: art-directed final", "final-art.json", "look-final-art.json")
spline("b01", "C2 spline body", "spline-lo.json", LOOK0)
spline("b02", "right valley: JAX region fit (e1)", "spline-rv-e1.json", LOOK0)
spline("b03", "audit loop: lvt60", "spline-lvt60.json", LOOK0)
R = [
    ("r1-L13", "auto/r1/spec-r1-L13.json"),
    ("r2-L01", "auto/r2/spec-r2-L01.json"),
    ("r4-merged", "auto/r4/spec-r4-merged.json"),
    ("r5-L02", "auto/r5/spec-r5-L02.json"),
    ("r6-L03", "auto/r6/spec-r6-L03.json"),
    ("r7-merged", "auto/r7/spec-r7-merged.json"),
    ("r12-L06", "auto/r12/spec-r12-L06.json"),
    ("r13-L01", "auto/r13/spec-r13-L01.json"),
    ("r15-L06", "auto/r15/spec-r15-L06.json"),
    ("r18-L12", "auto/r18/spec-r18-L12.json"),
]
for n, (t, s) in enumerate(R):
    spline(
        f"c{n:02d}",
        f"loop {t}",
        "../" + s,
        LOOK0 if n < 6 else "w-meshshadow.look.json",
    )
spline(
    "c10",
    "loop hyb-L456: left-valley cushions",
    "../auto/r18/spec-r18-L12.json",
    "w-meshshadow.look.json",
    "hybrid-hyb-L456.json",
)
spline(
    "c11",
    "loop r24-L16+L15",
    "../auto/r24/spec-r24-L16+L15.json",
    "w-meshshadow.look.json",
    "hybrid-hyb-L456.json",
)
spline(
    "c12",
    "loop r26-L15+L14",
    "../auto/r26/spec-r26-L15+L14.json",
    "w-meshshadow.look.json",
    "hybrid-hyb-L456.json",
)
spline(
    "c13",
    "loop r28-hybR: right-valley cushions",
    "../auto/r26/spec-r26-L15+L14.json",
    "w-meshshadow.look.json",
    "hybrid-r28-hybR.json",
)
for i in range(1, 7):
    spline(
        f"d{i}",
        f"look {i}" + (" (frozen)" if i == 6 else ""),
        "../auto/r26/spec-r26-L15+L14.json",
        f"look/look{i}.json",
        "hybrid-r28-hybR.json",
        lookpath=True,
    )
spline(
    "e1",
    "r38-edge: right-arm edge fit (final)",
    "../auto/r38/spec-r38-edge.json",
    "w-final.look.json",
    "hybrid-r28-hybR.json",
)
if __name__ == "__main__":
    import sys

    out = os.path.abspath("anim/frames")
    jobs = []
    for f in F:
        q = dict(f["query"])
        # the render server serves snakes/ only: copy a loop round's spec in beside the pages
        if q.get("spec", "").startswith("../"):
            name = "anim-" + os.path.basename(q["spec"])
            shutil.copy("snakes/" + q["spec"], "snakes/" + name)
            q["spec"] = name
        jobs.append(
            dict(
                out=f"{out}/{f['tag']}.png", page=f["page"], params=f["params"], query=q
            )
        )
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    for i in range(k):
        json.dump(jobs[i::k], open(f"anim/jobs{i}.json", "w"))
    json.dump(
        [dict(tag=f["tag"], cap=f["cap"]) for f in F],
        open("anim/captions.json", "w"),
        indent=1,
    )
    print(len(F), "frames")
