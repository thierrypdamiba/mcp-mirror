import {readFile} from "node:fs/promises";
import path from "node:path";
import {pathToFileURL} from "node:url";

import {chromium} from "playwright-core";
import {preview} from "vite";

const chromePath =
  process.env.CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const widths = [320, 375, 390, 768, 1024];
const routes = [
  ["index", "#/"],
  ["destructiveHint detail", "#/cap/destructive-hint"],
  ["stats capabilities", "#/stats"],
  ["stats frameworks", "#/stats?view=frameworks"],
  ["changes", "#/changes"],
  ["method", "#/method"],
];

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    documentScrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    grids: [...document.querySelectorAll(".support-grid-scroll")].map(
      (element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }),
    ),
  }));
  assert(
    metrics.documentScrollWidth === metrics.innerWidth,
    `${label}: document is ${metrics.documentScrollWidth}px wide in a ${metrics.innerWidth}px viewport`,
  );
  metrics.grids.forEach((grid, index) => {
    assert(
      grid.scrollWidth === grid.clientWidth,
      `${label}: support grid ${index + 1} scrolls ${grid.scrollWidth - grid.clientWidth}px horizontally`,
    );
  });
}

const database = JSON.parse(
  await readFile("site/public/data/data-1.0.json", "utf8"),
);
const legacyDatabase = JSON.parse(
  await readFile("site/public/data/data-2025-11-25.json", "utf8"),
);
const server = await preview({
  configFile: "vite.config.ts",
  preview: {
    host: "127.0.0.1",
    port: 0,
    strictPort: false,
  },
});
const address = server.httpServer.address();
assert(address && typeof address !== "string", "Preview server did not bind");
const baseUrl = `http://127.0.0.1:${address.port}/`;
const browser = await chromium.launch({executablePath: chromePath, headless: true});
const context = await browser.newContext();
await context.grantPermissions(["clipboard-read", "clipboard-write"], {
  origin: baseUrl.slice(0, -1),
});
const consoleErrors = [];

