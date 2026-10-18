// Render snakes/still.html to PNG. Usage: node snake_still.mjs out.png [params.json] [query...]
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
const [out, params = "params.json", ...rest] = process.argv.slice(2);
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png" };
const browser = await chromium.launch({
  executablePath: CHROME,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
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
page.on("console", (m) => console.log("console", m.type(), m.text().slice(0, 300)));
const qs = new URLSearchParams({ params, ...Object.fromEntries(rest.map((kv) => kv.split(/=(.*)/s).slice(0, 2))) });
await page.goto(`http://wend.local/still.html?${qs}`);
await page.waitForFunction(() => window.__ready === true, null, { timeout: 120000 });
await page.locator("#c").screenshot({ path: out });
await browser.close();
