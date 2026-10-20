// Two snakes twisted into a W: pure geometry, no Three.js.
//
// The centrelines are the fit's model (tools/snakefit.py), computed the same way:
//   - an invisible spine C(s), a clamped cubic B-spline resampled by arc length s;
//   - a parallel-transport frame N(s), B(s) along it;
//   - a twist angle theta(s), integrated from a rate that varies along the spine, so the
//     twist can slow down and reverse at the crest (a perversion);
//   - the strands C(s) -/+ R u(s), u = cos(theta) N + sin(theta) B, yellow and blue;
//   - near each head the pair shifts so that the head's snake runs on the spine and the
//     other snake's tail wraps around its neck.
// On top of the fit this file adds what a silhouette can't constrain: tube meshes with
// proper caps, a softly squared head cross-section, eyes, and baked ambient occlusion.
//
// Units are reference-image pixels (the reference is 1448 x 1086); x right, y up
// (y = -image y), z towards the camera.

export const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
export const smoothstep = (e0, e1, x) => { const t = clamp((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t); };
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => Math.hypot(a[0], a[1], a[2]);
const unit = (a) => mul(a, 1 / (norm(a) || 1));

// Clamped uniform cubic B-spline, sampled at n + 1 parameters (as numpy's version).
export function bspline(ctrl, n) {
  const P = [ctrl[0], ctrl[0], ...ctrl, ctrl.at(-1), ctrl.at(-1)];
  const segs = P.length - 3;
  const out = [];
  for (let k = 0; k <= n; k++) {
    const t = k < n ? (k * segs) / n : segs - 1e-9;
    const i = Math.min(Math.floor(t), segs - 1), u = t - i;
    const b0 = (1 - u) ** 3 / 6, b1 = (3 * u ** 3 - 6 * u ** 2 + 4) / 6;
    const b2 = (-3 * u ** 3 + 3 * u ** 2 + 3 * u + 1) / 6, b3 = u ** 3 / 6;
    out.push([0, 1, 2].map((c) => b0 * P[i][c] + b1 * P[i + 1][c] + b2 * P[i + 2][c] + b3 * P[i + 3][c]));
  }
  return out;
}

// Resample a polyline at n points evenly spaced in arc length.
export function resample(C, n) {
  const d = [0];
  for (let i = 1; i < C.length; i++) d.push(d[i - 1] + norm(sub(C[i], C[i - 1])));
  const L = d.at(-1), pts = [], s = [];
  let j = 0;
  for (let k = 0; k < n; k++) {
    const t = (k * L) / (n - 1);
    while (j < C.length - 2 && d[j + 1] < t) j++;
    const f = clamp((t - d[j]) / (d[j + 1] - d[j] || 1), 0, 1);
    pts.push(add(C[j], mul(sub(C[j + 1], C[j]), f)));
    s.push(t);
  }
  return { pts, s };
}

const gradient = (C) => C.map((_, i) => {
  const a = C[Math.max(i - 1, 0)], b = C[Math.min(i + 1, C.length - 1)];
  return sub(b, a);
});

// The strands' centrelines and radii, sampled along the spine.
export function centrelines(p, n = 3000) {
  let { pts: C, s } = p.polyline
    ? resample(p.polyline.map(([x, y]) => [x, -y, 0]), n) // a spine read off the reference
    : resample(bspline(p.spine, 4000), n);
  let L = s.at(-1);
  let T = gradient(C).map(unit);
  if (p.spine_offsets) {
    // a smooth in-plane displacement of the spine, knots evenly along it
    const off = p.spine_offsets, at = (x) => {
      const f = clamp((x / L) * (off.length - 1), 0, off.length - 1), i = Math.min(Math.floor(f), off.length - 2);
      return off[i] + (off[i + 1] - off[i]) * (f - i);
    };
    ({ pts: C, s } = resample(C.map((c, i) => add(c, mul([-T[i][1], T[i][0], 0], at(s[i])))), n));
    L = s.at(-1);
    T = gradient(C).map(unit);
  }
  const N = [], B = [];
  let b = unit(sub([0, 0, 1], mul(T[0], T[0][2])));
  for (let i = 0; i < n; i++) {
    if (i) b = unit(sub(b, mul(T[i], dot(b, T[i]))));
    B.push(b); N.push(cross(b, T[i]));
  }
  const [h0, h1] = p.helix;
  const knots = p.rate.map((_, i) => (h0 + ((h1 - h0) * i) / (p.rate.length - 1)) * L);
  const rateAt = (x) => {
    if (x <= knots[0]) return p.rate[0] / 100;
    if (x >= knots.at(-1)) return p.rate.at(-1) / 100;
    const i = knots.findIndex((k) => k > x) - 1;
    return (p.rate[i] + ((p.rate[i + 1] - p.rate[i]) * (x - knots[i])) / (knots[i + 1] - knots[i])) / 100;
  };
  let theta = [p.theta0];
  for (let i = 1; i < n; i++) theta.push(theta[i - 1] + 2 * Math.PI * ((rateAt(s[i]) + rateAt(s[i - 1])) / 2) * (s[i] - s[i - 1]));
  let anchors = p.anchors;
  if (p.anchor_xy) {
    // anchors at image points (each lobe's centre), projected onto the spine
    const e = (p.cam.elev * Math.PI) / 180;
    anchors = p.anchor_xy.map(([x, y, t]) => {
      let bi = 0, bd = Infinity;
      C.forEach((c, i) => {
        const d = (c[0] - x) ** 2 + (-(c[1] * Math.cos(e) - c[2] * Math.sin(e)) - y) ** 2;
        if (d < bd) { bd = d; bi = i; }
      });
      return [s[bi], t];
    });
  }
  if (anchors) {
    // theta pinned at arc lengths (each visible lobe faces the camera), linear between,
    // continued with the end slopes beyond
    const A = anchors.map(([x, t], i) => [x + (p.anchor_shift || 0) + (p.anchor_offsets ? p.anchor_offsets[i] : 0), t, i]);
    A.sort((u, v) => u[0] - v[0]);
    const m0 = (A[1][1] - A[0][1]) / (A[1][0] - A[0][0]), m1 = (A.at(-1)[1] - A.at(-2)[1]) / (A.at(-1)[0] - A.at(-2)[0]);
    // a monotone cubic through the anchors (Fritsch-Carlson), smooth where the twist reverses
    const h = A.slice(1).map((a, i) => a[0] - A[i][0]), d = h.map((hi, i) => (A[i + 1][1] - A[i][1]) / hi);
    const m = A.map((_, i) => {
      if (i === 0) return d[0];
      if (i === A.length - 1) return d.at(-1);
      if (d[i - 1] * d[i] <= 0) return 0;
      const w1 = 2 * h[i] + h[i - 1], w2 = h[i] + 2 * h[i - 1];
      return (w1 + w2) / (w1 / d[i - 1] + w2 / d[i]);
    });
    // the twist reversal (`reversal` = { anchor, w }): between its neighbouring anchors theta
    // follows a rounded V, t0 - c (sqrt((x - s0)^2 + w^2) - w), so the twist keeps its pace
    // into the reversal and turns round within about w px, instead of slowing over the whole
    // interval; the neighbours' slopes are set to match, so the twist stays C1
    let rev = null;
    if (p.reversal) {
      const k = A.findIndex((a) => a[2] === p.reversal.anchor), w = p.reversal.w;
      const [s1, t1] = A[k - 1], [s0, t0] = A[k], [s2, t2] = A[k + 1];
      const c1 = (t0 - t1) / (Math.hypot(s0 - s1, w) - w), c2 = (t0 - t2) / (Math.hypot(s2 - s0, w) - w);
      m[k - 1] = (c1 * (s0 - s1)) / Math.hypot(s0 - s1, w);
      m[k + 1] = (-c2 * (s2 - s0)) / Math.hypot(s2 - s0, w);
      rev = { a: s1, b: s2, s0, t0, c1, c2, w };
    }
    theta = s.map((x) => {
      if (rev && x > rev.a && x < rev.b) return rev.t0 - (x < rev.s0 ? rev.c1 : rev.c2) * (Math.hypot(x - rev.s0, rev.w) - rev.w);
      if (x <= A[0][0]) return A[0][1] + m0 * (x - A[0][0]);
      if (x >= A.at(-1)[0]) return A.at(-1)[1] + m1 * (x - A.at(-1)[0]);
      const i = Math.max(0, A.findIndex((a) => a[0] > x) - 1), hh = h[i], u = (x - A[i][0]) / hh;
      return (2 * u ** 3 - 3 * u ** 2 + 1) * A[i][1] + (u ** 3 - 2 * u ** 2 + u) * hh * m[i]
        + (-2 * u ** 3 + 3 * u ** 2) * A[i + 1][1] + (u ** 3 - u ** 2) * hh * m[i + 1];
    });
  }
  // per-lobe fullness (`lobes` = [{ anchor, strand, f, w }]): one strand's radius scaled by
  // f around one anchor's lobe, fading out over w px, so a lobe can be slimmer or fuller
  // than its neighbours without moving them
  const lobeAt = {};
  if (anchors) anchors.forEach(([x], i) => { lobeAt[i] = x + (p.anchor_shift || 0) + (p.anchor_offsets ? p.anchor_offsets[i] : 0); });
  const lobeScale = (name, x) => {
    let f = 1;
    for (const lb of p.lobes || []) if (lb.strand === name && lobeAt[lb.anchor] !== undefined) f *= 1 + (lb.f - 1) * Math.exp(-(((x - lobeAt[lb.anchor]) / lb.w) ** 2));
    return f;
  };
  // thickness profile along the spine: scales both the radius and the offset
  const swell = (x) => {
    if (!p.swell) return 1;
    const w = p.swell, f = clamp((x / L) * (w.length - 1), 0, w.length - 1), i = Math.min(Math.floor(f), w.length - 2);
    return w[i] + (w[i + 1] - w[i]) * (f - i);
  };
  const Y = [], Bl = [], rY = [], rB = [], hY = [], hB = [];
  const [lenY, lenB] = p.head_len;
  // beading: each strand is fattest mid-lobe (facing the camera or away) and thinner where
  // it passes the side, as twisted balloons are; faded out at the necks
  const bead = (i) => {
    if (!p.bead) return 1;
    // 1 along the body, 0 at both necks (as the fitter's wY, wB)
    const w = smoothstep(h0 * L - p.neck, h0 * L + p.neck * 0.3, s[i]) - smoothstep(h1 * L - p.neck * 0.3, h1 * L + p.neck, s[i]);
    // "front": only swell mid-lobe, so the sides (and the outline) keep the fitted radius
    const f = p.bead_mode === "front" ? Math.sin(theta[i]) ** 2 : Math.sin(theta[i]) ** 2 - 0.5;
    return 1 + p.bead * clamp(w, 0, 1) * f;
  };
  for (let i = 0; i < n; i++) {
    const g = swell(s[i]), a = p.a * g, R = p.R * g;
    const u = add(mul(N[i], Math.cos(theta[i])), mul(B[i], Math.sin(theta[i])));
    const wY = 1 - smoothstep(h0 * L - p.neck, h0 * L + p.neck * 0.3, s[i]);
    const wB = smoothstep(h1 * L - p.neck * 0.3, h1 * L + p.neck, s[i]);
    const shift = mul(u, (wY - wB) * R);
    // the tail circles the neck further out than the rope's squeezed spacing
    const e = mul(u, 2 * (p.wrap || 0) * R);
    Y.push(sub(add(sub(C[i], mul(u, R)), shift), mul(e, wB)));
    Bl.push(add(add(add(C[i], mul(u, R)), shift), mul(e, wY)));
    if (p.heads) {
      // radius profile from each snout: rs at the snout, rm at dm, back to 1 at dn
      const prof = (d, h) => d < h.dm ? h.rs + (h.rm - h.rs) * smoothstep(0, h.dm, d) : h.rm + (1 - h.rm) * smoothstep(h.dm, h.dn, d);
      const [H0, H1] = p.heads;
      hY.push(1 - smoothstep(H0.dm, H0.dn, s[i])); hB.push(1 - smoothstep(H1.dm, H1.dn, L - s[i]));
      rY.push(a * prof(s[i], H0) * bead(i) * lobeScale("yellow", s[i])); rB.push(a * prof(L - s[i], H1) * bead(i) * lobeScale("blue", s[i]));
    } else {
      hY.push(smoothstep(lenY + 40, lenY - 10, s[i]));
      hB.push(smoothstep(L - lenB - 40, L - lenB + 10, s[i]));
      rY.push(a * (1 + (p.head_r - 1) * hY[i]));
      rB.push(a * (1 + (p.head_r - 1) * hB[i]));
    }
  }
  // Yellow runs from its snout (s = 0) to its tail, blue from its tail to its snout
  // (s = L). Each is returned head first.
  const [tailB, tailY] = p.tail;
  let iY = s.findIndex((x) => x > L - tailY), iB = s.findIndex((x) => x >= tailB);
  // end each tail where it is behind the other snake's neck: within `tail_hide` px of the
  // fitted end, at the point where the strand sits furthest from the camera
  if (p.tail_hide) {
    const back = (P, i) => P[i][2] - C[i][2];
    const near = (i0, P) => {
      let bi = i0, bz = Infinity;
      for (let i = 0; i < n; i++) if (Math.abs(s[i] - s[i0]) <= p.tail_hide && back(P, i) < bz) { bz = back(P, i); bi = i; }
      return bi;
    };
    iY = near(iY, Y); iB = near(iB, Bl);
  }
  const tailTaper = (d) => 0.75 + 0.25 * clamp(d / 30, 0, 1);
  // each sample also carries its partner on the other strand (`mate`), the partner's own
  // arc length (`mateS`) and whether the partner's tube is there (`mateW`, 0 past its tail)
  const yellow = { pts: [], r: [], head: [], s: [], mate: [], mateS: [], mateW: [] };
  const blue = { pts: [], r: [], head: [], s: [], mate: [], mateS: [], mateW: [] };
  for (let i = 0; i < iY; i++) {
    yellow.pts.push(Y[i]); yellow.r.push(rY[i] * tailTaper(L - tailY - s[i])); yellow.head.push(hY[i]); yellow.s.push(s[i]);
    yellow.mate.push(Bl[i]); yellow.mateS.push(L - s[i]); yellow.mateW.push(smoothstep(s[iB], s[iB] + 25, s[i]));
  }
  for (let i = n - 1; i >= iB; i--) {
    blue.pts.push(Bl[i]); blue.r.push(rB[i] * tailTaper(s[i] - tailB)); blue.head.push(hB[i]); blue.s.push(L - s[i]);
    blue.mate.push(Y[i]); blue.mateS.push(s[i]); blue.mateW.push(smoothstep(s[iY - 1], s[iY - 1] - 25, s[i]));
  }
  return { spine: C, s, L, theta, yellow, blue };
}

// Resample a strand by its own arc length, so mesh rings are evenly spaced.
function evenly(strand, step) {
  const d = [0];
  for (let i = 1; i < strand.pts.length; i++) d.push(d[i - 1] + norm(sub(strand.pts[i], strand.pts[i - 1])));
  const n = Math.max(8, Math.round(d.at(-1) / step));
  const out = { pts: [], r: [], head: [], mate: strand.mate ? [] : null, press: strand.press ? [] : null, sec: strand.sec ? [] : null,
    s: strand.s ? [] : null, disp: strand.disp ? strand.disp.handles : null };
  let j = 0;
  for (let k = 0; k <= n; k++) {
    const t = (k * d.at(-1)) / n;
    while (j < d.length - 2 && d[j + 1] < t) j++;
    const f = clamp((t - d[j]) / (d[j + 1] - d[j] || 1), 0, 1);
    const lerp = (A) => A[j] + (A[j + 1] - A[j]) * f;
    out.pts.push(add(strand.pts[j], mul(sub(strand.pts[j + 1], strand.pts[j]), f)));
    out.r.push(lerp(strand.r)); out.head.push(lerp(strand.head));
    if (out.mate) out.mate.push(add(strand.mate[j], mul(sub(strand.mate[j + 1], strand.mate[j]), f)));
    if (out.press) out.press.push(lerp(strand.press));
    if (out.sec) out.sec.push([0, 1, 2].map((k) => strand.sec[j][k] + (strand.sec[j + 1][k] - strand.sec[j][k]) * f));
    if (out.s) out.s.push(lerp(strand.s));
  }
  return out;
}

// Gaussian smoothing of a sequence of points (or vectors), sigma in samples, ends clamped.
function gauss(P, sigma) {
  const h = Math.ceil(3 * sigma), w = [];
  for (let k = -h; k <= h; k++) w.push(Math.exp(-(k * k) / (2 * sigma * sigma)));
  return P.map((_, i) => {
    let acc = [0, 0, 0], ws = 0;
    for (let k = -h; k <= h; k++) {
      const j = clamp(i + k, 0, P.length - 1);
      acc = add(acc, mul(P[j], w[k + h])); ws += w[k + h];
    }
    return mul(acc, 1 / ws);
  });
}

// Rotation-minimising frames by the double reflection method (Wang et al. 2008).
function rmf(pts) {
  const n = pts.length;
  const T = gradient(pts).map(unit);
  const r = [];
  let r0 = Math.abs(T[0][1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
  r0 = unit(sub(r0, mul(T[0], dot(r0, T[0]))));
  r.push(r0);
  for (let i = 0; i < n - 1; i++) {
    const v1 = sub(pts[i + 1], pts[i]), c1 = dot(v1, v1);
    const rL = sub(r[i], mul(v1, (2 / c1) * dot(v1, r[i])));
    const tL = sub(T[i], mul(v1, (2 / c1) * dot(v1, T[i])));
    const v2 = sub(T[i + 1], tL), c2 = dot(v2, v2);
    r.push(unit(c2 < 1e-12 ? rL : sub(rL, mul(v2, (2 / c2) * dot(v2, rL)))));
  }
  return { T, N: r, B: r.map((x, i) => cross(T[i], x)) };
}

// A superellipse power: exponent q = 2 is a circle, larger is squarer.
const spow = (x, e) => Math.sign(x) * Math.abs(x) ** e;

// Strand-local radial displacement of the swept surface (the "disp" handles of a spec strand):
//   D(s, psi) = sum_i a_i b((s - s_i) / sig_s_i) b(wrap(psi - psi_i) / sig_psi_i)
// where b(x) = (1 - x^2)^3 on |x| < 1 and 0 beyond (C2, compact), s the strand's own station and
// psi the angle round the strand in the section frame of ellipse(): 0 towards the depth axis d
// (the view direction made perpendicular to the tangent), 90 degrees along the lateral axis
// l = T x d, which lies in the screen plane. sig_s is the half-width of the support in stations,
// sig_psi in degrees (<= 180), a a fraction of the radius: the ring vertex moves along its
// direction to r (1 + D). Handles carry degrees in the spec; this takes them as they are.
const bump = (x) => { const u = 1 - x * x; return u > 0 ? u * u * u : 0; };
export function dispField(handles, s, psi) {
  let D = 0;
  for (const h of handles) {
    const bs = bump((s - h.s) / h.sig_s);
    if (bs <= 0) continue;
    const dp = ((((psi - (h.psi * Math.PI) / 180) % (2 * Math.PI)) + 3 * Math.PI) % (2 * Math.PI)) - Math.PI;
    D += h.a * bs * bump(dp / ((h.sig_psi * Math.PI) / 180));
  }
  return D;
}

// The surface grid of one strand: rings along the body, then caps. Returns positions,
// a per-vertex "head" weight, ring count and radial count; the mesh is closed with a pole
// vertex at each end.
export function strandSurface(strand, opts) {
  const { step = 3, radial = 64, head, smooth = 0, fold = null, press = null, view = [0, 0, 1] } = opts;
  const S = evenly(strand, step);
  // a light smoothing of the centreline (Gaussian, `smooth` samples), so the rings follow
  // its shape and not its sampling
  if (smooth) S.pts = gauss(S.pts, smooth);
  // where the strand bends tighter than its radius allows (radius x curvature near 1, so
  // distant parts of the tube would overlap), smooth its path more, there only
  if (opts.tight) {
    const { boost = 6, from = 0.6, span = 8 } = opts.tight;
    const P = S.pts, n = P.length;
    const kap = P.map((_, i) => {
      const a = P[Math.max(i - span, 0)], b = P[i], c = P[Math.min(i + span, n - 1)];
      const ab = norm(sub(b, a)), bc = norm(sub(c, b)), ac = norm(sub(c, a));
      return ab && bc && ac ? (2 * norm(cross(sub(b, a), sub(c, a)))) / (ab * bc * ac) : 0;
    });
    const sig = gauss(kap.map((k, i) => [clamp((S.r[i] * k - from) / from, 0, 1), 0, 0]), span).map((v) => boost * v[0]);
    S.pts = P.map((_, i) => {
      if (sig[i] < 0.3) return P[i];
      const h = Math.ceil(3 * sig[i]);
      let acc = [0, 0, 0], ws = 0;
      for (let k = -h; k <= h; k++) {
        const w = Math.exp(-(k * k) / (2 * sig[i] * sig[i]));
        acc = add(acc, mul(P[clamp(i + k, 0, n - 1)], w)); ws += w;
      }
      return mul(acc, 1 / ws);
    });
  }
  const { T, N, B } = rmf(S.pts);
  const m = S.pts.length;
  // the curvature vector along the strand, smoothed the same way: where the tube's radius
  // times its curvature towards a side nears 1, consecutive rings cross on that side and
  // the surface folds through itself. `fold` = [x0, x1] limits it softly to x1: the inside
  // of a tight bend is pinched, as a balloon's is, instead of creased.
  const K = fold ? gauss(T.map((_, i) => {
    const a = Math.max(i - 1, 0), b = Math.min(i + 1, m - 1);
    return mul(sub(T[b], T[a]), 1 / (norm(sub(S.pts[b], S.pts[a])) || 1));
  }), Math.max(smooth, 2)) : null;
  // the press (`press` = { k, overlap }): where the two strands' tubes would pass through
  // each other, each is flattened against the plane halfway between the pair, with a soft
  // knee of width k, as two balloons pressed together are; the outer sides don't move
  const pressed = (i, c, X) => {
    if (!press || !S.mate || !S.press || !S.press[i]) return X;
    const nv = sub(S.mate[i], c), dist = norm(nv);
    if (dist < 1e-6) return X;
    const n = mul(nv, 1 / dist), h = dot(sub(X, c), n) - dist / 2, e = press.overlap ?? 1.5, k = press.k ?? 10;
    const hs = Math.min(h, e) - Math.max(k - Math.abs(h - e), 0) ** 2 / (4 * k);
    return sub(X, mul(n, (h - hs) * S.press[i]));
  };
  const pinch = (i, dir, r) => {
    if (!K) return 1;
    const x = r * dot(K[i], dir), [x0, x1] = fold;
    return x <= x0 ? 1 : (x0 + (x1 - x0) * Math.tanh((x - x0) / (x1 - x0))) / x;
  };
  // elliptical sections (`strand.sec` = [ql, qd, psi] per sample, from strandspline.js): the
  // depth axis d is the view direction made perpendicular to the tangent, the lateral axis
  // l = T x d lies in the screen plane, and the unit circle becomes the ellipse with semi-axes
  // ql, qd about (l, d) turned by psi: ql sets the visible width, qd the thickness towards the
  // camera. Where the tangent nearly points at the camera the section blends back to a circle.
  // tools/jaxsurface.py ellipse() is the same map.
  const ellipse = (i, dir) => {
    if (!S.sec) return dir;
    const t = T[i];
    let d = sub(view, mul(t, dot(view, t)));
    const dn = norm(d), lev = smoothstep(0.2, 0.45, dn);
    if (lev <= 0) return dir;
    d = mul(d, 1 / dn);
    const l = cross(t, d), [ql0, qd0, psi0] = S.sec[i];
    const ql = 1 + lev * (ql0 - 1), qd = 1 + lev * (qd0 - 1), psi = lev * psi0;
    const c = Math.cos(psi), sn = Math.sin(psi);
    const a1 = add(mul(l, c), mul(d, sn)), a2 = add(mul(l, -sn), mul(d, c));
    const along = mul(t, dot(dir, t));
    return add(along, add(mul(a1, dot(dir, a1) * ql), mul(a2, dot(dir, a2) * qd)));
  };
  // the displacement field D at ring sample i and unit-circle direction arg (before ellipse()):
  // its psi is the angle in the same (l, d) frame; it fades out with the section frame (where
  // the tangent nearly points at the camera that frame is undefined, and ellipse() is a circle)
  const disp = (i, arg) => {
    if (!S.disp || !S.s) return 0;
    const t = T[i];
    let d = sub(view, mul(t, dot(view, t)));
    const dn = norm(d), lev = smoothstep(0.2, 0.45, dn);
    if (lev <= 0) return 0;
    d = mul(d, 1 / dn);
    const l = cross(t, d);
    return lev * dispField(S.disp, S.s[i], Math.atan2(dot(arg, l), dot(arg, d)));
  };
  // cap profiles: index 0 is the snout (blunt, superelliptic), the far end is the tail
  // opts.capLen scales either cap's length: 0 closes a cut part (scene.js extra.cut) with a flat
  // disc, inside the region's own surface, where a round cap would poke out
  const capLen = opts.capLen || [1, 1];
  const caps = [
    { at: 0, dir: mul(T[0], -1), len: head.snoutLen * S.r[0] * capLen[0], q: head.snoutQ, rings: 14 },
    { at: m - 1, dir: T[m - 1], len: S.r[m - 1] * capLen[1], q: 2, rings: 12 },
  ];
  const up = [0, 1, 0];
  // the head's cross-section: e2 is world up made perpendicular to the strand, e1 is
  // lateral; the section is a superellipse, wider than tall
  const offset = (i, c, r, h, phi) => {
    let e2 = sub(up, mul(T[i], dot(up, T[i])));
    // the head shape fades out smoothly where the strand turns vertical (the neck), so the
    // section never jumps between rings
    const level = smoothstep(0.3, 0.7, norm(e2));
    e2 = level > 0 ? unit(e2) : N[i];
    const e1 = cross(e2, T[i]);
    // angle of e1 in the (N, B) plane, so the ring parameter stays continuous
    const psi = Math.atan2(dot(e1, B[i]), dot(e1, N[i]));
    const al = phi - psi;
    const w = h * level;
    const ca = Math.cos(al), sa = Math.sin(al);
    const qx = 2 / (2 + (head.q - 2) * w);
    const hx = (1 + (head.wide - 1) * w) * spow(ca, qx), hy = (1 + (head.flat - 1) * w) * spow(sa, qx);
    const circ = add(mul(N[i], Math.cos(phi)), mul(B[i], Math.sin(phi)));
    const sq = add(mul(e1, hx), mul(e2, hy));
    const arg = add(mul(circ, 1 - w), mul(sq, w));
    const dir = ellipse(i, arg);
    const X = add(c, mul(dir, r * pinch(i, dir, r) * (1 + disp(i, arg))));
    return pressed(i, c, X);
  };
  const rings = [], centres = [];
  const ringOf = (i, c, r, h) => {
    centres.push(c);
    const ring = [];
    for (let j = 0; j < radial; j++) ring.push(offset(i, c, r, h, (2 * Math.PI * j) / radial));
    return ring;
  };
  // snout cap rings, from the tip inwards
  const [c0, c1] = caps;
  const capRings = (cap, reverse) => {
    const out = [];
    for (let k = 1; k < cap.rings; k++) {
      const beta = (Math.PI / 2) * (1 - k / cap.rings); // pi/2 at the tip, 0 at the body
      const along = cap.len * spow(Math.sin(beta), 2 / cap.q);
      const rad = spow(Math.cos(beta), 2 / cap.q);
      const i = cap.at;
      out.push(ringOf(i, add(S.pts[i], mul(cap.dir, along)), S.r[i] * rad, S.head[i]));
    }
    return reverse ? out.reverse() : out;
  };
  const tip0 = add(S.pts[0], mul(c0.dir, c0.len));
  const tip1 = add(S.pts[m - 1], mul(c1.dir, c1.len));
  rings.push(...capRings(c0, false));
  for (let i = 0; i < m; i++) rings.push(ringOf(i, S.pts[i], S.r[i], S.head[i]));
  rings.push(...capRings(c1, true));
  // the body vertex of sample i at the section angle psi (radians; the frame of dispField), for
  // placing handles: tools/ffd_locate.mjs
  const pointAt = (i, psi) => {
    const t = T[i];
    let d = sub(view, mul(t, dot(view, t)));
    const dn = norm(d);
    d = mul(d, 1 / (dn || 1));
    const l = cross(t, d), arg = add(mul(d, Math.cos(psi)), mul(l, Math.sin(psi)));
    return offset(i, S.pts[i], S.r[i], 0, Math.atan2(dot(arg, B[i]), dot(arg, N[i])));
  };
  return { rings, centres, tips: [tip0, tip1], radial, centre: S, frames: { T, N, B }, pointAt };
}

// Balls along both strands, for ambient occlusion and the eyes' placement.
export function balls(strands, spacing) {
  const out = [];
  strands.forEach((st, id) => {
    let acc = Infinity;
    for (let i = 0; i < st.pts.length; i++) {
      if (i) acc += norm(sub(st.pts[i], st.pts[i - 1]));
      if (acc >= spacing) { out.push([...st.pts[i], st.r[i], id]); acc = 0; }
    }
  });
  return out;
}

// Ambient occlusion from analytic balls and the ground plane, per vertex.
export function occlusion(pos, nrm, ballList, ground, opts, own = -1) {
  const { k = 0.1, groundK = 0.6, groundFall = 60, spacing, contact = 0.6, contactFall = 14 } = opts;
  const out = new Float32Array(pos.length / 3);
  for (let v = 0; v < out.length; v++) {
    const x = pos[3 * v], y = pos[3 * v + 1], z = pos[3 * v + 2];
    const nx = nrm[3 * v], ny = nrm[3 * v + 1], nz = nrm[3 * v + 2];
    let occ = 0, touch = 0;
    for (let b = 0; b < ballList.length; b++) {
      const B = ballList[b];
      const dx = B[0] - x, dy = B[1] - y, dz = B[2] - z;
      const d2 = dx * dx + dy * dy + dz * dz;
      const lim = 4 * B[3];
      if (d2 > lim * lim) continue;
      const d = Math.sqrt(d2);
      // contact: the groove where this surface meets the other strand
      if (B[4] !== undefined && B[4] !== own) touch = Math.max(touch, 1 - smoothstep(B[3], B[3] + contactFall, d));
      if (d < B[3] * 1.01) continue;
      const c = (nx * dx + ny * dy + nz * dz) / d;
      if (c <= 0) continue;
      occ += c * (B[3] * B[3]) / d2 * (spacing / (2 * B[3]));
    }
    const h = Math.max(0, y - ground);
    const g = Math.max(0, -ny) * Math.exp(-h / groundFall) * groundK;
    out[v] = clamp((1 - k * occ - g) * (1 - contact * touch), 0.08, 1);
  }
  return out;
}

export { sub, add, mul, dot, cross, norm, unit };

// What a baked head depends on: the head and neck params, and the strand where each neck
// joins it (position samples from 20 px before the join to past the dive), rounded. Body
// changes elsewhere leave it unchanged, so a bake stays valid for them.
export function headKey(params, lines) {
  const near = (name, nk) => {
    const st = lines[name], out = [];
    st.s.forEach((x, i) => { if (x > nk.join_s - 20 && x < nk.join_s + 60) out.push(st.pts[i].map((v) => Math.round(v * 100) / 100), Math.round(st.r[i] * 100) / 100); });
    return out;
  };
  return paramsHash(JSON.stringify({ h: params.head_profiles, n: params.necks, k: params.neck_blend ?? 12, e: params.cam.elev,
    y: near("yellow", params.necks[0]), b: near("blue", params.necks[1]) }));
}

// FNV-1a over a string, as 16 hex digits (two 32-bit halves): ties a baked mesh file to the
// exact params it was made from (tools/bake_heads.mjs writes it, scene.js checks it)
export function paramsHash(text) {
  let a = 0x811c9dc5, b = 0x01000193 ^ 0x5bd1e995;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    a = Math.imul(a ^ c, 0x01000193) >>> 0; b = Math.imul(b ^ c, 0x01000197) >>> 0;
  }
  return a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0");
}

// ---- heads: a round cone smooth-unioned with the neck, as a signed distance field

// Exact signed distance to a round cone: spheres of radius r1 at a and r2 at b, and the
// cone tangent to both (Inigo Quilez).
export function sdRoundCone(p, a, b, r1, r2) {
  const ba = sub(b, a), l2 = dot(ba, ba), rr = r1 - r2, a2 = l2 - rr * rr, il2 = 1 / l2;
  const pa = sub(p, a), y = dot(pa, ba), z = y - l2;
  const xv = sub(mul(pa, l2), mul(ba, y)), x2 = dot(xv, xv), y2 = y * y * l2, z2 = z * z * l2;
  const k = Math.sign(rr) * rr * rr * x2;
  if (Math.sign(z) * a2 * z2 > k) return Math.sqrt(x2 + z2) * il2 - r2;
  if (Math.sign(y) * a2 * y2 < k) return Math.sqrt(x2 + y2) * il2 - r1;
  return (Math.sqrt(x2 * a2 * il2) + y * rr) * il2 - r1;
}
const smin = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k * 0.25; };
// the cubic smooth minimum: C2 where smin is only C1 (smin's curvature jumps at |a - b| = k, which shows as
// straight kinks in a zebra render of a blend); its largest rounding is k / 6 where smin's is k / 4
const smin3 = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * h * k / 6; };

