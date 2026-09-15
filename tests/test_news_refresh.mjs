import assert from "node:assert/strict";
import test from "node:test";

import {parseFeed} from "../scripts/refresh_news.mjs";

test("parseFeed reads Atom metadata without rewriting source text", () => {
  const items = parseFeed(`
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>SDK v2.0 &amp; tools</title>
        <link rel="alternate" href="https://example.com/releases/v2" />
        <published>2026-09-14T08:30:00Z</published>
        <content type="html"><![CDATA[<p>Typed <strong>release notes</strong>.</p>]]></content>
      </entry>
    </feed>
  `);

  assert.deepEqual(items, [
    {
      title: "SDK v2.0 & tools",
      url: "https://example.com/releases/v2",
      date: "2026-09-14",
      summary: "Typed release notes.",
    },
  ]);
});

test("parseFeed reads RSS items", () => {
  const items = parseFeed(`
    <rss><channel><item>
      <title>Protocol update</title>
      <link>https://example.com/protocol</link>
      <pubDate>Mon, 14 Sep 2026 09:00:00 GMT</pubDate>
      <description>Source-provided summary.</description>
    </item></channel></rss>
  `);

  assert.equal(items[0].title, "Protocol update");
  assert.equal(items[0].url, "https://example.com/protocol");
  assert.equal(items[0].date, "2026-09-14");
  assert.equal(items[0].summary, "Source-provided summary.");
});
