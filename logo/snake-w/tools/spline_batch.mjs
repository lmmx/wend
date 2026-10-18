// Render several stills of snakes/still-spline.html (or job.page) in one browser. Usage: node spline_batch.mjs jobs.json
// jobs: [{ "out": "...png", "params": "...json", "query": { "look": "...", "yaw": "35", ... } }, ...]
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
// playwright from the project, else this machine's global install; Chromium from $CHROME, else
// the pre-installed one
const { chromium } = (() => { try { return require("playwright"); } catch { return require("/opt/node22/lib/node_modules/playwright"); } })();
const CHROME = process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const ROOT = fileURLToPath(new URL("..", import.meta.url));
const DIR = join(ROOT, "snakes");
const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json" };
const browser = await chromium.launch({ executablePath: CHROME, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const ctx = await browser.newContext({ viewport: { width: 1448, height: 1086 }, deviceScaleFactor: 1 });
await ctx.route("**/*", (r) => {
  const url = new URL(r.request().url());
  // three r170 from vendor/three.module.js if it is there (offline), else from the CDN
  if (url.href === "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js")
    return existsSync(join(ROOT, "vendor/three.module.js"))
      ? r.fulfill({ body: readFileSync(join(ROOT, "vendor/three.module.js")), contentType: "text/javascript" })
      : r.continue();
  if (url.host === "wend.local") {
    const file = join(DIR, decodeURIComponent(url.pathname));
    if (!existsSync(file)) return r.fulfill({ status: 404, body: "" });
    return r.fulfill({ body: readFileSync(file), contentType: TYPES[extname(file)] || "application/octet-stream" });
  }
  return r.abort();
});
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("pageerror", e.message));
page.on("console", (m) => { if (m.type() !== "log" || /built/.test(m.text())) console.log("console", m.type(), m.text().slice(0, 200)); });
for (const job of jobs) {
  const qs = new URLSearchParams({ params: job.params, ...job.query });
  await page.goto(`http://wend.local/${job.page || "still-spline.html"}?${qs}`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 180000 });
  await page.locator("#c").screenshot({ path: job.out });
  console.log("done", job.out);
}
await browser.close();
console.log("rendered", jobs.length);
