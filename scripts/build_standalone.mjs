import {readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const docsDir = path.join(root, "docs");
const indexPath = path.join(docsDir, "index.html");
const specIndexPath = path.join(docsDir, "data", "specs.json");

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

const MIME_TYPES = {
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};

/** Inline every file the stylesheet points at, as a data URI.
 *
 * The point of this build is a single file someone can email. A relative `url()`
 * resolves against wherever the HTML happens to sit, so leaving one in produces a
 * file that looks self-contained, works in `docs/` next to its assets, and quietly
 * loses its fonts the moment anyone moves it.
 */
async function inlineStylesheetAssets(css, cssDir) {
  const pattern = /url\((['"]?)([^'")]+)\1\)/g;
  const inlined = new Map();

  for (const [, , reference] of css.matchAll(pattern)) {
    if (inlined.has(reference) || /^(?:data:|https?:|\/\/)/.test(reference)) {
      continue;
    }
    const file = reference.startsWith("/")
      ? path.join(docsDir, reference.slice(1))
      : path.resolve(cssDir, reference);
    const mime = MIME_TYPES[path.extname(file).toLowerCase()];
    if (!mime) {
      throw new Error(`No MIME type known for the stylesheet asset ${reference}`);
    }
    const contents = await readFile(file);
    inlined.set(reference, `data:${mime};base64,${contents.toString("base64")}`);
  }

  return css.replace(pattern, (match, _quote, reference) =>
    inlined.has(reference) ? `url(${inlined.get(reference)})` : match,
  );
}

const [javascript, stylesheet, rawSpecIndex] = await Promise.all([
  readFile(assetPath(scriptMatch[1]), "utf8"),
  readFile(assetPath(styleMatch[1]), "utf8"),
  readFile(specIndexPath, "utf8"),
]);

const specIndex = JSON.parse(rawSpecIndex);
const datasets = Object.fromEntries(
  await Promise.all(
    specIndex.specs.map(async (entry) => [
      entry.id,
      JSON.parse(await readFile(path.join(docsDir, "data", entry.file), "utf8")),
    ]),
  ),
);
const database = datasets[specIndex.default_spec];
const inlineData = JSON.stringify({database, datasets, specIndex})
  .replaceAll("<", "\\u003c")
  .replaceAll("\u2028", "\\u2028")
  .replaceAll("\u2029", "\\u2029");
const safeJavaScript = javascript.replaceAll("</script", "<\\/script");
const safeStylesheet = (
  await inlineStylesheetAssets(
    stylesheet,
    path.dirname(assetPath(styleMatch[1])),
  )
).replaceAll("</style", "<\\/style");

const standalone = index
  .replace(styleMatch[0], () => `<style>${safeStylesheet}</style>`)
  .replace(
    scriptMatch[0],
    () =>
      `<script>{const d=${inlineData};window.__MCP_MIRROR_DATA__=d.database;window.__MCP_MIRROR_DATASETS__=d.datasets;window.__MCP_MIRROR_SPEC_INDEX__=d.specIndex;}</script>\n    <script type="module">${safeJavaScript}</script>`,
  );

// The whole promise of this artifact is that it travels alone, and a reference to a
// neighbouring file breaks that silently rather than loudly. Fail the build instead.
const dangling = standalone.match(/(?:url\(|(?:src|href)=")\.{0,2}\/(?!\/)[^)"']+/);
if (dangling) {
  throw new Error(
    `standalone.html still points at a neighbouring file (${dangling[0].slice(0, 80)}), ` +
      "so it would lose that asset as soon as anyone moved it",
  );
}

const target = path.join(docsDir, "standalone.html");
await writeFile(target, standalone);
console.log(
  `wrote docs/standalone.html (${Buffer.byteLength(standalone).toLocaleString()} bytes)`,
);
