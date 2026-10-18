// Dump the JS ground-truth strands (geometry.js centrelines) and the scene's rendered tube
// centrelines (sliced at each neck join, evened and smoothed as strandSurface does) to JSON.
// Usage (from snakes/): node ../tools/dump_strands.mjs params.json out.json [spec.json]
// With a spec, the strands come from strandspline.js instead (to check the JS evaluator).
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
const G = await import(pathToFileURL(resolve("geometry.js")).href);
const [pf, out, specFile] = process.argv.slice(2);
const params = JSON.parse(readFileSync(pf, "utf8"));
const lines = G.centrelines(params);
let body = { yellow: lines.yellow, blue: lines.blue };
if (specFile) {
  const S = await import(pathToFileURL(resolve("strandspline.js")).href);
  const spec = JSON.parse(readFileSync(specFile, "utf8"));
  body = S.strandsFromSpec(spec);
  if (spec.tube) params.tube = { ...(params.tube || {}), ...spec.tube };
}
const head = { snoutLen: 1, snoutQ: 2, q: 2.4, wide: 1.06, flat: 0.96 };
const tube = { head, ...(params.tube || {}) };
const res = { elev: params.cam.elev, L: lines.L, spine: lines.spine, s: lines.s, theta: lines.theta, tube: params.tube, necks: params.necks };
["yellow", "blue"].forEach((name, i) => {
  const st = body[name], nk = params.necks[i];
  const i0 = st.s.findIndex((x) => x >= nk.join_s - 2);
  const sl = Object.fromEntries(Object.entries(st).map(([k, v]) => [k, v.slice(i0)]));
  const surf = G.strandSurface(sl, { ...tube, fold: null, press: null });
  const at = G.strandAt(st, nk.join_s);
  res[name] = { ...st, i0, rendered: { pts: surf.centre.pts, r: surf.centre.r }, join: { J: at.J, T: at.T, K: at.K } };
});
writeFileSync(out, JSON.stringify(res));
console.log("L", lines.L.toFixed(1), "yellow", body.yellow.pts.length, "blue", body.blue.pts.length);
