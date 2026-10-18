// The spline body: each strand an independent clamped cubic B-spline centreline in 3D and a
// cubic B-spline radius, over the strand's own station u (the `s` field the scene uses: spine
// arc length from that snake's snout end; yellow's is the spine station, blue's is L - station).
// The NumPy reference is tools/strandspline.py (same spec, same sampling); tools/fit_splines.py
// writes the specs (spline-*.json).
//
// strandsFromSpec(spec) returns { yellow, blue } in the shape centrelines() returns them, for
// createScene's `body` option: pts sampled ~spec.step (0.5) px apart in their own arc length,
// r, head (0), s, and mate / mateS / mateW for the press. The mate is the partner at the same
// shared station (spec.mate = "station", the default: the twist partner, as centrelines() pairs
// them), or the closest partner point within spec.mate_window station px (spec.mate = "closest").

const P = 3;

export function knots(s0, s1, nseg) {
  const t = [];
  for (let i = 0; i < P; i++) t.push(s0);
  for (let i = 0; i <= nseg; i++) t.push(s0 + ((s1 - s0) * i) / nseg);
  for (let i = 0; i < P; i++) t.push(s1);
  return t;
}

// the span holding u and its P + 1 non-zero basis values (Cox-de Boor, the triangular scheme)
function basisAt(t, u) {
  const K = t.length, lo = t[P], hi = t[K - P - 1];
  u = Math.min(hi, Math.max(lo, u));
  let i = P;
  while (i < K - P - 2 && t[i + 1] <= u) i++;
  const N = [1], left = [], right = [];
  for (let j = 1; j <= P; j++) {
    left[j] = u - t[i + 1 - j]; right[j] = t[i + j] - u;
    let saved = 0;
    for (let r = 0; r < j; r++) {
      const den = right[r + 1] + left[j - r], tmp = den > 0 ? N[r] / den : 0;
      N[r] = saved + right[r + 1] * tmp;
      saved = left[j - r] * tmp;
    }
    N[j] = saved;
  }
  return { i, N }; // control points i - P .. i
}

export function evalStrand(st, u) {
  const t = st._t || (st._t = knots(st.s0, st.s1, st.nseg));
  const tr = st._tr || (st._tr = knots(st.s0, st.s1, st.rseg ?? st.nseg));
  const a = basisAt(t, u), b = basisAt(tr, u);
  const X = [0, 0, 0];
  for (let k = 0; k <= P; k++) { const c = st.ctrl[a.i - P + k]; X[0] += a.N[k] * c[0]; X[1] += a.N[k] * c[1]; X[2] += a.N[k] * c[2]; }
  let r = 0;
  for (let k = 0; k <= P; k++) r += b.N[k] * st.rctrl[b.i - P + k];
  return { X, r };
}

// even arc-length samples: a dense fixed grid in u, its chord length, then interpolation
export function arcSample(st, step = 0.5, densePerSpan = 24) {
  const nd = st.nseg * densePerSpan + 1, ud = [], cum = [0];
  let prev = null;
  for (let k = 0; k < nd; k++) {
    const u = st.s0 + ((st.s1 - st.s0) * k) / (nd - 1), { X } = evalStrand(st, u);
    if (prev) cum.push(cum.at(-1) + Math.hypot(X[0] - prev[0], X[1] - prev[1], X[2] - prev[2]));
    ud.push(u); prev = X;
  }
  const n = Math.round(cum.at(-1) / step) + 1, us = [], pts = [], r = [];
  let j = 0;
  for (let k = 0; k < n; k++) {
    const a = (k * cum.at(-1)) / (n - 1);
    while (j < nd - 2 && cum[j + 1] < a) j++;
    const f = Math.min(1, Math.max(0, (a - cum[j]) / (cum[j + 1] - cum[j] || 1)));
    const u = ud[j] + (ud[j + 1] - ud[j]) * f, e = evalStrand(st, u);
    us.push(u); pts.push(e.X); r.push(e.r);
  }
  return { u: us, pts, r };
}

const smoothstep = (e0, e1, x) => { const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); };

export function strandsFromSpec(spec) {
  const step = spec.step ?? 0.5, L = spec.L, mode = spec.mate ?? "station", win = spec.mate_window ?? 80;
  const out = {};
  for (const name of ["yellow", "blue"]) out[name] = arcSample(spec[name], step);
  const shared = (name, u) => (name === "yellow" ? u : L - u);
  for (const [name, other] of [["yellow", "blue"], ["blue", "yellow"]]) {
    const A = out[name], B = out[other], so = spec[other];
    const st = { pts: A.pts, r: A.r, s: A.u, head: A.u.map(() => 0), mate: [], mateS: [], mateW: [] };
    for (let i = 0; i < A.u.length; i++) {
      let m, ms;
      if (mode === "closest") {
        // closest partner sample within the station window (diagnostic)
        const si = shared(name, A.u[i]), p = A.pts[i];
        let bd = Infinity, bj = 0;
        for (let j = 0; j < B.u.length; j++) {
          if (Math.abs(shared(other, B.u[j]) - si) > win) continue;
          const q = B.pts[j], d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2;
          if (d < bd) { bd = d; bj = j; }
        }
        m = B.pts[bj]; ms = B.u[bj];
      } else {
        ms = L - A.u[i];
        m = evalStrand(so, Math.min(so.s1, Math.max(so.s0, ms))).X;
      }
      st.mate.push(m); st.mateS.push(ms); st.mateW.push(smoothstep(0, 25, so.s1 - ms));
    }
    out[name] = st;
  }
  // drop the evaluation caches from the spec objects
  for (const name of ["yellow", "blue"]) { delete spec[name]._t; delete spec[name]._tr; }
  return out;
}