// Surface nets: one vertex per grid cell the surface crosses, at the mean of its edge
// crossings; one quad per grid edge the surface crosses. Normals from the field's gradient.
export function surfaceNets(f, lo, hi, step) {
  const dims = [0, 1, 2].map((c) => Math.ceil((hi[c] - lo[c]) / step) + 1);
  const [nx, ny, nz] = dims;
  const at = (i, j, k) => [lo[0] + i * step, lo[1] + j * step, lo[2] + k * step];
  const V = new Float32Array(nx * ny * nz);
  for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) V[i + nx * (j + ny * k)] = f(at(i, j, k));
  const val = (i, j, k) => V[i + nx * (j + ny * k)];
  const cx = nx - 1, cy = ny - 1, cz = nz - 1;
  const vid = new Int32Array(cx * cy * cz).fill(-1);
  const cell = (i, j, k) => i + cx * (j + cy * k);
  const C8 = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
  const E12 = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
  const pos = [];
  for (let k = 0; k < cz; k++) for (let j = 0; j < cy; j++) for (let i = 0; i < cx; i++) {
    const v = C8.map(([a, b, c]) => val(i + a, j + b, k + c));
    if (v.every((x) => x < 0) || v.every((x) => x >= 0)) continue;
    let sx = 0, sy = 0, sz = 0, n = 0;
    for (const [a, b] of E12) {
      if ((v[a] < 0) === (v[b] < 0)) continue;
      const t = v[a] / (v[a] - v[b]);
      sx += C8[a][0] + (C8[b][0] - C8[a][0]) * t; sy += C8[a][1] + (C8[b][1] - C8[a][1]) * t; sz += C8[a][2] + (C8[b][2] - C8[a][2]) * t; n++;
    }
    vid[cell(i, j, k)] = pos.length / 3;
    pos.push(...at(i + sx / n, j + sy / n, k + sz / n));
  }
  const idx = [];
  const quad = (a, b, c, d) => { if (a < 0 || b < 0 || c < 0 || d < 0) return; idx.push(a, b, c, a, c, d); };
  for (let k = 1; k < cz; k++) for (let j = 1; j < cy; j++) for (let i = 0; i < cx; i++)   // x edges
    if ((val(i, j, k) < 0) !== (val(i + 1, j, k) < 0)) quad(vid[cell(i, j - 1, k - 1)], vid[cell(i, j, k - 1)], vid[cell(i, j, k)], vid[cell(i, j - 1, k)]);
  for (let k = 1; k < cz; k++) for (let j = 0; j < cy; j++) for (let i = 1; i < cx; i++)   // y edges
    if ((val(i, j, k) < 0) !== (val(i, j + 1, k) < 0)) quad(vid[cell(i - 1, j, k - 1)], vid[cell(i, j, k - 1)], vid[cell(i, j, k)], vid[cell(i - 1, j, k)]);
  for (let k = 0; k < cz; k++) for (let j = 1; j < cy; j++) for (let i = 1; i < cx; i++)   // z edges
    if ((val(i, j, k) < 0) !== (val(i, j, k + 1) < 0)) quad(vid[cell(i - 1, j - 1, k)], vid[cell(i, j - 1, k)], vid[cell(i, j, k)], vid[cell(i - 1, j, k)]);
  // normals from the gradient, and each triangle wound to agree with them
  const nrm = new Float32Array(pos.length), h = step / 2;
  for (let v = 0; v < pos.length / 3; v++) {
    const p = [pos[3 * v], pos[3 * v + 1], pos[3 * v + 2]];
    const g = unit([0, 1, 2].map((c) => { const a = [...p], b = [...p]; a[c] += h; b[c] -= h; return f(a) - f(b); }));
    nrm.set(g, 3 * v);
  }
  for (let t = 0; t < idx.length; t += 3) {
    const P = [0, 1, 2].map((q) => [pos[3 * idx[t + q]], pos[3 * idx[t + q] + 1], pos[3 * idx[t + q] + 2]]);
    const fn = cross(sub(P[1], P[0]), sub(P[2], P[0]));
    const vn = [0, 1, 2].reduce((acc, q) => add(acc, [nrm[3 * idx[t + q]], nrm[3 * idx[t + q] + 1], nrm[3 * idx[t + q] + 2]]), [0, 0, 0]);
    if (dot(fn, vn) < 0) [idx[t + 1], idx[t + 2]] = [idx[t + 2], idx[t + 1]];
  }
  return { positions: new Float32Array(pos), normals: nrm, indices: idx };
}

