// Bake the head-and-neck meshes (the slow part of the build) for a params file, so pages
// load them instead of meshing the head field. Usage: node bake_heads.mjs params.json out.json
// The output holds, per head, its positions, normals, indices (base64) and AO balls; scene.js
// uses it when given `bakedHeads`, and checks a hash of what the heads depend on (headKey) so a
// stale bake is not used.
import { readFileSync, writeFileSync } from "node:fs";
const G = await import(new URL("../snakes/geometry.js", import.meta.url));
const [paramsPath, out] = process.argv.slice(2);
const text = readFileSync(paramsPath, "utf8"), params = JSON.parse(text);
const elev = (params.cam.elev * Math.PI) / 180;
const lines = G.centrelines(params);
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
