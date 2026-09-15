import {mkdir, readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const deckPath = path.join(root, "talk", "deck.html");
const pdfName = "mcp-mirror-talk.pdf";
const pdfPath = path.join(root, "talk", pdfName);
const targetDir = path.join(root, "docs", "talk");

const deck = await readFile(deckPath, "utf8");

/** Refuse to publish a deck that has to fetch anything off the machine rendering it.
 *
 * The point of publishing is that an audience reopens exactly what ran on stage, and a
 * CDN font or a remote script quietly makes that a promise the network has to keep.
 * The patterns match fetched references only, so the inline QR code's `xmlns`, which
 * names an XML vocabulary rather than requesting one, does not read as a dependency.
 */
const REMOTE_REFERENCES = [
  [/(?:src|href)\s*=\s*["']\s*(?:https?:)?\/\//i, "a remote src or href"],
  [/url\(\s*["']?\s*(?:https?:)?\/\//i, "a remote stylesheet url()"],
  [/@import/i, "an @import"],
];

for (const [pattern, description] of REMOTE_REFERENCES) {
  const offender = deck.match(pattern);
  if (offender) {
    throw new Error(
      `talk/deck.html carries ${description} (${offender[0]}), so the published deck ` +
        "would depend on a network the audience may not have",
    );
  }
}

/** The PDF ships as a committed export rather than a build product.
 *
 * Rendering it here would put a browser and a PDF library in the build path for a file
 * that only changes when the slides do. That makes a missing one a deletion rather than
 * a first-run gap, and the README offers it as a download, so stopping the build beats
 * publishing a link that 404s for everyone who trusts it.
 */
const pdf = await readFile(pdfPath).catch((cause) => {
  throw new Error(
    `talk/${pdfName} is missing, so the download the README offers would 404. ` +
      "Restore the committed export, or drop the link if the deck now travels alone.",
    {cause},
  );
});

// Only the deck and its PDF travel. `present.html` reads the verbatim speaking script
// over fetch, so publishing the presenter console would publish the script with it.
await mkdir(targetDir, {recursive: true});
await writeFile(path.join(targetDir, "index.html"), deck);
await writeFile(path.join(targetDir, pdfName), pdf);
console.log(
  `wrote docs/talk/index.html (${Buffer.byteLength(deck).toLocaleString()} bytes) ` +
    `and docs/talk/${pdfName} (${pdf.byteLength.toLocaleString()} bytes)`,
);