// A head: the round cone from the back of the head to the snout (image coordinates in the
// params), smooth-unioned with the neck, which is the strand from `cone.cut` to `join` (arc
// length from the snout end). The tube mesh takes over at `join`.
export function headSurface(strand, cone, elev, { join, k = 24, step = 2.5, seg = 6, shrink = 0.4 } = {}) {
  const w = (x, y) => [x, -y / Math.cos(elev), 0];
  const B = w(cone.bx, cone.by), S = w(cone.sx, cone.sy);
  const neck = [];
  let last = null;
  for (let i = 0; i < strand.pts.length && strand.s[i] <= join; i++) {
    if (strand.s[i] < cone.cut) continue;
    if (!last || norm(sub(strand.pts[i], last)) >= seg) { neck.push([strand.pts[i], strand.r[i] - shrink]); last = strand.pts[i]; }
  }
  const f = (x) => {
    let t = Infinity;
    for (let i = 0; i < neck.length - 1; i++) t = Math.min(t, sdRoundCone(x, neck[i][0], neck[i + 1][0], neck[i][1], neck[i + 1][1]));
    return smin(sdRoundCone(x, B, S, cone.rb, cone.rs), t, k);
  };
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const [c, r] of [[B, cone.rb], [S, cone.rs], ...neck]) for (let q = 0; q < 3; q++) { lo[q] = Math.min(lo[q], c[q] - r - k); hi[q] = Math.max(hi[q], c[q] + r + k); }
  return { ...surfaceNets(f, lo, hi, step), balls: [[...B, cone.rb], [...S, cone.rs]] };
}

