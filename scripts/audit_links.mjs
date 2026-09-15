import {access, readFile} from "node:fs/promises";
import path from "node:path";

import {chromium} from "playwright-core";
import {preview} from "vite";

const chromePath =
  process.env.CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const database = JSON.parse(
  await readFile("site/public/data/data-1.0.json", "utf8"),
);
const capabilityIds = new Set(Object.keys(database.data));
const routes = [
  "#/",
  "#/stats",
  "#/changes",
  "#/method",
  ...[...capabilityIds].map((id) => `#/cap/${encodeURIComponent(id)}`),
];
const checkExternal = process.argv.includes("--external");

function validateHash(hash) {
  const path = hash.split("?")[0];
  if (["#/", "#/stats", "#/changes", "#/method"].includes(path)) return;
  if (path.startsWith("#/cap/")) {
    const capabilityId = decodeURIComponent(path.slice("#/cap/".length));
    if (capabilityIds.has(capabilityId)) return;
  }
  throw new Error(`unknown internal destination ${hash}`);
}

async function externalStatus(url) {
  const response = await fetch(url, {
    headers: {"user-agent": "mcp-mirror-link-audit/1"},
    redirect: "follow",
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
}

const server = await preview({
  configFile: "vite.config.ts",
  preview: {host: "127.0.0.1", port: 0, strictPort: false},
});
const port = server.httpServer.address().port;
const baseUrl = `http://127.0.0.1:${port}/`;
const browser = await chromium.launch({executablePath: chromePath});
const page = await browser.newPage({viewport: {width: 1280, height: 900}});
const externalUrls = new Set();
let linkCount = 0;

try {
  for (const route of routes) {
    await page.goto(`${baseUrl}${route}`, {waitUntil: "networkidle"});
    const links = await page.locator("a[href]").evaluateAll((anchors) =>
      anchors.map((anchor) => ({
        href: anchor.getAttribute("href") ?? "",
        label:
          anchor.getAttribute("aria-label")?.trim() ||
          anchor.textContent?.trim() ||
          anchor.querySelector("img")?.getAttribute("alt")?.trim() ||
          "",
        target: anchor.getAttribute("target"),
        rel: anchor.getAttribute("rel") ?? "",
      })),
    );
    for (const link of links) {
      linkCount += 1;
      if (!link.label) throw new Error(`${route}: link ${link.href} has no accessible name`);
      if (link.href.startsWith("#")) {
        if (link.href.startsWith("#/")) {
          validateHash(link.href);
        } else if ((await page.locator(link.href).count()) !== 1) {
          throw new Error(`${route}: page anchor ${link.href} has no unique target`);
        }
      } else if (/^https?:\/\//.test(link.href)) {
        externalUrls.add(link.href);
        if (link.target === "_blank") {
          const rel = new Set(link.rel.split(/\s+/));
          if (!rel.has("noopener") || !rel.has("noreferrer")) {
            throw new Error(`${route}: external link ${link.href} has unsafe rel`);
          }
        }
      } else if (link.href.startsWith("./")) {
        const localPath = path.join("site/public", link.href.slice(2));
        await access(localPath);
      } else {
        throw new Error(`${route}: unsupported link destination ${link.href}`);
      }
    }
  }

  if (checkExternal) {
    for (const url of externalUrls) await externalStatus(url);
  }
} finally {
  await browser.close();
  await server.httpServer.close();
}

console.log(
  `audited ${linkCount} rendered links across ${routes.length} routes; ` +
    `${externalUrls.size} external destinations${checkExternal ? " responded successfully" : " collected"}`,
);