try {
  for (const width of widths) {
    const page = await context.newPage();
    await page.setViewportSize({width, height: 1000});
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(`${width}px: ${message.text()}`);
      }
    });

    for (const [name, hash] of routes) {
      await page.goto(`${baseUrl}${hash}`, {waitUntil: "networkidle"});
      await assertNoHorizontalOverflow(page, `${width}px ${name}`);
    }

    await page.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
    assert(
      (await page.getByLabel("MCP specification revision").inputValue()) ===
        "2026-07-28" &&
        (await page.getByText("2 of 5 frameworks reach this revision").count()) ===
          1,
      `${width}px: current MCP snapshot is not explicit`,
    );
    const canvasColor = await page.evaluate(
      () => getComputedStyle(document.body).backgroundColor,
    );
    assert(
      canvasColor === "rgb(0, 43, 54)",
      `${width}px: page canvas is not Solarized base03 (${canvasColor})`,
    );
    const headerGeometry = await page.evaluate(() => {
      const header = document.querySelector(".site-header");
      const main = document.querySelector(".header-main-row");
      const nav = document.querySelector(".site-nav");
      const ticker = document.querySelector(".news-ticker");
      const links = [...nav.querySelectorAll(".nav-link")];
      const tickerStyle = getComputedStyle(ticker);
      const headerStyle = getComputedStyle(header);
      const activeLinkStyle = getComputedStyle(links[0]);
      const activeBackgroundParts =
        activeLinkStyle.backgroundColor.match(/[\d.]+/g)?.map(Number) ?? [];
      const mainRect = main.getBoundingClientRect();
      const tickerRect = ticker.getBoundingClientRect();
      const linkRects = links.map((link) => link.getBoundingClientRect());
      const isMobile = window.innerWidth <= 544;
      return {
        labels: links.map((link) => link.getAttribute("aria-label")),
        navCount: document.querySelectorAll(".site-header nav").length,
        listCount: document.querySelectorAll(".site-header nav > ul").length,
        brandCount: document.querySelectorAll(".site-header .header-brand").length,
        active: links.map((link) => link.getAttribute("aria-current")),
        ordered: links.every(
          (link, index) =>
            index === 0 ||
            link.getBoundingClientRect().left >=
              links[index - 1].getBoundingClientRect().right,
        ),
        tickerPlacement: isMobile
          ? tickerRect.top >= linkRects[0].bottom
          : linkRects[1].right <= tickerRect.left &&
            tickerRect.right <= linkRects[2].left &&
            tickerRect.top >= mainRect.top &&
            tickerRect.bottom <= mainRect.bottom,
        background: tickerStyle.backgroundColor,
        border: tickerStyle.borderStyle,
        shadow: tickerStyle.boxShadow,
        radius: tickerStyle.borderRadius,
        fontFamilyMatches: tickerStyle.fontFamily === headerStyle.fontFamily,
        headerHeight: header.getBoundingClientRect().height,
        tickerTimeCount: ticker.querySelectorAll("time").length,
        navFontSize: Number.parseFloat(activeLinkStyle.fontSize),
        navFontWeight: Number.parseInt(activeLinkStyle.fontWeight, 10),
        activeBackground: activeLinkStyle.backgroundColor,
        activeBackgroundAlpha: activeBackgroundParts[3] ?? 1,
      };
    });
    assert(
      JSON.stringify(headerGeometry.labels) ===
        JSON.stringify(["Home", "Stats", "News", "About"]) &&
        headerGeometry.navCount === 1 &&
        headerGeometry.listCount === 1 &&
        headerGeometry.brandCount === 0 &&
        headerGeometry.active[0] === "page" &&
        headerGeometry.ordered &&
        headerGeometry.tickerPlacement &&
        headerGeometry.background === "rgba(0, 0, 0, 0)" &&
        headerGeometry.border === "none" &&
        headerGeometry.shadow === "none" &&
        headerGeometry.radius === "0px" &&
        headerGeometry.fontFamilyMatches &&
        headerGeometry.tickerTimeCount === 0 &&
        headerGeometry.navFontSize >= 11.5 &&
        headerGeometry.navFontWeight >= 600 &&
        headerGeometry.activeBackground.includes("203, 75, 22") &&
        headerGeometry.activeBackgroundAlpha <= 0.25 &&
        Math.abs(headerGeometry.headerHeight - (width <= 544 ? 71 : 43)) <= 1,
      `${width}px: header hierarchy or ticker integration is incorrect: ${JSON.stringify(headerGeometry)}`,
    );
    const searchGapGeometry = await page.evaluate(() => {
      const wordmark = document.querySelector(".search-wordmark").getBoundingClientRect();
      const field = document.querySelector(".capability-search-wrap").getBoundingClientRect();
      const question = document.querySelector(".search-question").getBoundingClientRect();
      return {
        before: field.left - wordmark.right,
        after: question.left - field.right,
      };
    });
    assert(
      searchGapGeometry.before > 0 && searchGapGeometry.after > 0,
      `${width}px: highlighted search field lacks word gaps: ${JSON.stringify(searchGapGeometry)}`,
    );
    const frameworkRows = await page
      .locator(
        '.home-framework-scores[data-version-kind="current_version"] .home-framework-score',
      )
      .evaluateAll(
      (elements) =>
        elements.map((element) => ({
          agentId: element.getAttribute("data-agent-id"),
          version: element.getAttribute("data-summary-version"),
          visibleVersion:
            element.querySelector(".framework-summary-version")?.textContent?.trim() ??
            "",
        })),
      );
    assert(
      frameworkRows.length === Object.keys(database.agents).length,
      `${width}px: framework summary rendered ${frameworkRows.length} rows`,
    );
    frameworkRows.forEach(({agentId, version, visibleVersion}) => {
      const expected = database.agents[agentId]?.current_version;
      assert(expected, `${width}px: unknown framework summary row ${agentId}`);
      assert(
        version === expected && visibleVersion === expected,
        `${width}px: ${agentId} summary showed ${visibleVersion || "<empty>"}; expected ${expected}`,
      );
    });
    assert(
      (await page.getByRole("heading", {name: "Frameworks", exact: true}).count()) === 1 &&
        (await page.getByRole("radio", {name: "Current version"}).count()) === 0 &&
        (await page.getByRole("radio", {name: "Dev version"}).count()) === 0 &&
        (await page.getByRole("link", {name: "Compare all frameworks"}).getAttribute("href")) ===
          "#/stats?view=frameworks",
      `${width}px: framework snapshot is not a compact current-version answer`,
    );
    const newIds = await page
      .locator(".home-section-new li")
      .evaluateAll((items) => items.map((item) => item.dataset.capabilityId));
    const popularIds = await page
      .locator(".home-section-popular li")
      .evaluateAll((items) => items.map((item) => item.dataset.capabilityId));
    const expectedNewIds = Object.values(database.data)
      .filter(
        (capability) =>
          capability.shown !== false && Boolean(capability.measured.run_date),
      )
      .sort(
        (left, right) =>
          right.measured.run_date.localeCompare(left.measured.run_date) ||
          left.title.localeCompare(right.title),
      )
      .slice(0, 5)
      .map(({id}) => id);
    assert(
      JSON.stringify(newIds) === JSON.stringify(expectedNewIds) &&
        JSON.stringify(popularIds) ===
          JSON.stringify(["destructive-hint", "read-only-hint", "required", "nested-objects", "enum"]) &&
        (await page.locator(".home-section").count()) === 7 &&
        (await page.locator(".home-section-coverage").count()) === 0 &&
        (await page.locator(".home-sections > .home-section").first().getAttribute("class"))
          ?.includes("home-section-scores") &&
        (await page.locator(".home-section-new small").count()) === 0 &&
        (await page.locator(".home-section-popular small").count()) === 0 &&
        (await page.getByRole("heading", {name: "Test a capability"}).count()) === 1 &&
        (await page.getByRole("heading", {name: "MCP facts"}).count()) === 1 &&
        (await page.getByRole("heading", {name: "How it works"}).count()) === 1 &&
        (await page.locator(".home-evidence-table, .home-explore, .feature-strip").count()) === 0 &&
        (await page.getByRole("radio", {name: "Popular"}).count()) === 0 &&
        (await page.getByRole("radio", {name: "Trending"}).count()) === 0,
      `${width}px: homepage is not the expected framework-first seven-section answer`,
    );
    const homepageColumnCount = await page
      .locator(".home-sections")
      .evaluate(
        (element) =>
          getComputedStyle(element).gridTemplateColumns.split(" ").length,
      );
    assert(
      homepageColumnCount === (width <= 640 ? 1 : width <= 835 ? 2 : 3),
      `${width}px: homepage uses ${homepageColumnCount} columns at the wrong breakpoint`,
    );
    if (width === 1024) {
      const factSection = page.locator(".home-section-dyk");
      assert(
        (await factSection.locator("li").count()) === 3 &&
          (await factSection.getByText("MCP messages use JSON-RPC 2.0.").count()) === 1 &&
          (await factSection.locator('a[target="_blank"]').count()) === 3,
        "Homepage MCP facts are not concise and source-linked",
      );
      assert(
        (await page
          .getByRole("link", {
            name: "deterministic adapter diff source on GitHub, opens externally",
          })
          .getAttribute("href"))?.endsWith(
          "/blob/main/src/mcp_mirror/diff.py",
        ),
        "Footer does not link to the adapter diff implementation",
      );
    }

    await page.goto(`${baseUrl}#/stats`, {waitUntil: "networkidle"});
    const statsHeaders = (await page.locator(".stats-matrix thead th").allTextContents())
      .map((value) => value.trim().replace(/\s+/g, " "));
    assert(
      statsHeaders.length === Object.keys(database.agents).length + 4 &&
        statsHeaders[0] === "Capability" &&
        statsHeaders.slice(-3).join("|") === "Present|Retained|Dropped" &&
        (await page.locator(".stats-matrix tbody tr").count()) ===
          Object.values(database.data).filter(
            (capability) => capability.shown !== false,
          ).length &&
        (await page
          .locator(".stats-matrix tbody tr")
          .first()
          .locator(".stats-framework-cell")
          .count()) === Object.keys(database.agents).length,
      `${width}px: Stats does not expose every capability and framework column`,
    );
    await assertNoHorizontalOverflow(page, `${width}px stats matrix`);
    if (width === 1024) {
      await page.getByLabel("Sort").selectOption("dropped");
      const droppedCounts = await page
        .locator(".stats-total-n strong")
        .allTextContents();
      assert(
        droppedCounts.every(
          (value, index) =>
            index === 0 || Number(droppedCounts[index - 1]) >= Number(value),
        ),
        "Dropped sort is not descending",
      );
      await page
        .locator(".stats-filter-grid label")
        .filter({hasText: "Framework"})
        .locator("select")
        .selectOption("openai-agents");
      assert(
        !(await page.getByLabel("Version").isDisabled()),
        "Framework selection did not enable version filtering",
      );
      await page.getByLabel("Support state").selectOption("n");
      assert(
        page.url().includes("sort=dropped") &&
          page.url().includes("framework=openai-agents") &&
          page.url().includes("support=n"),
        "Stats state is not encoded in the shareable URL",
      );
      await page.getByRole("button", {name: "Copy view link"}).click();
      await page.getByRole("status").filter({hasText: "Link copied"}).waitFor();
      assert(
        (await page.evaluate(() => navigator.clipboard.readText())) === page.url(),
        "Stats view link was not copied",
      );
      await page.getByRole("tab", {name: /Frameworks/}).click();
      assert(
        page.url().includes("view=frameworks") &&
          (await page.locator(".framework-card").count()) ===
            Object.keys(database.agents).length &&
          (await page.locator(".framework-measurement-note").count()) === 3 &&
          (await page.getByText(/not a “best framework” leaderboard/i).count()) === 1,
        "Framework comparison is not contained within Stats",
      );
      await assertNoHorizontalOverflow(page, "1024px filtered framework stats");
    }

    await page.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
    const search = page.getByRole("searchbox", {
      name: "Search MCP capabilities",
    });
    await search.fill("hint");
    await page.locator(".feature-module.is-search-result").first().waitFor();
    assert(
      (await page.locator(".feature-module.is-search-result").count()) > 1,
      `${width}px: search did not render multiple full cards`,
    );
    const moduleGeometry = await page
      .locator(".feature-module.is-search-result")
      .evaluateAll((modules) =>
        modules.slice(0, 2).map((module) => {
          const rect = module.getBoundingClientRect();
          const style = getComputedStyle(module);
          return {
            top: rect.top,
            bottom: rect.bottom,
            borderWidth: Number.parseFloat(style.borderTopWidth),
            borderStyle: style.borderTopStyle,
          };
        }),
      );
    const minimumModuleGap = width <= 544 ? 18 : 24;
    assert(
      moduleGeometry.length === 2 &&
        moduleGeometry[1].top - moduleGeometry[0].bottom >= minimumModuleGap &&
        moduleGeometry.every(
          (module) =>
            module.borderWidth === 1 && module.borderStyle === "solid",
        ),
      `${width}px: feature module spacing or borders failed acceptance`,
    );
    const requiredRegions = [
      ".feature-action-rail",
      ".feature-module-header",
      '[data-region="measurement-baseline"]',
      '[data-region="description"]',
      '[data-region="display-controls"]',
      '[data-region="framework-matrix"]',
      ".feature-tabs",
    ];
    for (const selector of requiredRegions) {
      assert(
        (await page.locator(`.feature-module.is-search-result ${selector}`).count()) ===
          (await page.locator(".feature-module.is-search-result").count()),
        `${width}px: search feature modules are missing ${selector}`,
      );
    }
    if (width === 1024) {
      const firstModule = page.locator(".feature-module.is-search-result").first();
      const searchModules = page.locator(".feature-module.is-search-result");
      for (let index = 0; index < await searchModules.count(); index += 1) {
        const module = searchModules.nth(index);
        const testTab = module.getByRole("tab", {name: "Test a feature"});
        assert(
          (await testTab.count()) === 1,
          `Search FeatureModule ${index + 1} does not have exactly one Test a feature tab`,
        );
        await testTab.click();
        // A feature no scan covers has no command to offer, so the panel explains what a
        // probe would have to do instead of printing a command that reproduces nothing.
        const unmeasured =
          (await module.getAttribute("data-measurement-state")) ===
          "not_measured";
        assert(
          unmeasured
            ? (await module.locator(".feature-probe").count()) === 1 &&
              (await module.getByRole("button", {name: "Copy command"}).count()) === 0
            : (await module.locator(".feature-test-controls select").count()) === 2 &&
              (await module.getByRole("button", {name: "Copy command"}).count()) === 1,
          `Search FeatureModule ${index + 1} Test a feature panel is not functional`,
        );
      }
      const destructiveSearchModule = page.locator(
        '.feature-module.is-search-result[data-capability-id="destructive-hint"]',
      );
      // Derived rather than hardcoded: how many cells carry a note changes with the
      // data, but they must always number 1..n left to right.
      const noteMarkers = (
        await destructiveSearchModule
          .locator('.support-cell[data-current="true"] .support-note-ref')
          .allTextContents()
      ).map((value) => value.trim());
      assert(
        noteMarkers.length > 0 &&
          JSON.stringify(noteMarkers) ===
            JSON.stringify(noteMarkers.map((_, index) => `#${index + 1}`)),
        `Search-result FeatureModule note markers are not in reading order: ${noteMarkers.join(" ")}`,
      );
      await firstModule.getByRole("tab", {name: "Feedback"}).click();
      assert(
        (await firstModule.getByText(/Submit a correction with evidence/).count()) === 1,
        "Feedback panel did not open inside its search feature module",
      );
      await firstModule.getByRole("tab", {name: "Notes"}).click();
      assert(
        (await firstModule.locator(".numbered-notes").count()) === 1,
        "Notes panel did not reopen inside its search feature module",
      );
    }
    await assertNoHorizontalOverflow(page, `${width}px multi-result search`);

    await page.goto(`${baseUrl}#/cap/destructive-hint`, {
      waitUntil: "networkidle",
    });
    const currentCells = await page
      .locator('.support-cell[data-current="true"]')
      .evaluateAll((elements) =>
        elements.map((element) => ({
          agentId: element.getAttribute("data-agent-id"),
          text: element.textContent?.trim() ?? "",
          version: element.getAttribute("data-version"),
          visible: Boolean(
            element.getClientRects().length &&
              Number.parseFloat(getComputedStyle(element).opacity) > 0,
          ),
        })),
      );
    assert(
      currentCells.length === Object.keys(database.agents).length,
      `${width}px: current-version feature cells are incomplete`,
    );
    currentCells.forEach(({agentId, text, version, visible}) => {
      const expected = database.agents[agentId]?.current_version;
      assert(
        visible && version === expected && text.includes(expected),
        `${width}px: ${agentId} feature cell did not visibly show ${expected}`,
      );
    });
    const moduleRegions = await page
      .locator(".feature-module.is-detail")
      .locator(
        '.feature-action-rail, .feature-module-header, [data-region="measurement-baseline"], [data-region="description"], [data-region="display-controls"], [data-region="framework-matrix"], .feature-tabs',
      )
      .count();
    assert(moduleRegions === 7, `${width}px: detail FeatureModule regions are incomplete`);
    const tabGeometry = await page.locator(".feature-tabs [role=tab]").evaluateAll(
      (tabs) =>
        tabs.map((tab) => {
          const rect = tab.getBoundingClientRect();
          return {centerY: rect.y + rect.height / 2, left: rect.left};
        }),
    );
    const matrixLeft = await page
      .locator(".feature-matrix .support-grid")
      .evaluate((element) => element.getBoundingClientRect().left);
    const tabListBottom = await page
      .locator(".feature-tabs .tabs__list-container")
      .evaluate((element) => element.getBoundingClientRect().bottom);
    const panelTop = await page
      .locator(".feature-tabs [role=tabpanel]")
      .evaluate((element) => element.getBoundingClientRect().top);
    assert(
      tabGeometry.length === 5 &&
        tabGeometry.every(
          (tab) => Math.abs(tab.centerY - tabGeometry[0].centerY) <= 1,
        ) &&
        Math.abs(tabGeometry[0].left - matrixLeft) <= 1 &&
        Math.abs(panelTop - tabListBottom) <= 1,
      `${width}px: FeatureModule tabs are not one attached horizontal row: ${JSON.stringify({tabGeometry, matrixLeft, tabListBottom, panelTop})}`,
    );
    const contrast = await page
      .locator(
        '.support-cell[data-agent-id="openai-agents"][data-version="0.22.0"]',
      )
      .evaluate((element) => {
        const parse = (color) => {
          const value = color.trim();
          if (/^#[\da-f]{6}$/i.test(value)) {
            return [1, 3, 5].map((offset) =>
              Number.parseInt(value.slice(offset, offset + 2), 16),
            );
          }
          return value.match(/\d+(?:\.\d+)?/g)?.slice(0, 3).map(Number) ??
            [0, 0, 0];
        };
        const luminance = (rgb) => {
          const values = rgb.map((value) => {
            const channel = value / 255;
            return channel <= 0.03928
              ? channel / 12.92
              : ((channel + 0.055) / 1.055) ** 2.4;
          });
          return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
        };
        const rootStyle = getComputedStyle(document.documentElement);
        const semanticColor =
          element.classList.contains("support-y")
            ? "--solar-green"
            : element.classList.contains("support-a")
              ? "--solar-yellow"
              : element.classList.contains("support-n")
                ? "--no-support"
                : "--solar-base01";
        const foregroundColor =
          element.classList.contains("support-y") ||
          element.classList.contains("support-a")
            ? "--solar-base03"
            : "--solar-base3";
        const foreground = luminance(
          parse(rootStyle.getPropertyValue(foregroundColor)),
        );
        const background = luminance(parse(rootStyle.getPropertyValue(semanticColor)));
        return (
          (Math.max(foreground, background) + 0.05) /
          (Math.min(foreground, background) + 0.05)
        );
      });
    assert(contrast >= 4.5, `${width}px: representative support cell contrast is ${contrast}`);
    if (width === 1024) {
      // Derived from the cells themselves: an adapter owes a note whenever it did
      // something to the value or could not reach the revision at all, so which
      // frameworks are annotated is a property of the row, not of who was scanned.
      const destructiveStats = database.data["destructive-hint"].stats;
      const expectedNotes = Object.entries(database.agents)
        .filter(([agentId, agent]) =>
          (destructiveStats[agentId]?.[agent.current_version] ?? "").includes("#"),
        )
        .map(([, agent], index) => ({
          number: index + 1,
          label: `${agent.name} ${agent.current_version}`,
        }));
      const visibleRefs = (
        await page
          .locator('.support-cell[data-current="true"] .support-note-ref')
          .allTextContents()
      ).map((value) => value.trim());
      assert(
        visibleRefs.length === expectedNotes.length &&
          JSON.stringify(visibleRefs) ===
            JSON.stringify(expectedNotes.map(({number}) => `#${number}`)),
        `Current note markers are not in reading order: ${visibleRefs.join(", ")}`,
      );
      for (const {number, label} of expectedNotes) {
        const noteMarker = page
          .getByRole("link", {name: `Read note ${number} for ${label}`})
          .first();
        await noteMarker.focus();
        await noteMarker.press("Enter");
        await page.waitForFunction(
          (suffix) => document.activeElement?.id.endsWith(suffix),
          `-note-${number}`,
        );
        assert(
          (await page.locator(`[id$="-note-${number}"]`).textContent()).includes(
            `#${number} · ${label}`,
          ),
          `Note ${number} does not visibly identify ${label}`,
        );
      }
      await page
        .locator(
          '.support-cell[data-agent-id="openai-agents"][data-version="0.22.0"]',
        )
        .screenshot({path: "/tmp/mcp-mirror-note-cell.png"});
    }

    if (width === 390) {
      await page.reload({waitUntil: "networkidle"});
      await page.screenshot({
        path: "/tmp/mcp-mirror-destructive-390.png",
        fullPage: true,
      });
    }
    await page.close();
  }

  for (const width of [544, 640, 641, 835, 836, 900, 901, 1280]) {
    const page = await context.newPage();
    await page.setViewportSize({width, height: 900});
    await page.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
    await assertNoHorizontalOverflow(page, `${width}px home breakpoint`);
    const homepageColumnCount = await page
      .locator(".home-sections")
      .evaluate(
        (element) =>
          getComputedStyle(element).gridTemplateColumns.split(" ").length,
      );
    assert(
      homepageColumnCount === (width <= 640 ? 1 : width <= 835 ? 2 : 3),
      `${width}px breakpoint rendered ${homepageColumnCount} homepage columns`,
    );

    await page.goto(`${baseUrl}#/stats`, {waitUntil: "networkidle"});
    await assertNoHorizontalOverflow(page, `${width}px stats breakpoint`);
    const statsMatrixDisplay = await page
      .locator(".stats-matrix")
      .evaluate((element) => getComputedStyle(element).display);
    assert(
      statsMatrixDisplay === (width <= 900 ? "block" : "table"),
      `${width}px Stats matrix used ${statsMatrixDisplay} at the wrong breakpoint`,
    );
    await page.close();
  }

  const titlePage = await context.newPage();
  await titlePage.setViewportSize({width: 1024, height: 800});
  for (const [id, expected] of [
    ["read-only-hint", "readOnlyHint"],
    ["destructive-hint", "destructiveHint"],
    ["format", "format"],
  ]) {
    await titlePage.goto(`${baseUrl}#/cap/${id}`, {waitUntil: "networkidle"});
    assert(
      (await titlePage.locator(".feature-title-line h2 code").textContent()) === expected,
      `${id} did not render with canonical inline-code casing`,
    );
  }
  await titlePage.goto(`${baseUrl}#/cap/one-of-any-of`, {waitUntil: "networkidle"});
  assert(
    JSON.stringify(
      await titlePage.locator(".feature-title-line h2 code").allTextContents(),
    ) === JSON.stringify(["oneOf", "anyOf"]),
    "oneOf / anyOf did not preserve both canonical keywords",
  );
  await titlePage.goto(`${baseUrl}#/cap/arrays-of-objects`, {waitUntil: "networkidle"});
  assert(
    (await titlePage.locator(".feature-title-line h2").textContent()).trim() ===
      "Arrays of Objects" &&
      (await titlePage.locator(".feature-title-line h2 code").count()) === 0,
    "Conceptual capability lost intentional Title Case",
  );
  await titlePage.close();

  const copyPage = await context.newPage();
  await copyPage.setViewportSize({width: 1024, height: 900});
  await copyPage.goto(`${baseUrl}#/cap/destructive-hint`, {
    waitUntil: "networkidle",
  });
  await copyPage.getByRole("tab", {name: /Resources/}).click();
  assert(
    (await copyPage
      .locator(".feature-example-comparison .copy-code-block")
      .count()) === 2 &&
      (await copyPage
        .locator(
          '.feature-example-comparison .copy-code-block button[aria-label="Copy command"]',
        )
        .count()) === 2,
    "Capability example snippets are missing reusable Copy controls",
  );
  await copyPage.getByRole("tab", {name: "Test a feature"}).click();
  const reproduce = copyPage.locator(".command-box");
  const reproduceValue = await reproduce.locator("code").textContent();
  const reproduceCopy = reproduce.getByRole("button", {name: "Copy command"});
  await reproduceCopy.click();
  assert(
    (await copyPage.evaluate(() => navigator.clipboard.readText())) ===
      reproduceValue,
    "Reproduce Copy changed command whitespace or content",
  );
  assert(
    (await reproduceCopy.textContent()).includes("Copied"),
    "Reproduce Copy did not show its success state",
  );
  await copyPage.close();

  const offline = await context.newPage();
  await offline.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, "clipboard", {
      configurable: true,
      get: () => undefined,
    });
    window.__fallbackCopied = "";
    document.execCommand = (command) => {
      if (command !== "copy") {
        return false;
      }
      window.__fallbackCopied =
        document.activeElement instanceof HTMLTextAreaElement
          ? document.activeElement.value
          : "";
      return true;
    };
  });
  await offline.setViewportSize({width: 390, height: 844});
  const standaloneUrl =
    `${pathToFileURL(path.resolve("docs", "standalone.html")).href}#/cap/destructive-hint`;
  await offline.goto(standaloneUrl, {waitUntil: "load"});
  await offline.getByRole("tab", {name: "Test a feature"}).click();
  const offlineCommand = await offline.locator(".command-box code").textContent();
  const offlineCopy = offline
    .locator(".command-box")
    .getByRole("button", {name: "Copy command"});
  await offlineCopy.click();
  assert(
    (await offline.evaluate(() => window.__fallbackCopied)) === offlineCommand,
    "Standalone clipboard fallback changed command whitespace or content",
  );
  await offline.close();

  const tickerPage = await context.newPage();
  await tickerPage.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
  const ticker = tickerPage.locator(".news-ticker");
  assert(
    (await ticker.locator('.news-crawl-group:not([data-clone="true"]) a').count()) >= 3,
    "News crawl does not expose several unique headlines",
  );
  assert(
    (await ticker.locator('[data-clone="true"][aria-hidden="true"][inert]').count()) === 1,
    "News crawl clone is not hidden and inert",
  );
  const track = ticker.locator(".news-crawl-track");
  const initialTransform = await track.evaluate(
    (element) => getComputedStyle(element).transform,
  );
  await tickerPage.waitForTimeout(300);
  const movingTransform = await track.evaluate(
    (element) => getComputedStyle(element).transform,
  );
  assert(
    initialTransform !== movingTransform,
    "News crawl transform did not change over elapsed time",
  );
  await ticker.hover();
  await ticker.waitFor({state: "visible"});
  await tickerPage.waitForFunction(
    () => document.querySelector(".news-ticker")?.hasAttribute("data-paused"),
  );
  await tickerPage.waitForTimeout(50);
  const pausedTransform = await track.evaluate(
    (element) => getComputedStyle(element).transform,
  );
  await tickerPage.waitForTimeout(250);
  assert(
    (await track.evaluate((element) => getComputedStyle(element).transform)) ===
      pausedTransform,
    "News crawl did not pause on hover",
  );
  await tickerPage.locator(".news-ticker-link").first().focus();
  const focusedTransform = await track.evaluate(
    (element) => getComputedStyle(element).transform,
  );
  await tickerPage.waitForTimeout(250);
  assert(
    (await track.evaluate((element) => getComputedStyle(element).transform)) ===
      focusedTransform,
    "News crawl did not pause while a headline had keyboard focus",
  );
  await tickerPage.close();

  const reducedMotionPage = await context.newPage();
  await reducedMotionPage.emulateMedia({reducedMotion: "reduce"});
  await reducedMotionPage.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
  const reducedTicker = reducedMotionPage.locator(".news-ticker");
  assert(
    (await reducedTicker.locator(".news-crawl-track").evaluate(
      (element) => getComputedStyle(element).display,
    )) === "none" &&
      (await reducedTicker.locator(".news-crawl-reduced").isVisible()),
    "Reduced-motion crawl did not switch to its static headline",
  );
  await reducedMotionPage.close();

  const desktop = await context.newPage();
  await desktop.setViewportSize({width: 1920, height: 1100});
  await desktop.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
  await assertNoHorizontalOverflow(desktop, "1920px reflected desktop");
  const reflection = await desktop.evaluate(() => {
    const style = getComputedStyle(document.body, "::before");
    return {
      display: style.display,
      pointerEvents: style.pointerEvents,
      opacity: Number.parseFloat(style.opacity),
    };
  });
  assert(
    reflection.display === "block" &&
      reflection.pointerEvents === "none" &&
      reflection.opacity <= 0.22,
    "Wide-screen reflection pools are missing or too prominent",
  );
  await desktop.screenshot({
    path: "/tmp/mcp-mirror-home-1920.png",
    fullPage: true,
  });
  await desktop.setViewportSize({width: 1400, height: 1100});
  await desktop.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
  await desktop.locator("body").click({position: {x: 8, y: 400}});
  await desktop.locator(".site-header").screenshot({
    path: "/tmp/mcp-mirror-news-crawl-1400.png",
  });
  await desktop.screenshot({
    path: "/tmp/mcp-mirror-home-1400.png",
    fullPage: true,
  });
  await desktop.locator(".home-section-scores").screenshot({
    path: "/tmp/mcp-mirror-framework-support-1400.png",
  });
  await desktop
    .getByRole("searchbox", {name: "Search MCP capabilities"})
    .fill("hint");
  await desktop.locator(".feature-module.is-search-result").first().waitFor();
  await desktop.screenshot({
    path: "/tmp/mcp-mirror-search-modules-1400.png",
    fullPage: true,
  });
  await desktop
    .getByRole("searchbox", {name: "Search MCP capabilities"})
    .fill("");
  await desktop.goto(
    `${baseUrl}?spec=2025-11-25#/cap/destructive-hint`,
    {waitUntil: "networkidle"},
  );
  assert(
    (await desktop.getByLabel("MCP specification revision").inputValue()) ===
      "2025-11-25",
    "Legacy version-window test did not load the 2025 snapshot",
  );
  const desktopModule = desktop.locator(".feature-module.is-detail");
  const compactGeometry = await desktopModule.evaluate((module) => {
    const style = getComputedStyle(module);
    const moduleRect = module.getBoundingClientRect();
    const railRect = module.querySelector(".feature-action-rail").getBoundingClientRect();
    const tabs = [...module.querySelectorAll(".feature-tabs [role=tab]")].map(
      (tab) => tab.getBoundingClientRect().width,
    );
    return {
      width: moduleRect.width,
      height: moduleRect.height,
      radius: style.borderRadius,
      shadow: style.boxShadow,
      backgroundImage: style.backgroundImage,
      railOutside: railRect.right <= moduleRect.left + 1,
      tabWidths: tabs,
    };
  });
  assert(
    compactGeometry.height <= 520 &&
      compactGeometry.radius === "0px" &&
      compactGeometry.shadow === "none" &&
      compactGeometry.backgroundImage === "none" &&
      compactGeometry.railOutside &&
      new Set(compactGeometry.tabWidths.map(Math.round)).size > 1,
    `Desktop FeatureModule did not reach compact flat geometry: ${JSON.stringify(compactGeometry)}`,
  );
  const filteredCounts = await desktopModule
    .locator(".agent-column")
    .evaluateAll((columns) =>
      columns.map(
        (column) => column.querySelectorAll(".support-cell:not(.is-empty)").length,
      ),
    );
  assert(
    filteredCounts.every((count) => count <= 3),
    `Filtered view exceeds the previous/current/next window: ${filteredCounts.join(", ")}`,
  );
  await desktopModule.getByRole("radio", {name: "All"}).click();
  assert(
    (await desktopModule.locator(".support-cell:not(.is-empty)").count()) >
      filteredCounts.reduce((sum, count) => sum + count, 0),
    "All versions did not expand the filtered matrix",
  );
  await desktopModule.getByRole("radio", {name: "Filtered"}).click();
  assert(
    (await desktopModule.locator('[data-region="measurement-baseline"]').count()) === 1 &&
      (await desktopModule.locator(".feature-module-meta").count()) === 0 &&
      (await desktopModule.getByRole("tab", {name: /Resources, \d+/}).count()) === 1,
    "FeatureModule duplicates provenance or omits the Resources count",
  );
  const docsControl = desktopModule.getByRole("link", {
    name: "MCP Docs for destructiveHint",
  });
  const docsGeometry = await docsControl.evaluate((control) => {
    const outer = control.getBoundingClientRect();
    const label = control.querySelector("span").getBoundingClientRect();
    const title = control.closest(".feature-title-line").querySelector("h2").getBoundingClientRect();
    return {
      centerDelta: Math.abs(
        outer.top + outer.height / 2 - (title.top + title.height / 2),
      ),
      labelCenterDelta: Math.abs(
        label.left + label.width / 2 - (outer.left + outer.width / 2),
      ),
      documentIcons: control.querySelectorAll(".spec-link-document-icon").length,
      target: control.getAttribute("target"),
      rel: control.getAttribute("rel"),
    };
  });
  assert(
    docsGeometry.centerDelta <= 6 &&
      docsGeometry.labelCenterDelta <= 18 &&
      docsGeometry.documentIcons === 1 &&
      docsGeometry.target === "_blank" &&
      docsGeometry.rel.includes("noopener") &&
      (await docsControl.getAttribute("href")) ===
        legacyDatabase.data["destructive-hint"].docs_url,
    `Docs control geometry or semantics failed: ${JSON.stringify(docsGeometry)}`,
  );
  await desktop.screenshot({
    path: "/tmp/mcp-mirror-feature-module-1400.png",
    fullPage: true,
  });
  await desktop.setViewportSize({width: 1024, height: 900});
  await desktop.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
  await desktop
    .getByRole("searchbox", {name: "Search MCP capabilities"})
    .fill("");
  await desktop.screenshot({
    path: "/tmp/mcp-mirror-home-1024.png",
    fullPage: true,
  });
  await desktop.setViewportSize({width: 390, height: 844});
  await desktop.locator("body").click({position: {x: 4, y: 700}});
  await desktop.screenshot({
    path: "/tmp/mcp-mirror-home-390.png",
    fullPage: true,
  });
  await desktop
    .getByRole("searchbox", {name: "Search MCP capabilities"})
    .fill("hint");
  await desktop.locator(".feature-module.is-search-result").first().waitFor();
  await desktop.screenshot({
    path: "/tmp/mcp-mirror-search-modules-390.png",
    fullPage: true,
  });
  await desktop.close();

  assert(
    consoleErrors.length === 0,
    `Browser console errors: ${consoleErrors.join(" | ")}`,
  );
  console.log(
    `responsive smoke passed: ${widths.join(", ")}px across index, search, detail, stats, changes, and method`,
  );
} finally {
  await context.close();
  await browser.close();
  await new Promise((resolve, reject) => {
    server.httpServer.close((error) => (error ? reject(error) : resolve()));
  });
}
