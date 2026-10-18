// Where do handles land? For a spec, the screen position (reference px) and depth of the body
// vertex at (own station s, section angle psi) of each strand: the frame of geometry.js dispField
// (psi 0 towards the camera-facing depth axis, 90 degrees along the screen-plane lateral axis).
// Usage (from snakes/): node ../tools/ffd_locate.mjs params.json spec.json out.json
// (every second ring: about 6 px of station apart)
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
const G = await import(pathToFileURL(resolve("geometry.js")).href);
const S = await import(pathToFileURL(resolve("strandspline.js")).href);
const [pf, sf, outf, ...rest] = process.argv.slice(2);
const params = JSON.parse(readFileSync(pf, "utf8")), spec = JSON.parse(readFileSync(sf, "utf8"));
const body = S.strandsFromSpec(spec);
if (spec.tube) params.tube = { ...(params.tube || {}), ...spec.tube };
const el = (params.cam.elev * Math.PI) / 180, ce = Math.cos(el), se = Math.sin(el);
const proj = (p) => [p[0], -(p[1] * ce - p[2] * se), p[1] * se + p[2] * ce];
const tube = { head: { snoutLen: 1, snoutQ: 2, q: 2.4, wide: 1.06, flat: 0.96 }, ...(params.tube || {}), view: [0, se, ce] };
const out = {};
["yellow", "blue"].forEach((name, i) => {
  const st = body[name], nk = params.necks[i], i0 = st.s.findIndex((x) => x >= nk.join_s - 2);
  const sl = Object.fromEntries(Object.entries(st).map(([k, v]) => [k, Array.isArray(v) ? v.slice(i0) : v]));
  if (tube.press) { const mj = params.necks[1 - i].join_s; sl.press = sl.mateW.map((w, j) => w * G.smoothstep(mj, mj + 30, sl.mateS[j])); }
  const surf = G.strandSurface(sl, tube);
  // own station of each evened sample: by arc length, as mesh_check
  const m = surf.centre.pts.length, acc = [0], ac = [0];
  for (let k = 1; k < sl.pts.length; k++) acc.push(acc[k - 1] + Math.hypot(...[0, 1, 2].map((c) => sl.pts[k][c] - sl.pts[k - 1][c])));
  for (let k = 1; k < m; k++) ac.push(ac[k - 1] + Math.hypot(...[0, 1, 2].map((c) => surf.centre.pts[k][c] - surf.centre.pts[k - 1][c])));
  const sAt = ac.map((a) => { const f = a / ac[m - 1] * acc.at(-1); let j = 0; while (j < acc.length - 2 && acc[j + 1] < f) j++; const t = (f - acc[j]) / ((acc[j + 1] - acc[j]) || 1); return sl.s[j] + (sl.s[j + 1] - sl.s[j]) * t; });
  const rows = [];
  for (let k = 0; k < m; k += 2) {
    const r = { s: sAt[k], c: proj(surf.centre.pts[k]), rad: surf.centre.r[k], T: surf.frames.T[k] };
    r.psi = [0, 45, 90, 135, 180, 225, 270, 315].map((a) => proj(surf.pointAt(k, (a * Math.PI) / 180)));
    rows.push(r);
  }
  out[name] = rows;
});
writeFileSync(outf, JSON.stringify(out));
console.log("ok", Object.values(out).map((r) => r.length));
