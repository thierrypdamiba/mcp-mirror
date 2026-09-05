import {readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const docsDir = path.join(root, "docs");
const indexPath = path.join(docsDir, "index.html");
const dataPath = path.join(docsDir, "data", "data-1.0.json");

const index = await readFile(indexPath, "utf8");
const scriptMatch = index.match(
  /<script type="module"[^>]*src="([^"]+)"[^>]*><\/script>/,
);
const styleMatch = index.match(
  /<link rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/,
);

if (!scriptMatch || !styleMatch) {
  throw new Error("Could not locate Vite JavaScript and CSS assets in docs/index.html");
}

function assetPath(reference) {
  return path.join(docsDir, reference.replace(/^\.\//, ""));
}

const [javascript, stylesheet, rawData] = await Promise.all([
  readFile(assetPath(scriptMatch[1]), "utf8"),
  readFile(assetPath(styleMatch[1]), "utf8"),
  readFile(dataPath, "utf8"),
]);

const database = JSON.parse(rawData);
const inlineData = JSON.stringify(database)
  .replaceAll("<", "\\u003c")
  .replaceAll("\u2028", "\\u2028")
  .replaceAll("\u2029", "\\u2029");
const safeJavaScript = javascript.replaceAll("</script", "<\\/script");
const safeStylesheet = stylesheet
  .replaceAll("url(./", "url(./assets/")
  .replaceAll('url("/img/', 'url("./img/')
  .replaceAll("url('/img/", "url('./img/")
  .replaceAll("url(/img/", "url(./img/")
  .replaceAll("</style", "<\\/style");

const standalone = index
  .replace(styleMatch[0], () => `<style>${safeStylesheet}</style>`)
  .replace(
    scriptMatch[0],
    () =>
      `<script>window.__MCP_MIRROR_DATA__=${inlineData};</script>\n    <script type="module">${safeJavaScript}</script>`,
  );

const target = path.join(docsDir, "standalone.html");
await writeFile(target, standalone);
console.log(
  `wrote docs/standalone.html (${Buffer.byteLength(standalone).toLocaleString()} bytes)`,
);
