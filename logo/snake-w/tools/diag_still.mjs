// Neutral diagnostic renders (clay / zebra / curvature) of snakes/diag-clay.html.
// Usage (run from snakes/):
//   node ../tools/diag_still.mjs OUTPREFIX params.json [key=value ...]
//   node ../tools/diag_still.mjs --jobs jobs.json      jobs: [{ "prefix", "params", "query": {...} }]
// Query keys (see diag-clay.html): look, heads, modes=clay,zebra,zebrav,curv, views=preset|JSON,
// ss, cs, geo, bars. views presets: "full", "crops" (the five crops), "all" (full + crops).
// Writes OUTPREFIX<mode>-<view>.png for every mode x view. Paths that are not in snakes/ are
// looked up relative to the logo root, so params under ../diag/ work.
import { readFileSync, existsSync, writeFileSync, mkdirSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const { chromium } = (() => { try { return require("playwright"); } catch { return require("/opt/node22/lib/node_modules/playwright"); } })();
const CHROME = process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const ROOT = fileURLToPath(new URL("..", import.meta.url));
const DIR = join(ROOT, "snakes");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".png": "image/png" };
export const CROPS = {
  arch: [600, 380, 880, 620], lvalley: [420, 560, 700, 800], rvalley: [800, 540, 1080, 800],
  larm: [380, 380, 520, 660], rarm: [940, 420, 1080, 700],
};
const PRESETS = { full: { full: [0, 0, 1448, 1086] }, crops: CROPS, all: { full: [0, 0, 1448, 1086], ...CROPS } };

const args = process.argv.slice(2);
let jobs;
if (args[0] === "--jobs") jobs = JSON.parse(readFileSync(args[1], "utf8"));
else {
  const [prefix, params = "params.json", ...rest] = args;
  jobs = [{ prefix, params, query: Object.fromEntries(rest.map((kv) => kv.split(/=(.*)/s).slice(0, 2))) }];
}
const browser = await chromium.launch({ executablePath: CHROME, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const ctx = await browser.newContext({ viewport: { width: 1448, height: 1086 }, deviceScaleFactor: 1 });
await ctx.route("**/*", (r) => {
  const url = new URL(r.request().url());
  if (url.href === "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js")
    return existsSync(join(ROOT, "vendor/three.module.js"))
      ? r.fulfill({ body: readFileSync(join(ROOT, "vendor/three.module.js")), contentType: "text/javascript" })
      : r.continue();
  if (url.host === "wend.local") {
    const p = decodeURIComponent(url.pathname);
    let file = join(DIR, p);
    if (!existsSync(file)) file = join(ROOT, p);
    if (!existsSync(file)) return r.fulfill({ status: 404, body: "" });
    return r.fulfill({ body: readFileSync(file), contentType: TYPES[extname(file)] || "application/octet-stream" });
  }
  return r.abort();
});
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("pageerror", e.message));
page.on("console", (m) => { const t = m.text(); if (!/GPU stall|WebGL/.test(t)) console.log("console", m.type(), t.slice(0, 400)); });
for (const job of jobs) {
  const t0 = Date.now();
  const query = { ...job.query };
  if (query.views && PRESETS[query.views]) query.views = JSON.stringify(PRESETS[query.views]);
  // params paths under ../diag etc: served from the root
  const toUrl = (p) => (p && p.startsWith("../") ? "/" + p.slice(3) : p);
  const qs = new URLSearchParams({ params: toUrl(job.params), ...query, ...(query.heads ? { heads: toUrl(query.heads) } : {}) });
  await page.goto(`http://wend.local/diag-clay.html?${qs}`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 600000 });
  const err = await page.evaluate(() => window.__error);
  if (err) { console.log("job failed", job.prefix, err); continue; }
  const shots = await page.evaluate(() => window.__shots);
  const info = await page.evaluate(() => window.__info);
  mkdirSync(dirname(job.prefix + "x"), { recursive: true });
  for (const s of shots) {
    const f = `${job.prefix}${s.mode}-${s.view}.png`;
    writeFileSync(f, Buffer.from(s.data.split(",")[1], "base64"));
  }
  console.log(`${job.prefix}: ${shots.length} shots, build ${info.build_ms} ms, total ${Date.now() - t0} ms`);
}
await browser.close();
