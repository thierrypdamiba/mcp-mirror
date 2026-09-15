import {readFile} from "node:fs/promises";

const news = JSON.parse(
  await readFile("site/src/data/news.json", "utf8"),
);
const categories = new Set(["Protocol", "Frameworks", "Ecosystem", "Security", "MCP Mirror"]);
const urls = new Set();
let previousDate = "9999-12-31";
const now = new Date();
const maxVerificationAgeDays = Number(
  process.env.NEWS_MAX_VERIFICATION_AGE_DAYS ?? 30,
);

if (!Number.isFinite(maxVerificationAgeDays) || maxVerificationAgeDays < 1) {
  throw new Error("NEWS_MAX_VERIFICATION_AGE_DAYS must be a positive number");
}

for (const [index, item] of news.entries()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(item.date) || Number.isNaN(Date.parse(item.date))) {
    throw new Error(`news item ${index + 1} has an invalid date`);
  }
  if (item.date > previousDate) {
    throw new Error("news items must be newest first");
  }
  previousDate = item.date;
  const url = new URL(item.url);
  if (url.protocol !== "https:") throw new Error(`${item.id} URL must use HTTPS`);
  const canonical = `${url.origin}${url.pathname}`.replace(/\/$/, "");
  if (urls.has(canonical)) throw new Error(`${item.id} duplicates canonical URL ${canonical}`);
  urls.add(canonical);
  if (!categories.has(item.category)) throw new Error(`${item.id} has invalid category`);
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(item.verified_at) ||
    Number.isNaN(Date.parse(item.verified_at))
  ) {
    throw new Error(`${item.id} has invalid verification metadata`);
  }
  const verifiedAt = new Date(`${item.verified_at}T23:59:59Z`);
  const verificationAgeDays = (now - verifiedAt) / 86_400_000;
  if (verificationAgeDays < -1) {
    throw new Error(`${item.id} was verified in the future`);
  }
  if (verificationAgeDays > maxVerificationAgeDays) {
    throw new Error(
      `${item.id} was last verified ${Math.floor(verificationAgeDays)} days ago; ` +
        `maximum is ${maxVerificationAgeDays}`,
    );
  }
  if (item.date > item.verified_at) {
    throw new Error(`${item.id} was verified before its publication date`);
  }
  for (const field of ["id", "title", "summary", "source"]) {
    if (!String(item[field] ?? "").trim()) throw new Error(`${item.id} is missing ${field}`);
  }
}

const newestAgeDays =
  (Date.now() - Date.parse(`${news[0].date}T00:00:00Z`)) / 86_400_000;
if (newestAgeDays > 45) {
  console.warn(`warning: newest checked-in news item is ${Math.floor(newestAgeDays)} days old`);
}
console.log(`validated ${news.length} verified news items, newest first`);
