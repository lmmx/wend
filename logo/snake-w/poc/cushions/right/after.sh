#!/bin/bash
# the right-valley hybrid: overlay, real renders (candidate, and the incumbent again under the
# floor fix), measures, gates, sheet, blind pair pages
# usage: poc/right/after.sh CUSHIONS ALPHA
set -e
CUS=$1; AL=${2:-1.0}; XW=${3:-0}; ALONG=${4:-tube}; PY=../snakes-venv/bin/python; SPEC=auto/r26/spec-r26-L15+L14.json; R=auto/r28
TAG=r28-hybR; INC=r26-L15+L14f
CUSHION_SITE=right $PY tools/hybrid.py $SPEC $CUS poc/right/inc-rings.json snakes/hybrid-$TAG.json --alpha $AL --xw $XW --along $ALONG --base snakes/hybrid-hyb-L456.json
$PY - <<PYEOF
import sys; sys.path.insert(0, "tools")
import autoround as A
for tag, ex in (("$INC", "hybrid-hyb-L456.json"), ("$TAG", "hybrid-$TAG.json")):
    import os
    if tag == "$INC" and os.path.exists("$R/metrics-$INC.json"): continue
    A.render_and_measure(tag, "$SPEC", "$R/renders", "$R", look="snakes/w-meshshadow.look.json", extra=ex)
import json
mc, mb = json.load(open("$R/metrics-$TAG.json")), json.load(open("$R/metrics-$INC.json"))
print("gates", A.gates(mc, mb))
for f in ("L10", "L11", "L12", "L13", "L14", "L15", "L16"):
    a, b = mc["features"][f], mb["features"][f]
    print(f, "IoU %.3f -> %.3f, p95 %.1f -> %.1f, sev %s -> %s" % (b["iou"], a["iou"], b.get("p95", 0), a.get("p95", 0), b["severity"], a["severity"]))
print("silhouette", mb["global"]["silhouette_iou"], "->", mc["global"]["silhouette_iou"])
PYEOF
$PY poc/sheet.py $R/renders/$INC $R/renders/$TAG L12,L13,L14 $R/sheet-$TAG.png "$TAG: the right valley's tube moved towards the fitted cushions (after) vs the incumbent (before), real Three.js renders" 780,490,1090,810
if [ $(( RANDOM % 2 )) -eq 0 ]; then XT=$INC; YT=$TAG; else XT=$TAG; YT=$INC; fi
echo "{\"$TAG\": {\"X\": \"$XT\", \"Y\": \"$YT\"}}" > $R/mapping.json
$PY tools/pair_pages.py $R/renders $XT $R/renders $YT $R/pair-$TAG --focus "L13,L12,L14,L12|L13,L13|L14"
echo done $TAG
