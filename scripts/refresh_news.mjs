import {readFile, writeFile} from "node:fs/promises";

const NEWS_PATH = "site/src/data/news.json";
const SOURCES_PATH = "site/src/data/news-sources.json";
const MAX_ITEMS = 20;
const MAX_STORY_AGE_DAYS = 120;

function decodeXml(value) {
  return value
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'");
}

function textContent(value) {
  return decodeXml(
    value
      .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .replace(/\s+([.,!?;:])/g, "$1")
      .trim(),
  );
}

function tag(block, name) {
  return block.match(new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)</${name}>`, "i"))?.[1];
}

function entryLink(block) {
  const alternate = block.match(
    /<link\b(?=[^>]*\brel=["']alternate["'])(?=[^>]*\bhref=["']([^"']+)["'])[^>]*\/?>/i,
  );
  if (alternate) return decodeXml(alternate[1]);
  const href = block.match(/<link\b[^>]*\bhref=["']([^"']+)["'][^>]*\/?>/i);
  if (href) return decodeXml(href[1]);
  return textContent(tag(block, "link") ?? "");
}

export function parseFeed(xml) {
  const atomEntries = [...xml.matchAll(/<entry\b[^>]*>([\s\S]*?)<\/entry>/gi)].map(
    (match) => match[1],
  );
  const rssEntries = [...xml.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)].map(
    (match) => match[1],
  );
  return [...atomEntries, ...rssEntries]
    .map((block) => {
      const title = textContent(tag(block, "title") ?? "");
      const url = entryLink(block) || textContent(tag(block, "guid") ?? "");
      const published =
        textContent(tag(block, "published") ?? "") ||
        textContent(tag(block, "updated") ?? "") ||
        textContent(tag(block, "pubDate") ?? "");
      const summary = textContent(
        tag(block, "summary") ?? tag(block, "content") ?? tag(block, "description") ?? "",
      );
      const parsedDate = new Date(published);
      return {
        title,
        url,
        date: Number.isNaN(parsedDate.valueOf())
          ? ""
          : parsedDate.toISOString().slice(0, 10),
        summary,
      };
    })
    .filter((item) => item.title && item.url && item.date);
}

function canonicalUrl(raw) {
  const url = new URL(raw);
  url.hash = "";
  for (const key of [...url.searchParams.keys()]) {
    if (key.startsWith("utm_") || key === "ref") url.searchParams.delete(key);
  }
  return `${url.origin}${url.pathname}${url.search}`.replace(/\/$/, "");
}

function slug(value) {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .slice(0, 72);
}

function sourceSummary(value) {
  const text = value.trim();
  if (text.length <= 280) return text;
  return `${text.slice(0, 277).trimEnd()}...`;
}

async function fetchSource(source) {
  const response = await fetch(source.url, {
    headers: {"user-agent": "mcp-mirror-news-refresh/1"},
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    throw new Error(`${source.name} returned HTTP ${response.status}`);
  }
  return parseFeed(await response.text())
    .slice(0, source.limit)
    .map((item) => ({
      id: `${slug(source.source)}-${slug(item.title)}`,
      date: item.date,
      title: item.title,
      summary: sourceSummary(item.summary || item.title),
      source: source.source,
      url: canonicalUrl(item.url),
      category: source.category,
    }));
}

async function linkIsAccessible(url) {
  try {
    const response = await fetch(url, {
      headers: {"user-agent": "mcp-mirror-news-refresh/1"},
      redirect: "follow",
      signal: AbortSignal.timeout(20_000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function refreshNews({
  now = new Date(),
  fetcher = fetchSource,
  linkChecker = linkIsAccessible,
} = {}) {
  const [existing, sources] = await Promise.all([
    readFile(NEWS_PATH, "utf8").then(JSON.parse),
    readFile(SOURCES_PATH, "utf8").then(JSON.parse),
  ]);
  const verifiedAt = now.toISOString().slice(0, 10);
  const fetched = (await Promise.all(sources.map(fetcher))).flat();
  const candidates = [...fetched, ...existing];
  const accessible = await Promise.all(
    candidates.map(async (item) => [canonicalUrl(item.url), await linkChecker(item.url)]),
  );
  const accessibleUrls = new Set(
    accessible.filter(([, ok]) => ok).map(([url]) => url),
  );
  const oldestAcceptedDate = new Date(now);
  oldestAcceptedDate.setUTCDate(oldestAcceptedDate.getUTCDate() - MAX_STORY_AGE_DAYS);
  const oldestAccepted = oldestAcceptedDate.toISOString().slice(0, 10);

  const merged = [
    ...fetched.map((item) => ({...item, verified_at: verifiedAt})),
    ...existing.map((item) => ({...item, verified_at: verifiedAt})),
  ].filter(
    (item) =>
      item.date >= oldestAccepted && accessibleUrls.has(canonicalUrl(item.url)),
  );
  const seen = new Set();
  const accepted = merged
    .sort(
      (left, right) =>
        right.date.localeCompare(left.date) ||
        left.title.localeCompare(right.title),
    )
    .filter((item) => {
      const canonical = canonicalUrl(item.url);
      if (seen.has(canonical)) return false;
      seen.add(canonical);
      return true;
    })
    .slice(0, MAX_ITEMS);

  await writeFile(NEWS_PATH, `${JSON.stringify(accepted, null, 2)}\n`);
  return {sources: sources.length, fetched: fetched.length, accepted: accepted.length};
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const result = await refreshNews();
  console.log(
    `refreshed ${result.accepted} news items from ${result.sources} approved sources ` +
      `(${result.fetched} fetched)`,
  );
}