// ---- heads v2: a swept-profile head and a constructed neck (tools/headmodel.py is the same)
//
// Head frame: t in [0, 1] from the rear of the head to the snout tip, v up in the picture
// plane, z towards the camera. Upper outline u = U(t) sqrt(t(1-t)), lower l = -Lo(t)
// sqrt(t(1-t)), depth rz = D(t) sqrt(t(1-t)); U, Lo, D are Catmull-Rom curves through control
// values. Each section is two half-superellipses glued at the cheek line m = l + beta (u - l).

export function catmull(ctrl, t) {
  const K = ctrl.length, P = [2 * ctrl[0] - ctrl[1], ...ctrl, 2 * ctrl[K - 1] - ctrl[K - 2]];
  const x = clamp(t, 0, 1) * (K - 1), i = Math.min(Math.floor(x), K - 2), u = x - i;
  const [p0, p1, p2, p3] = [P[i], P[i + 1], P[i + 2], P[i + 3]];
  return 0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u);
}

export function headFrame(h, elev) {
  const w = (q) => [q[0], -q[1] / Math.cos(elev), 0];
  const R0 = w(h.rear), Tp = w(h.tip), L = norm(sub(Tp, R0)), d = mul(sub(Tp, R0), 1 / L);
  let n = [-d[1], d[0], 0];
  if (n[1] < 0) n = mul(n, -1);
  return { R0, d, n, L, tip: Tp };
}

