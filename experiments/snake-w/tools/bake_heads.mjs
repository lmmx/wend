// Bake the head-and-neck meshes (the slow part of the build) for a params file, so pages
// load them instead of meshing the head field. Usage: node bake_heads.mjs params.json out.json [spec.json]
// With a spline spec (strandspline.js), the heads follow its strands, as the pages build them.
// The output holds, per head, its positions, normals, indices (base64) and AO balls; scene.js
// uses it when given `bakedHeads`, and checks a hash of what the heads depend on (headKey) so a
// stale bake is not used.
import { readFileSync, writeFileSync } from "node:fs";
const G = await import(new URL("../snakes/geometry.js", import.meta.url));
const [paramsPath, out, specPath] = process.argv.slice(2);
const text = readFileSync(paramsPath, "utf8"), params = JSON.parse(text);
const elev = (params.cam.elev * Math.PI) / 180;
let lines = G.centrelines(params);
if (specPath) {
  const { strandsFromSpec } = await import(new URL("../snakes/strandspline.js", import.meta.url));
  const spec = JSON.parse(readFileSync(specPath, "utf8"));
  if (spec.tube) params.tube = { ...(params.tube || {}), ...spec.tube };
  lines = { ...lines, ...strandsFromSpec(spec) };
}
const b64 = (a) => Buffer.from(a.buffer, a.byteOffset, a.byteLength).toString("base64");
const heads = {};
const t0 = Date.now();
["yellow", "blue"].forEach((name, i) => {
  const h = G.headSurface2(lines[name], params.head_profiles[i], params.necks[i], elev, { k: params.neck_blend ?? 12, parts: "both" });
  heads[name] = { positions: b64(new Float32Array(h.positions)), normals: b64(new Float32Array(h.normals)),
    indices: b64(new Uint32Array(h.indices)), balls: h.balls };
});
const hash = G.headKey(params, lines);
writeFileSync(out, JSON.stringify({ version: 1, params_hash: hash, heads }));
console.log(`baked in ${Date.now() - t0} ms -> ${out}`);
