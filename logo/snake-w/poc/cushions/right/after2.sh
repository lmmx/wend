#!/bin/bash
# a right-valley hybrid against the incumbent r28-hybR: overlay (with the left valley's), real
# render, measures, gates, sheet, blind pair pages
# usage: poc/right/after2.sh ROUND TAG CUSHIONS ALPHA XW ALONG RIM
set -e
RD=$1; TAG=$2; CUS=$3; AL=$4; XW=$5; ALONG=$6; RIM=$7
PY=../snakes-venv/bin/python; SPEC=auto/r26/spec-r26-L15+L14.json; R=auto/$RD; INC=r28-hybR; IR=auto/r28
mkdir -p $R/renders
CUSHION_SITE=right $PY tools/hybrid.py $SPEC $CUS poc/right/inc-rings.json snakes/hybrid-$TAG.json --alpha $AL --xw $XW --along $ALONG --rim $RIM --base snakes/hybrid-hyb-L456.json
$PY - <<PYEOF
import sys, json; sys.path.insert(0, "tools")
import autoround as A
A.render_and_measure("$TAG", "$SPEC", "$R/renders", "$R", look="snakes/w-meshshadow.look.json", extra="hybrid-$TAG.json")
mc, mb = json.load(open("$R/metrics-$TAG.json")), json.load(open("$IR/metrics-$INC.json"))
print("gates", A.gates(mc, mb))
for f in ("L10", "L11", "L12", "L13", "L14", "L15", "L16"):
    a, b = mc["features"][f], mb["features"][f]
    print(f, "IoU %.3f -> %.3f, sev %s -> %s" % (b["iou"], a["iou"], b["severity"], a["severity"]))
print("silhouette", mb["global"]["silhouette_iou"], "->", mc["global"]["silhouette_iou"])
PYEOF
for f in $IR/renders/$INC-*; do ln -sf "$(realpath $f)" $R/renders/; done
$PY poc/sheet.py $R/renders/$INC $R/renders/$TAG L12,L13,L14 $R/sheet-$TAG.png "$TAG: the right valley's hybrid (after) vs the incumbent $INC (before), real Three.js renders" 780,490,1090,810
if [ $(( RANDOM % 2 )) -eq 0 ]; then XT=$INC; YT=$TAG; else XT=$TAG; YT=$INC; fi
echo "{\"$TAG\": {\"X\": \"$XT\", \"Y\": \"$YT\"}}" > $R/mapping.json
$PY tools/pair_pages.py $R/renders $XT $R/renders $YT $R/pair-$TAG --focus "L13,L12,L14,L12|L13,L13|L14"
echo done $TAG
