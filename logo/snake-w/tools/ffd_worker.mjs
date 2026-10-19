// A persistent renderer for the displacement-field fit: one Chromium, one request per stdin line,
// one reply per stdout line. A request is { id, spec, disp, out, clip, box } -
//   spec  the base spec file (in snakes/); disp = { yellow: [...handles], blue: [...] } replaces
//         the strands' disp lists (omit a strand to keep the base spec's);
//   out   PNG path; clip = [x0, y0, x1, y1] in reference px (default the whole frame);
//   box   [x0, y0, x1, y1]: the window for fold_box; shade: a PNG path for a grey Lambert render of the same clip.
// The render is snakes/ffd-flat.html: the real geometry (strandsFromSpec, press, strandSurface,
// the hero camera) in flat colours with no heads, occlusion or shadow: tens of ms a build.
// real: true renders the real scene instead (still-spline.html: about 25 s, at ss 1).
// spec_obj: an inline spec object instead of the file; ids: a path for the raw surface-point
// buffer of the clip (ffd-flat.html __ids; reply { w, h }).
// Reply: { id, ms, fold_area, fold_box } (flat only). Usage (from snakes/): node ../tools/ffd_worker.mjs
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import readline from "node:readline";
const require = createRequire(import.meta.url);
const { chromium } = (() => { try { return require("playwright"); } catch { return require("/opt/node22/lib/node_modules/playwright"); } })();
const CHROME = process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const ROOT = fileURLToPath(new URL("..", import.meta.url));
const DIR = join(ROOT, "snakes");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json" };
const look = readFileSync(join(DIR, "w-final.look.json"), "utf8");
const overrides = new Map();
const browser = await chromium.launch({ executablePath: CHROME, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const ctx = await browser.newContext({ viewport: { width: 1448, height: 1086 }, deviceScaleFactor: 1 });
await ctx.route("**/*", (r) => {
  const url = new URL(r.request().url());
  if (url.href === "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js")
    return existsSync(join(ROOT, "vendor/three.module.js")) ? r.fulfill({ body: readFileSync(join(ROOT, "vendor/three.module.js")), contentType: "text/javascript" }) : r.continue();
  if (url.host === "wend.local") {
    const p = decodeURIComponent(url.pathname);
    if (overrides.has(p)) return r.fulfill({ body: overrides.get(p), contentType: "application/json" });
    const file = join(DIR, p);
    if (!existsSync(file)) return r.fulfill({ status: 404, body: "" });
    return r.fulfill({ body: readFileSync(file), contentType: TYPES[extname(file)] || "application/octet-stream" });
  }
  return r.abort();
});
const page = await ctx.newPage();
page.on("pageerror", (e) => console.error("pageerror", e.message));
// FFD_PARAMS / FFD_HEADS (env): the params file and head bake (in snakes/) of a neck variant
const PARAMS = process.env.FFD_PARAMS || "w-final.params.json", HEADS = process.env.FFD_HEADS || "heads-final.json";
await page.goto(`http://wend.local/ffd-flat.html?${new URLSearchParams({ params: PARAMS, heads: HEADS })}`);
await page.waitForFunction(() => window.__ready === true, null, { timeout: 60000 });
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  const req = JSON.parse(line), t0 = Date.now();
  try {
    const spec = req.spec_obj || JSON.parse(readFileSync(join(DIR, req.spec), "utf8"));
    for (const n of ["yellow", "blue"]) if (req.disp && req.disp[n]) spec[n].disp = req.disp[n];
    const c = req.clip || [0, 0, 1448, 1086];
    let reply = { id: req.id };
    if (req.real) {
      const key = `/ffd-override-${req.id}.json`;
      overrides.set(key, JSON.stringify(spec));
      const p2 = await ctx.newPage();
      const qs = new URLSearchParams({ params: PARAMS, look, ss: "1", heads: HEADS, spec: key.slice(1) });
      await p2.goto(`http://wend.local/still-spline.html?${qs}`);
      await p2.waitForFunction(() => window.__ready === true, null, { timeout: 180000 });
      await p2.screenshot({ path: req.out, clip: { x: c[0], y: c[1], width: c[2] - c[0], height: c[3] - c[1] } });
      await p2.close(); overrides.delete(key);
    } else if (req.ids) {
      // the surface-point buffer (ffd-flat.html __ids): raw RGBA bytes of the clip, rows from the top
      const r = await page.evaluate(([s, cl]) => window.__ids(s, cl), [spec, c]);
      writeFileSync(req.ids, Buffer.from(r.data, "base64"));
      Object.assign(reply, { w: r.w, h: r.h });
    } else {
      Object.assign(reply, await page.evaluate(([s, b]) => window.__run(s, b), [spec, req.box || null]));
      await page.screenshot({ path: req.out, clip: { x: c[0], y: c[1], width: c[2] - c[0], height: c[3] - c[1] } });
      if (req.shade) { await page.evaluate(() => window.__shade()); await page.screenshot({ path: req.shade, clip: { x: c[0], y: c[1], width: c[2] - c[0], height: c[3] - c[1] } }); }
      if (req.normals) { await page.evaluate(() => window.__normals()); await page.screenshot({ path: req.normals, clip: { x: c[0], y: c[1], width: c[2] - c[0], height: c[3] - c[1] } }); }
    }
    reply.total_ms = Date.now() - t0;
    console.log(JSON.stringify(reply));
  } catch (e) {
    console.log(JSON.stringify({ id: req.id, error: String(e.message || e).slice(0, 300) }));
  }
}
await browser.close();