export function headDistance(h, F, p) {
  const rel = sub(p, F.R0), t = dot(rel, F.d) / F.L;
  if (t >= 1) return norm(sub(p, F.tip));
  if (t <= 0) return norm(sub(p, F.R0));
  const v = dot(rel, F.n), z = p[2], s = Math.sqrt(t * (1 - t));
  const u = catmull(h.U, t) * s, l = -catmull(h.Lo, t) * s, rz = Math.max(catmull(h.D, t) * s, 1e-6);
  const m = l + h.beta * (u - l), hv = Math.max(v >= m ? u - m : m - l, 1e-6);
  const rho = ((Math.abs(v - m) / hv) ** h.q + (Math.abs(z) / rz) ** h.q) ** (1 / h.q);
  // the scale is the same above and below the cheek line, so the field (and so the normals
  // taken from its gradient) stays smooth across it; "split" is the earlier, kinked version,
  // kept to reproduce the checkpoint
  return (rho - 1) * (h.field_scale === "split" ? Math.min(hv, rz) : Math.min(rz, 0.5 * (u - l)));
}

// The head as the union of its planar sections (opt-in: h.field = "sections"; the default
// stays the estimate above). Its distance is the minimum over stations t' of
// sqrt(axial offset^2 + in-plane distance to section t'^2): exact for any section shape, with
// the in-plane distance taken along the ray from the section's centre and corrected to first
// order by the boundary normal. Searched in a bracket around the point's own station. Points
// with |estimate| beyond `band` keep the estimate; the sign is the estimate's, so the zero set
// is unchanged. (tools/headmodel.py: head_distance_sections, the same.)
export function headDistanceSections(h, F, p, { band = 30, coarse = 9, refine = 14 } = {}) {
  const base = headDistance(h, F, p);
  if (Math.abs(base) >= band) return base;
  const rel = sub(p, F.R0), t0 = dot(rel, F.d) / F.L, v = dot(rel, F.n), z = p[2], q = h.q;
  const inside = base < 0;
  const sec = (tp) => {
    const s = Math.sqrt(Math.max(tp * (1 - tp), 0));
    const u = catmull(h.U, tp) * s, l = -catmull(h.Lo, tp) * s, rz = Math.max(catmull(h.D, tp) * s, 1e-9);
    const m = l + h.beta * (u - l), hu = Math.max(u - m, 1e-9), hl = Math.max(m - l, 1e-9);
    const dv = v - m, rho = Math.max(Math.hypot(dv, z), 1e-12), c = dv / rho, sn = z / rho;
    const hv = dv >= 0 ? hu : hl;
    const Rr = 1 / ((Math.abs(c) / hv) ** q + (Math.abs(sn) / rz) ** q) ** (1 / q);
    const a = Rr * c, b = Rr * sn;
    let gx = Math.sign(a) * Math.abs(a / hv) ** (q - 1) / hv, gy = Math.sign(b) * Math.abs(b / rz) ** (q - 1) / rz;
    const gl = Math.hypot(gx, gy) || 1; gx /= gl; gy /= gl;
    const cosa = clamp(Math.abs(c * gx + sn * gy), 0.05, 1);
    const gap = (rho - Rr) * cosa, ax = (tp - t0) * F.L;
    return inside ? Math.hypot(ax, gap) : Math.hypot(ax, Math.max(gap, 0));
  };
  const w = (band + 8) / F.L;
  let lo = clamp(t0 - w, 0, 1), hi = clamp(t0 + w, 0, 1);
  if (t0 > 1) lo = 1 - w;
  if (t0 < 0) hi = w;
  if (hi - lo < 1e-6) hi = lo + 1e-6;
  let best = Infinity, bt = lo;
  for (let k = 0; k < coarse; k++) {
    const tp = lo + ((hi - lo) * k) / (coarse - 1), d = sec(tp);
    if (d < best) { best = d; bt = tp; }
  }
  const step = (hi - lo) / (coarse - 1), gr = (Math.sqrt(5) - 1) / 2;
  let a = clamp(bt - step, 0, 1), b = clamp(bt + step, 0, 1);
  let c1 = b - gr * (b - a), c2 = a + gr * (b - a), f1 = sec(c1), f2 = sec(c2);
  for (let i = 0; i < refine; i++) {
    if (f1 < f2) { b = c2; c2 = c1; f2 = f1; c1 = b - gr * (b - a); f1 = sec(c1); }
    else { a = c1; c1 = c2; f1 = f2; c2 = a + gr * (b - a); f2 = sec(c2); }
  }
  const dist = Math.min(f1, f2, best);
  return inside ? -dist : dist;
}

