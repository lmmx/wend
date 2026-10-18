// The spline body (strandspline.js) as a `geo` module for diag-clay.html, so the old and the
// new body go through exactly the same clay / zebra setup. ?spec= names the spec file.
import { strandsFromSpec } from "./strandspline.js";
const q = new URLSearchParams(location.search);
const spec = await (await fetch(q.get("spec") || "spline-first.json")).json();
export function centrelines() {
  const b = strandsFromSpec(spec);
  return { yellow: b.yellow, blue: b.blue };
}
