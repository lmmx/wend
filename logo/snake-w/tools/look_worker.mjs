// A persistent look renderer: snakes/look-lab.html in one Chromium (the final geometry built once),
// one request per stdin line { id, look (a patch on the base look), out (PNG path) }, one reply per
// stdout line { id, ms }. LOOK_BASE / LOOK_SS (env): the base look file and the pixel ratio.
// Usage (from snakes/): node ../tools/look_worker.mjs
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
const browser = await chromium.launch({ executablePath: CHROME, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const ctx = await browser.newContext({ viewport: { width: 1448, height: 1086 }, deviceScaleFactor: 1 });
await ctx.route("**/*", (r) => {
  const url = new URL(r.request().url());
  if (url.href === "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js")
    return existsSync(join(ROOT, "vendor/three.module.js")) ? r.fulfill({ body: readFileSync(join(ROOT, "vendor/three.module.js")), contentType: "text/javascript" }) : r.continue();
  if (url.host === "wend.local") {
    const file = join(DIR, decodeURIComponent(url.pathname));
    if (!existsSync(file)) return r.fulfill({ status: 404, body: "" });
    return r.fulfill({ body: readFileSync(file), contentType: TYPES[extname(file)] || "application/octet-stream" });
  }
  return r.abort();
});
const page = await ctx.newPage();
page.on("pageerror", (e) => console.error("pageerror", e.message));
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") console.error("console", m.text()); });
const qs = new URLSearchParams({ look: process.env.LOOK_BASE || "w-final.look.json", ss: process.env.LOOK_SS || "1" });
await page.goto(`http://wend.local/look-lab.html?${qs}`);
await page.waitForFunction(() => window.__ready === true, null, { timeout: 120000 });
console.log(JSON.stringify({ ready: true }));
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  const req = JSON.parse(line), t0 = Date.now();
  try {
    const url = await page.evaluate((p) => window.__look(p), req.look || {});
    writeFileSync(req.out, Buffer.from(url.split(",")[1], "base64"));
    const t = await page.evaluate(() => window.__t);
    console.log(JSON.stringify({ id: req.id, ms: Date.now() - t0, t }));
  } catch (e) {
    console.log(JSON.stringify({ id: req.id, error: String(e) }));
  }
}
await browser.close();