// position, unit tangent (towards larger arc) and curvature vector of a strand at spine arc `at`
export function strandAt(strand, at) {
  const P = strand.pts, d = strand.s;
  const sl = [0];
  for (let i = 1; i < P.length; i++) sl.push(sl[i - 1] + norm(sub(P[i], P[i - 1])));
  const interp = (xs, ys, x) => {
    let j = 0;
    while (j < xs.length - 2 && xs[j + 1] < x) j++;
    const f = clamp((x - xs[j]) / (xs[j + 1] - xs[j] || 1), 0, 1);
    return ys[j] + (ys[j + 1] - ys[j]) * f;
  };
  const s0 = interp(d, sl, at);
  const Q = [-12, -6, 0, 6, 12].map((o) => [0, 1, 2].map((c) => interp(sl, P.map((q) => q[c]), s0 + o)));
  const T = mul(sub(Q[3], Q[1]), 1 / 12), T1 = mul(sub(Q[4], Q[2]), 1 / 12), T0 = mul(sub(Q[2], Q[0]), 1 / 12);
  return { J: Q[2], T: unit(T), K: mul(sub(unit(T1), unit(T0)), 1 / 12), arc: s0, sl };
}

function quintic(P0, V0, A0, A1, V1, P1, t) {
  const t2 = t * t, t3 = t2 * t, t4 = t3 * t, t5 = t4 * t;
  const h = [1 - 10 * t3 + 15 * t4 - 6 * t5, t - 6 * t3 + 8 * t4 - 3 * t5, 0.5 * t2 - 1.5 * t3 + 1.5 * t4 - 0.5 * t5,
    0.5 * t3 - t4 + 0.5 * t5, -4 * t3 + 7 * t4 - 3 * t5, 10 * t3 - 15 * t4 + 6 * t5];
  return [0, 1, 2].map((c) => h[0] * P0[c] + h[1] * V0[c] + h[2] * A0[c] + h[3] * A1[c] + h[4] * V1[c] + h[5] * P1[c]);
}

