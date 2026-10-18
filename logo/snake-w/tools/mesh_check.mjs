// Mesh-level validity of the body as the scene builds it (strands sliced at the neck joins, the
// tube options of params + spec, strandSurface rings): not the fit's own loss.
//   self   ring vertices of a strand lying inside a *non-adjacent* section of the same strand
//          (>= 90 px of station apart): distance to that section's ring centre < its radius - 1
//   across the same against the other strand, any station (soft contact: reported, intended)
//   folds  ring-to-ring advance of a surface line against the tube's tangent < 0 (the surface
//          runs backwards: a fold); "visible" ones also face the camera and survive a 2 px
//          point z-buffer of both tubes
// Areas, not vertex counts (those depend on the mesh resolution): each vertex stands for its
// patch, ring spacing x 2 pi r / radial. Reported over the whole body and inside an optional
// window (reference pixels), with the image bounding box of each defect.
// Usage (from snakes/): node ../tools/mesh_check.mjs params.json [spec.json|-] [x0,y0,x1,y1]
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
const G = await import(pathToFileURL(resolve("geometry.js")).href);
const [pf, specFile, boxArg] = process.argv.slice(2);
const params = JSON.parse(readFileSync(pf, "utf8"));
const lines = G.centrelines(params);
let body = { yellow: lines.yellow, blue: lines.blue };
if (specFile && specFile !== "-") {
  const S = await import(pathToFileURL(resolve("strandspline.js")).href);
  const spec = JSON.parse(readFileSync(specFile, "utf8"));
  body = S.strandsFromSpec(spec);
  if (spec.tube) params.tube = { ...(params.tube || {}), ...spec.tube };
}
const box = boxArg ? boxArg.split(",").map(Number) : null;
const el = (params.cam.elev * Math.PI) / 180, ce = Math.cos(el), se = Math.sin(el);
const proj = (p) => [p[0], -(p[1] * ce - p[2] * se), p[1] * se + p[2] * ce];
const inBox = (q) => !box || (q[0] >= box[0] && q[0] <= box[2] && q[1] >= box[1] && q[1] <= box[3]);
const strands = {};
["yellow", "blue"].forEach((name, i) => {
  const st = body[name], nk = params.necks[i], i0 = st.s.findIndex((x) => x >= nk.join_s - 2);
  strands[name] = Object.fromEntries(Object.entries(st).map(([k, v]) => [k, v.slice(i0)]));
});
const tube = { head: { snoutLen: 1, snoutQ: 2, q: 2.4, wide: 1.06, flat: 0.96 }, ...(params.tube || {}) };
if (tube.press) ["yellow", "blue"].forEach((name, i) => {
  const st = strands[name], mateJoin = params.necks[1 - i].join_s;
  st.press = st.mateW.map((w, j) => w * G.smoothstep(mateJoin, mateJoin + 30, st.mateS[j]));
});
const surf = {}, info = {};
for (const name of ["yellow", "blue"]) {
  const S = G.strandSurface(strands[name], tube);
  const capN = 13; // snout cap rings before the body rings (caps: 14 and 12 rings, minus one each)
  const m = S.centre.pts.length;
  const body = S.rings.slice(capN, capN + m);
  // the station of each evened sample: by arc length along the sliced strand
  const st = strands[name], acc = [0];
  for (let i = 1; i < st.pts.length; i++) acc.push(acc[i - 1] + Math.hypot(...[0, 1, 2].map((k) => st.pts[i][k] - st.pts[i - 1][k])));
  const ac = [0];
  for (let i = 1; i < m; i++) ac.push(ac[i - 1] + Math.hypot(...[0, 1, 2].map((k) => S.centre.pts[i][k] - S.centre.pts[i - 1][k])));
  const sAt = ac.map((a) => { const f = a / ac[m - 1] * acc[acc.length - 1]; let j = 0; while (j < acc.length - 2 && acc[j + 1] < f) j++; const t = (f - acc[j]) / ((acc[j + 1] - acc[j]) || 1); return st.s[j] + (st.s[j + 1] - st.s[j]) * t; });
  // the section frame (l, d) and semi-axes per ring, as strandSurface's ellipse()
  const view = [0, se, ce], sec = S.centre.sec;
  const ax = S.centre.pts.map((_, i) => {
    const t = S.frames.T[i], vt = view[0] * t[0] + view[1] * t[1] + view[2] * t[2];
    let d = [view[0] - t[0] * vt, view[1] - t[1] * vt, view[2] - t[2] * vt]; const dn = Math.hypot(...d);
    const lev = sec ? G.smoothstep(0.2, 0.45, dn) : 0; d = d.map((x) => x / (dn || 1));
    const l = [t[1] * d[2] - t[2] * d[1], t[2] * d[0] - t[0] * d[2], t[0] * d[1] - t[1] * d[0]];
    const [ql, qd, psi] = sec ? sec[i].map((x, k) => (k < 2 ? 1 + lev * (x - 1) : lev * x)) : [1, 1, 0];
    const c = Math.cos(psi), s_ = Math.sin(psi);
    return { a1: l.map((x, k) => c * x + s_ * d[k]), a2: l.map((x, k) => -s_ * x + c * d[k]), ql, qd, t };
  });
  surf[name] = { rings: body, c: S.centre.pts, r: S.centre.r, T: S.frames.T, s: sAt, ax };
}
// z-buffer of all body vertices, 2 px cells
const zb = new Map(), cell = (q) => `${Math.round(q[0] / 2)},${Math.round(q[1] / 2)}`;
for (const name in surf) for (const ring of surf[name].rings) for (const v of ring) {
  const q = proj(v), k = cell(q); if (!zb.has(k) || zb.get(k) < q[2]) zb.set(k, q[2]);
}
const visible = (q) => q[2] >= zb.get(cell(q)) - 3;
const view = [0, se, ce];
const out = {};
for (const name of ["yellow", "blue"]) {
  const A = surf[name], other = surf[name === "yellow" ? "blue" : "yellow"];
  const area = (i) => 3 * (2 * Math.PI * A.r[i]) / A.rings[i].length;
  let selfA = 0, selfAVis = 0, foldA = 0, foldAVis = 0, foldAVisBox = 0, selfABox = 0;
  const bb = { self: [1e9, 1e9, -1e9, -1e9], fold: [1e9, 1e9, -1e9, -1e9] };
  const grow = (b, q) => { b[0] = Math.min(b[0], q[0]); b[1] = Math.min(b[1], q[1]); b[2] = Math.max(b[2], q[0]); b[3] = Math.max(b[3], q[1]); };
  let selfN = 0, selfBox = 0, selfMax = 0, selfMaxBox = 0, selfVisBox = 0, foldN = 0, foldVis = 0, foldVisBox = 0, acrossMax = 0;
  const L = lines.L, shared = (nm, s) => (nm === "yellow" ? s : L - s);
  for (let i = 0; i < A.rings.length; i++) {
    const ring = A.rings[i];
    for (let j = 0; j < ring.length; j++) {
      const v = ring[j], q = proj(v);
      // non-adjacent sections of the same strand
      let pen = 0;
      for (let k = 0; k < A.c.length; k += 2) {
        if (Math.abs(A.s[k] - A.s[i]) < 90) continue;
        // inside section k's ellipsoid (semi-axes r ql, r qd, r ql about l, d, T)? depth of entry
        const c = A.c[k], e = A.ax[k], w = [v[0] - c[0], v[1] - c[1], v[2] - c[2]];
        const dt = (a) => w[0] * a[0] + w[1] * a[1] + w[2] * a[2];
        const ra = A.r[k] * e.ql, rb = A.r[k] * e.qd;
        const rho = Math.hypot(dt(e.a1) / ra, dt(e.a2) / rb, dt(e.t) / ra);
        pen = Math.max(pen, (1 - rho) * Math.min(ra, rb));
      }
      if (pen > 1) { selfA += area(i); if (visible(q)) { selfAVis += area(i); grow(bb.self, q); } if (inBox(q)) selfABox += area(i); selfN++; selfMax = Math.max(selfMax, pen); if (inBox(q)) { selfBox++; selfMaxBox = Math.max(selfMaxBox, pen); if (visible(q)) selfVisBox++; } }
      let pa = 0;
      for (let k = 0; k < other.c.length; k += 3) {
        const c = other.c[k], d = Math.hypot(v[0] - c[0], v[1] - c[1], v[2] - c[2]);
        pa = Math.max(pa, other.r[k] - d);
      }
      acrossMax = Math.max(acrossMax, pa);
      if (i + 1 < A.rings.length) {
        const w = A.rings[i + 1][j], T = A.T[i];
        const adv = (w[0] - v[0]) * T[0] + (w[1] - v[1]) * T[1] + (w[2] - v[2]) * T[2];
        if (adv < 0) {
          foldN++; foldA += area(i);
          const c = A.c[i], n = [v[0] - c[0], v[1] - c[1], v[2] - c[2]], nn = Math.hypot(...n) || 1;
          const facing = (n[0] * view[0] + n[1] * view[1] + n[2] * view[2]) / nn;
          if (facing > 0.2 && visible(q)) { foldVis++; foldAVis += area(i); grow(bb.fold, q); if (inBox(q)) { foldVisBox++; foldAVisBox += area(i); } }
        }
      }
    }
  }
  const r0 = (v) => Math.round(v);
  out[name] = { nonlocal_self_area_px2: r0(selfA), nonlocal_self_area_in_box_px2: r0(selfABox), nonlocal_self_max_depth_px: +selfMax.toFixed(1), nonlocal_self_max_depth_in_box_px: +selfMaxBox.toFixed(1),
    local_fold_area_px2: r0(foldA), local_fold_visible_area_px2: r0(foldAVis), local_fold_visible_area_in_box_px2: r0(foldAVisBox),
    visible_self_bbox: bb.self.map(r0), visible_fold_bbox: bb.fold.map(r0), across_contact_max_px: +acrossMax.toFixed(1) };
  continue;
  out[name] = { self_vertices: selfN, self_max_px: +selfMax.toFixed(1), self_in_box: selfBox, self_in_box_visible: selfVisBox, self_max_in_box_px: +selfMaxBox.toFixed(1),
    fold_vertices: foldN, fold_visible: foldVis, fold_visible_in_box: foldVisBox, across_max_px: +acrossMax.toFixed(1) };
}
console.log(JSON.stringify(out));
