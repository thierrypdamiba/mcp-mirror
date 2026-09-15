import {chromium} from "playwright-core";
import {preview} from "vite";
import {readFileSync} from "node:fs";
import path from "node:path";
import {pathToFileURL} from "node:url";

// Derived from the built dataset rather than hardcoded, so adding a protocol feature to
// the surface does not require editing an expected count here.
const database = JSON.parse(
  readFileSync("site/public/data/data-1.0.json", "utf8"),
);
const capabilityCount = Object.values(database.data).filter(
  (capability) => capability.shown !== false,
).length;
const coverage = database.coverage;
const news = JSON.parse(
  readFileSync("site/src/data/news.json", "utf8"),
);

// The version each snapshot measures at moves whenever the runner manifests are
// repinned, so read it rather than restate it.
const legacyCrewaiVersion = JSON.parse(
  readFileSync("site/public/data/data-2025-11-25.json", "utf8"),
).agents.crewai.current_version;

const chromePath =
  process.env.CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const server = await preview({
  configFile: "vite.config.ts",
  preview: {
    host: "127.0.0.1",
    port: 0,
    strictPort: false,
  },
});

const address = server.httpServer.address();
assert(address && typeof address !== "string", "Preview server did not bind a TCP port");
const baseUrl = `http://127.0.0.1:${address.port}/`;
const browser = await chromium.launch({executablePath: chromePath, headless: true});
const consoleErrors = [];