// the neck: from Q inside the head to J on the strand, matching J's position, tangent and
// curvature; its radius eases from r_top to the strand's radius at J
export function neckCurve(nk, h, F, at, rJ, n = 48) {
  const Q = add(add(F.R0, mul(F.d, nk.tQ * F.L)), mul(F.n, nk.vQ));
  const ang = (nk.angQ * Math.PI) / 180, dQ = add(mul(F.d, Math.cos(ang)), mul(F.n, Math.sin(ang)));
  const out = [];
  for (let k = 0; k < n; k++) {
    const t = k / (n - 1);
    const c = quintic(Q, mul(dQ, nk.alpha), [0, 0, 0], mul(at.K, nk.beta * nk.beta), mul(at.T, nk.beta), at.J, t);
    const e = smoothstep(nk.tau_a, 1, t);
    // an optional waist narrows the middle of the neck (the throat under the jaw)
    out.push([c, nk.r_top + (rJ - nk.r_top) * e - (nk.waist || 0) * Math.sin(Math.PI * t) ** 2]);
  }
  // waist_back (0-1): the share of the waist taken off the back of the neck instead of pinching
  // both sides; the throat edge stays where the plain waist puts it, the back edge moves out by
  // waist_back x waist sin^2 (the centre moves back by half of it, the radius grows by half).
  // It fades out over waist_back_fade (tau, default 0.35-0.6): below that the neck is as it was,
  // so its crossing with the body tube's start cap stays where it was, hidden under the coil
  // (filled further down, that crossing comes round the throat as a visible ring)
  const wb = nk.waist_back || 0, [wf0, wf1] = nk.waist_back_fade || [0.35, 0.6];
  if (wb && nk.waist) {
    // sideways only: perpendicular to the neck in the x-y plane (no shift along the neck, which
    // bunches the chain and bends it, and none in depth)
    const C0 = out.map((o) => o[0]);
    for (let k = 0; k < n; k++) {
      const t = k / (n - 1), s2 = Math.sin(Math.PI * t) ** 2;
      const T = sub(C0[Math.min(k + 1, n - 1)], C0[Math.max(k - 1, 0)]);
      let nb = unit([-T[1], T[0], 0]);
      if (dot(nb, F.d) > 0) nb = mul(nb, -1);
      const h2 = 0.5 * wb * nk.waist * s2 * (1 - smoothstep(wf0, wf1, t));
      out[k] = [add(out[k][0], mul(nb, h2)), out[k][1] + h2];
    }
  }
  return out;
}

