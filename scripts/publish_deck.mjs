import {mkdir, readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const deckPath = path.join(root, "talk", "deck.html");
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

// Only the deck travels. `present.html` reads the verbatim speaking script over fetch,
// so publishing the presenter console would publish the script along with it.
await mkdir(targetDir, {recursive: true});
await writeFile(path.join(targetDir, "index.html"), deck);
console.log(
  `wrote docs/talk/index.html (${Buffer.byteLength(deck).toLocaleString()} bytes)`,
);