try {
  const mobile = await browser.newPage({viewport: {width: 390, height: 844}});
  mobile.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  await mobile.goto(baseUrl, {waitUntil: "networkidle"});
  const widths = await mobile.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  assert(
    widths.document <= widths.viewport,
    `Mobile layout overflows: ${widths.document}px document in ${widths.viewport}px viewport`,
  );

  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  await page.goto(baseUrl, {waitUntil: "networkidle"});

  const specSelector = page.getByLabel("MCP specification revision");
  assert(
    (await specSelector.inputValue()) === "2026-07-28" &&
      (await page.getByText("2 of 5 frameworks reach this revision").count()) ===
        1,
    "The current MCP snapshot is not explicit",
  );
  await page
    .getByRole("navigation", {name: "Primary navigation"})
    .getByRole("link", {name: "Stats", exact: true})
    .waitFor();
  const firstHeadline = page
    .locator('.news-crawl-group:not([data-clone="true"]) .news-ticker-link')
    .first();
  const featureHref = await firstHeadline.getAttribute("href");
  assert(
    featureHref === news[0].url,
    `News crawl has an invalid newest destination: ${featureHref}`,
  );
  await page.goto(`${baseUrl}#/cap/destructive-hint`, {waitUntil: "networkidle"});
  await page.locator(".feature-module.is-detail").waitFor();
  await page.goto(baseUrl, {waitUntil: "networkidle"});

  const homeSearch = page.getByRole("searchbox", {name: "Search MCP capabilities"});
  await homeSearch.fill("hint");
  await page
    .getByRole("navigation", {name: "Primary navigation"})
    .getByRole("link", {name: "Home"})
    .click();
  assert(
    page.url().endsWith("#/") &&
      (await homeSearch.inputValue()) === "" &&
      (await page.getByRole("heading", {name: "New"}).count()) === 1 &&
      (await page.getByRole("heading", {name: "Popular"}).count()) === 1 &&
      (await page.locator(".home-section-new li").count()) === 5 &&
      (await page.locator(".home-section-popular li").count()) === 5,
    "Home navigation did not restore the curated homepage",
  );

  assert(
    coverage &&
      (await page.locator(".home-section-coverage").count()) === 0 &&
      (await page.locator(".home-section-scores").count()) === 1 &&
      (await page
        .getByText(
          `${coverage.measured} of ${coverage.total} MCP ${database.mcp_spec} capabilities have measurements.`,
          {exact: false},
        )
        .count()) === 1,
    "Home page does not lead with the measured framework summary",
  );
  await homeSearch.focus();
  await page.locator(".recent-searches").waitFor();
  await page.getByRole("button", {name: "Settings"}).click();
  const settingsDialog = page.getByRole("dialog", {name: "Settings"});
  await settingsDialog.waitFor();
  assert(
    (await settingsDialog.getByLabel("MCP protocol snapshot").count()) === 1 &&
      (await settingsDialog.getByRole("radio", {name: "Support status"}).count()) === 1 &&
      (await page.locator(".recent-searches").count()) === 0,
    "Settings did not open accessibly or close search history",
  );
  await settingsDialog.getByRole("button", {name: "Done"}).click();

  await page
    .getByRole("navigation", {name: "Primary navigation"})
    .getByRole("link", {name: "Stats"})
    .click();
  await page.getByRole("heading", {name: "Stats", exact: true}).waitFor();
  assert(
    page.url().endsWith("#/stats") &&
      (await page.locator(".stats-matrix tbody tr").count()) ===
        capabilityCount &&
      (await page.getByRole("tab", {name: /Capabilities/}).count()) === 1 &&
      (await page.getByRole("tab", {name: /Frameworks/}).count()) === 1,
    "Stats route did not expose the exhaustive capability view",
  );
  await page
    .locator(".stats-filter-grid label")
    .filter({hasText: "Framework"})
    .locator("select")
    .selectOption("openai-agents");
  await page.getByLabel("Support state").selectOption("n");
  assert(
    page.url().includes("framework=openai-agents") &&
      page.url().includes("support=n") &&
      (await page.locator(".stats-matrix tbody tr").count()) < capabilityCount,
    "Stats filters were not reflected in the shareable URL or table",
  );
  const [csvDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", {name: "Export CSV"}).click(),
  ]);
  assert(
    csvDownload.suggestedFilename().includes("mcp-2026-07-28") &&
      csvDownload.suggestedFilename().endsWith(".csv") &&
      (await page.getByRole("button", {name: "Export JSON"}).count()) === 1,
    "Stats exports are not available",
  );
  await page.getByRole("tab", {name: /Frameworks/}).click();
  assert(
    page.url().includes("view=frameworks") &&
      (await page.locator(".framework-card").count()) === 5 &&
      (await page.locator(".framework-measurement-note").count()) === 3,
    "Compare frameworks did not move inside Stats",
  );
  await page.getByRole("button", {name: "Reset filters"}).click();
  await page.getByRole("tab", {name: /Capabilities/}).click();
  await page
    .getByRole("navigation", {name: "Primary navigation"})
    .getByRole("link", {name: "Home"})
    .click();
  await specSelector.selectOption("2025-11-25");
  await page.getByText("5 of 5 frameworks reach this revision").waitFor();
  assert(
    page.url().includes("?spec=2025-11-25") &&
      (await page
        .locator('.home-framework-score[data-agent-id="crewai"]')
        .getAttribute("data-summary-version")) === legacyCrewaiVersion,
    "The protocol selector did not load the complete legacy snapshot",
  );
  await specSelector.selectOption("2026-07-28");
  await page.getByText("2 of 5 frameworks reach this revision").waitFor();

  await homeSearch.fill("format");
  await page
    .getByRole("navigation", {name: "Primary navigation"})
    .getByRole("link", {name: "Home"})
    .click();
  assert(
    page.url().endsWith("#/") && (await homeSearch.inputValue()) === "",
    "Home nav did not reset while already on the index route",
  );
  await homeSearch.fill("hint");
  await page.getByRole("link", {name: "Reset Can AI use search"}).click();
  assert(
    (await homeSearch.inputValue()) === "",
    "Search wordmark did not share the home reset behavior",
  );

  for (const recentQuery of [
    "hint",
    "schema",
    "tool",
    "object",
    "description",
    "format",
    "enum",
  ]) {
    await homeSearch.fill(recentQuery);
    await homeSearch.press("Enter");
  }
  await homeSearch.fill("HINT");
  await homeSearch.press("Enter");
  await homeSearch.fill("x");
  await homeSearch.press("Enter");
  await homeSearch.fill("zzzznotfound");
  await homeSearch.press("Enter");
  const storedRecents = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("mcp-mirror:recent-searches:v1") ?? "[]"),
  );
  assert(
    storedRecents.length === 6 &&
      storedRecents[0] === "HINT" &&
      !storedRecents.includes("hint") &&
      !storedRecents.includes("x") &&
      !storedRecents.includes("zzzznotfound"),
    `Recent search normalization or eligibility failed: ${JSON.stringify(storedRecents)}`,
  );
  await page.reload({waitUntil: "networkidle"});
  const reloadedSearch = page.getByRole("searchbox", {name: "Search MCP capabilities"});
  const recentPanel = page.getByRole("region", {name: "Recent searches"});
  await reloadedSearch.fill("");
  await reloadedSearch.blur();
  await reloadedSearch.focus();
  await recentPanel.waitFor();
  const recentGeometry = await recentPanel.evaluate((panel) => {
    const panelRect = panel.getBoundingClientRect();
    const fieldRect = panel.closest(".capability-search-wrap").getBoundingClientRect();
    const hero = panel.closest(".search-hero-inner");
    const heroRect = hero.getBoundingClientRect();
    const visibleElement = document.elementFromPoint(
      panelRect.left + panelRect.width / 2,
      panelRect.bottom - 4,
    );
    return {
      anchored: panelRect.top >= fieldRect.bottom,
      contained:
        panelRect.left >= 0 && panelRect.right <= document.documentElement.clientWidth,
      extendsPastHero: panelRect.bottom > heroRect.bottom,
      heroOverflow: getComputedStyle(hero).overflow,
      visiblePastHero: panel.contains(visibleElement),
    };
  });
  assert(
    recentGeometry.anchored &&
      recentGeometry.contained &&
      recentGeometry.extendsPastHero &&
      recentGeometry.heroOverflow === "visible" &&
      recentGeometry.visiblePastHero,
    `Recent searches panel is not safely anchored: ${JSON.stringify(recentGeometry)}`,
  );
  await recentPanel.getByRole("button", {name: "HINT", exact: true}).focus();
  await recentPanel.getByRole("button", {name: "HINT", exact: true}).press("Enter");
  assert(
    (await reloadedSearch.inputValue()) === "HINT",
    "Keyboard activation did not run a recent search",
  );
  await page.getByRole("link", {name: "Reset Can AI use search"}).click();
  await reloadedSearch.focus();
  await recentPanel.getByRole("button", {name: /Remove recent search HINT/}).click();
  assert(
    !(await page.evaluate(() =>
      JSON.parse(localStorage.getItem("mcp-mirror:recent-searches:v1") ?? "[]"),
    )).includes("HINT"),
    "Per-item recent search removal failed",
  );
  await recentPanel.getByRole("button", {name: "Clear recent searches"}).click();
  assert(
    (await page.evaluate(() =>
      JSON.parse(localStorage.getItem("mcp-mirror:recent-searches:v1") ?? "[]"),
    )).length === 0,
    "Clear recent searches failed",
  );

  const searchBox = page.getByRole("searchbox", {name: "Search MCP capabilities"});
  const readSearchStyle = () =>
    searchBox.evaluate((node) => {
      const input = window.getComputedStyle(node);
      const group = window.getComputedStyle(node.closest(".search-field__group"));
      return {
        inputBackground: input.backgroundColor,
        inputBoxShadow: input.boxShadow,
        inputOutline: input.outlineStyle,
        groupBackground: group.backgroundColor,
        groupBorderBottomColor: group.borderBottomColor,
        groupBoxShadow: group.boxShadow,
        groupOutline: group.outlineStyle,
      };
    });
  await searchBox.evaluate((node) => node.blur());
  const unfocusedSearchStyle = await readSearchStyle();
  await searchBox.focus();
  const focusedSearchStyle = await readSearchStyle();
  const isTransparent = (value) =>
    value === "rgba(0, 0, 0, 0)" || value === "transparent";
  assert(
    [
      unfocusedSearchStyle,
      focusedSearchStyle,
    ].every(
      (style) =>
        isTransparent(style.inputBackground) &&
        !isTransparent(style.groupBackground) &&
        style.inputOutline === "none" &&
        style.groupOutline === "none" &&
        style.inputBoxShadow === "none",
    ),
    `Search field lost its restrained highlighted surface: ${JSON.stringify({
      unfocusedSearchStyle,
      focusedSearchStyle,
    })}`,
  );
  assert(
    focusedSearchStyle.groupBorderBottomColor !==
      unfocusedSearchStyle.groupBorderBottomColor &&
      focusedSearchStyle.groupBackground !==
        unfocusedSearchStyle.groupBackground &&
      focusedSearchStyle.groupBoxShadow === "none",
    "Search focus state is not visibly stronger",
  );
  await searchBox.fill("hint");
  const typedSearchStyle = await readSearchStyle();
  assert(
    isTransparent(typedSearchStyle.inputBackground) &&
      !isTransparent(typedSearchStyle.groupBackground) &&
      typedSearchStyle.inputOutline === "none" &&
      typedSearchStyle.groupOutline === "none" &&
      typedSearchStyle.inputBoxShadow === "none" &&
      typedSearchStyle.groupBoxShadow === "none",
    `Typed search field lost its focus highlight: ${JSON.stringify(
      typedSearchStyle,
    )}`,
  );

  const tableCount = await page.locator(".feature-module.is-search-result").count();
  assert(tableCount > 1, "Live search did not default to full feature cards");
  const tableWidths = await page
    .locator(".feature-module.is-search-result")
    .evaluateAll((nodes) =>
      nodes.map((node) => Math.round(node.getBoundingClientRect().width)),
    );
  assert(
    tableWidths.every((width) => width > 1000),
    `A full table result did not span the page: ${tableWidths.join(", ")}`,
  );
  assert(
    (await page.locator(".feature-module.is-search-result .capability-grid-section").count()) ===
      tableCount,
    "A full feature card is missing its support grid",
  );

  await page.getByRole("radio", {name: "List"}).click();
  const cardCount = await page.locator(".capability-card-compact").count();
  assert(
    tableCount === cardCount,
    `List mode changed result count from ${tableCount} to ${cardCount}`,
  );
  const cardWidths = await page
    .locator(".capability-card-compact")
    .evaluateAll((nodes) =>
      nodes.map((node) => Math.round(node.getBoundingClientRect().width)),
    );
  assert(
    cardWidths.every((width) => width < 500),
    `A compact list result expanded into a page-wide panel: ${cardWidths.join(", ")}`,
  );

  await Promise.all([
    page.waitForURL(/#\/cap\//),
    page.getByRole("link", {name: /Open measurement/}).first().click(),
  ]);
  await page.locator(".feature-module.is-detail").waitFor();
  await page.locator('button[aria-label="Star this capability"]').click();
  await page.getByRole("tab", {name: "Test a feature"}).click();
  await page.getByText(/no model call or model API key is required/i).waitFor();

  await page.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
  await page.getByRole("searchbox", {name: "Search MCP capabilities"}).fill("hint");
  assert(
    (await page.evaluate(() =>
      JSON.parse(localStorage.getItem("mcpMirrorStars") ?? "[]"),
    )).length > 0,
    "Star selection did not persist",
  );

  const offline = await browser.newPage({viewport: {width: 1280, height: 800}});
  offline.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  await offline.goto(
    pathToFileURL(path.resolve("docs", "standalone.html")).href,
    {waitUntil: "load"},
  );
  await offline
    .getByLabel("Capability search")
    .getByRole("link", {name: "Reset Can AI use search"})
    .waitFor();
  assert(
    await offline.evaluate(
      () =>
        Boolean(window.__MCP_MIRROR_DATA__) &&
        Boolean(window.__MCP_MIRROR_SPEC_INDEX__) &&
        Object.keys(window.__MCP_MIRROR_DATASETS__ ?? {}).length === 2,
    ),
    "Standalone build did not expose both inlined protocol snapshots",
  );
  await offline
    .getByLabel("MCP specification revision")
    .selectOption("2025-11-25");
  await offline.getByText("5 of 5 frameworks reach this revision").waitFor();

  assert(
    consoleErrors.length === 0,
    `Browser console errors: ${consoleErrors.join(" | ")}`,
  );

  console.log(
    `site smoke passed: ${tableCount} full search tables, compact list toggle, detail tabs, ${widths.viewport}px mobile viewport`,
  );
} finally {
  await browser.close();
  await new Promise((resolve, reject) => {
    server.httpServer.close((error) => (error ? reject(error) : resolve()));
  });
}