// head + neck as one field. Past J the neck runs on along the strand for `dive` px with a
// radius just above the tube's that sinks below it, so the visible surface hands over to the
// tube without two surfaces coinciding.
export function headSurface2(strand, h, nk, elev, { k = 12, step = 2.5, dive = 30, parts = "both" } = {}) {
  const F = headFrame(h, elev);
  const at = strandAt(strand, nk.join_s);
  const iJ = strand.s.findIndex((x) => x >= nk.join_s);
  const rJ = strand.r[iJ];
  const chain = neckCurve(nk, h, F, at, rJ + 0.3);
  // the dive: strand samples past J
  for (let i = iJ + 1; i < strand.pts.length; i++) {
    const past = at.sl[i] - at.arc;
    if (past > dive) break;
    if (past < 4) continue;
    chain.push([strand.pts[i], strand.r[i] + 0.3 - 1.8 * smoothstep(0, dive, past)]);
  }
  // bounding spheres for a quick reject
  const cones = [];
  for (let i = 0; i < chain.length - 1; i++) {
    const [a, ra] = chain[i], [b, rb] = chain[i + 1];
    cones.push({ a, b, ra, rb, c: mul(add(a, b), 0.5), R: norm(sub(b, a)) / 2 + Math.max(ra, rb) });
  }
  // optional nape (necks[i].nape = { a: [t, v, r, z], b: [t, v, r, z] }): one more round-cone in the neck
  // field, from a to b, each end a sphere in the head frame (t along the head from the rear as a fraction of
  // its length, v up and z towards the camera in px, radius r in px). It fills the corner where the neck leaves
  // the head's rear cap, so the cap's outline runs into the neck's tangentially. Absent, nothing changes.
  if (nk.nape) {
    const at = ([t, v, , z]) => add(add(F.R0, mul(F.d, t * F.L)), add(mul(F.n, v), [0, 0, z]));
    const [a, b] = [at(nk.nape.a), at(nk.nape.b)], [ra, rb] = [nk.nape.a[2], nk.nape.b[2]];
    cones.push({ a, b, ra, rb, c: mul(add(a, b), 0.5), R: norm(sub(b, a)) / 2 + Math.max(ra, rb) });
  }
  const neckD = (x) => {
    let best = Infinity;
    for (const cn of cones) {
      if (norm(sub(x, cn.c)) - cn.R > best) continue;
      best = Math.min(best, sdRoundCone(x, cn.a, cn.b, cn.ra, cn.rb));
    }
    return best;
  };
  // `parts` (diagnostics only): mesh the head field or the neck field alone
  const hd = h.field === "sections" ? (x) => headDistanceSections(h, F, x) : (x) => headDistance(h, F, x);
  // optional per-neck blend: nk.blend = "cubic" uses the C2 smooth minimum, with radius nk.k (default k). The head's
  // section distance is exact only within its band (30), so the blend radius has to stay under that.
  const cubic = nk.blend === "cubic", kb = cubic ? nk.k ?? k : k;
  const f = parts === "head" ? hd : parts === "neck" ? neckD : cubic ? (x) => smin3(hd(x), neckD(x), kb) : (x) => smin(hd(x), neckD(x), k);
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  const grow = (c, r) => { for (let q = 0; q < 3; q++) { lo[q] = Math.min(lo[q], c[q] - r - k); hi[q] = Math.max(hi[q], c[q] + r + k); } };
  for (const [c, r] of chain) grow(c, r);
  for (let i = 0; i <= 20; i++) {
    const t = i / 20, s = Math.sqrt(t * (1 - t));
    const c = add(F.R0, mul(F.d, t * F.L));
    grow(c, Math.max(catmull(h.U, t), catmull(h.Lo, t), catmull(h.D, t)) * s + 2);
  }
  // balls for ambient occlusion: the neck chain and the head's axis
  const balls = chain.filter((_, i) => i % 3 === 0).map(([c, r]) => [...c, r]);
  for (let i = 1; i < 10; i++) {
    const t = i / 10, s = Math.sqrt(t * (1 - t));
    balls.push([...add(F.R0, mul(F.d, t * F.L)), ((catmull(h.U, t) + catmull(h.Lo, t)) / 2) * s]);
  }
  return { ...surfaceNets(f, lo, hi, step), balls, chain, frame: F };
}
