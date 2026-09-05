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
  ["compare", "#/compare"],
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
    const shellStyle = await page.evaluate(() => {
      const body = getComputedStyle(document.body);
      const heading = document.querySelector(".search-hero h1");
      const accent = document.querySelector(".search-wordmark span");
      return {
        canvasColor: body.backgroundColor,
        backgroundImage: body.backgroundImage,
        bodyFont: body.fontFamily,
        headingFont: getComputedStyle(heading).fontFamily,
        accentColor: getComputedStyle(accent).color,
      };
    });
    assert(
      shellStyle.canvasColor === "rgb(250, 250, 249)" &&
        shellStyle.backgroundImage.includes("linear-gradient") &&
        shellStyle.bodyFont === shellStyle.headingFont &&
        shellStyle.accentColor === "rgb(0, 153, 101)",
      `${width}px: Context7 light shell tokens are incorrect: ${JSON.stringify(shellStyle)}`,
    );
    const headerGeometry = await page.evaluate(() => {
      const header = document.querySelector(".site-header");
      const main = document.querySelector(".header-main-row");
      const nav = document.querySelector(".site-nav");
      const ticker = document.querySelector(".news-ticker");
      const links = [...nav.querySelectorAll(".nav-link")];
      const tickerStyle = getComputedStyle(ticker);
      const headerStyle = getComputedStyle(header);
      const mainRect = main.getBoundingClientRect();
      const tickerRect = ticker.getBoundingClientRect();
      const compare = links[2];
      const compareWords = compare.querySelectorAll("span");
      const source = header.querySelector(".header-source");
      return {
        labels: links.map((link) => link.getAttribute("aria-label")),
        navCount: document.querySelectorAll(".site-header nav").length,
        active: links.map((link) => link.getAttribute("aria-current")),
        ordered: links.every(
          (link, index) =>
            index === 0 ||
            link.getBoundingClientRect().left >=
              links[index - 1].getBoundingClientRect().right,
        ),
        tickerAbove: tickerRect.bottom <= mainRect.top,
        background: tickerStyle.backgroundColor,
        border: tickerStyle.borderStyle,
        shadow: tickerStyle.boxShadow,
        radius: tickerStyle.borderRadius,
        fontFamilyMatches: tickerStyle.fontFamily === headerStyle.fontFamily,
        headerHeight: header.getBoundingClientRect().height,
        tickerTimeCount: ticker.querySelectorAll("time").length,
        tickerFontSize: tickerStyle.fontSize,
        headlineFontSize: getComputedStyle(
          ticker.querySelector(".news-ticker-link"),
        ).fontSize,
        sourceHref: source?.getAttribute("href"),
        compareText: compare.textContent.trim().replace(/\s+/g, " "),
        compareWordGap:
          compareWords.length === 2
            ? compareWords[1].getBoundingClientRect().left -
              compareWords[0].getBoundingClientRect().right
            : null,
      };
    });
    assert(
      JSON.stringify(headerGeometry.labels) ===
        JSON.stringify(["Home", "News", "Compare frameworks", "About"]) &&
        headerGeometry.navCount === 1 &&
        headerGeometry.active[0] === "page" &&
        headerGeometry.ordered &&
        headerGeometry.tickerAbove &&
        headerGeometry.background === "rgba(0, 0, 0, 0)" &&
        headerGeometry.border === "none" &&
        headerGeometry.shadow === "none" &&
        headerGeometry.radius === "0px" &&
        headerGeometry.fontFamilyMatches &&
        headerGeometry.tickerTimeCount === 0 &&
        Number.parseFloat(headerGeometry.tickerFontSize) >= 12 &&
        Number.parseFloat(headerGeometry.tickerFontSize) <= 13.5 &&
        Number.parseFloat(headerGeometry.headlineFontSize) >= 12 &&
        headerGeometry.sourceHref === database.repo &&
        headerGeometry.compareText ===
          (width <= 400 ? "Compare frameworks" : "Compare frameworks") &&
        (width < 768 ||
          (headerGeometry.compareWordGap !== null &&
            headerGeometry.compareWordGap >= 4)) &&
        Math.abs(headerGeometry.headerHeight - 86) <= 1,
      `${width}px: header hierarchy or ticker integration is incorrect`,
    );
    const heroGeometry = await page.evaluate(() => {
      const heading = document.querySelector(".search-hero h1");
      const copy = document.querySelector(".hero-copy").getBoundingClientRect();
      const field = document.querySelector(".capability-search-wrap").getBoundingClientRect();
      const inputGroup = document.querySelector(".search-field__group").getBoundingClientRect();
      return {
        heading: heading.textContent.trim().replace(/\s+/g, " "),
        detail: document.querySelector(".hero-copy").textContent.trim().replace(/\s+/g, " "),
        fieldGap: field.top - copy.bottom,
        fieldWidth: field.width,
        fieldHeight: inputGroup.height,
      };
    });
    assert(
      heroGeometry.heading ===
        "MCP capability support across agent frameworks" &&
        heroGeometry.detail ===
          "Search a tool-definition capability to see whether each framework preserves it across exact tested versions." &&
        heroGeometry.fieldGap >= 20 &&
        heroGeometry.fieldWidth <= 500 &&
        Math.abs(heroGeometry.fieldHeight - 44) <= 1,
      `${width}px: capability-first hero geometry is incorrect: ${JSON.stringify(heroGeometry)}`,
    );
    const rows = await page
      .locator(
        '.home-framework-scores[data-version-kind="stable_version"] .home-framework-score',
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
      rows.length === Object.keys(database.agents).length,
      `${width}px: framework summary rendered ${rows.length} rows`,
    );
    rows.forEach(({agentId, version, visibleVersion}) => {
      const expected = database.agents[agentId]?.stable_version;
      assert(expected, `${width}px: unknown framework summary row ${agentId}`);
      assert(
        version === expected && visibleVersion === expected,
        `${width}px: ${agentId} summary showed ${visibleVersion || "<empty>"}; expected ${expected}`,
      );
    });
    assert(
      (await page.getByText("Current tested version", {exact: true}).count()) === 0 &&
        (await page.getByRole("heading", {name: "Measured frameworks"}).count()) === 1 &&
        (await page.getByRole("radio", {name: "Current version"}).count()) === 1 &&
        (await page.getByRole("radio", {name: "Dev version"}).count()) === 1 &&
        (await page.locator(".home-framework-scores").count()) === 1,
      `${width}px: framework summaries retained obsolete version labeling`,
    );
    const currentToggle = page.getByRole("radio", {name: "Current version"});
    const devToggle = page.getByRole("radio", {name: "Dev version"});
    assert(await currentToggle.isChecked(), `${width}px: Current version is not the default`);
    await devToggle.focus();
    await devToggle.press("Space");
    const devVersions = await page.locator(".framework-summary-version").allTextContents();
    assert(
      devVersions.length === Object.keys(database.agents).length &&
        devVersions.every((value) => value.trim() === "Not tracked") &&
        (await page.locator('.home-framework-scores[data-version-kind="dev_version"]').count()) === 1,
      `${width}px: unverified dev versions were invented`,
    );
    await currentToggle.click();
    const versionToggleGeometry = await page
      .locator(".home-section-scores")
      .evaluate((section) => {
        const group = section.querySelector(".home-version-toggle");
        const heading = section.querySelector("h2");
        const buttons = [...group.querySelectorAll('[role="radio"]')];
        const horizontalInsets = buttons.map((button) => {
          const outer = button.getBoundingClientRect();
          const range = document.createRange();
          range.selectNodeContents(button);
          const inner = range.getBoundingClientRect();
          return Math.min(
            inner.left - outer.left,
            outer.right - inner.right,
          );
        });
        const firstRow = group.nextElementSibling?.querySelector("li");
        const groupRect = group.getBoundingClientRect();
        const headingRect = heading.getBoundingClientRect();
        const sectionRect = section.getBoundingClientRect();
        const headingStyles = [
          section.closest(".home-sections").querySelector(".home-section-dyk h2"),
          section.closest(".home-sections").querySelector(".home-section-tools h2"),
          heading,
        ].map((element) => {
          const style = getComputedStyle(element);
          return {
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            lineHeight: style.lineHeight,
          };
        });
        return {
          minimumHorizontalInset: Math.min(...horizontalInsets),
          buttonHeights: buttons.map(
            (button) => button.getBoundingClientRect().height,
          ),
          groupWidth: groupRect.width,
          sectionWidth: sectionRect.width,
          headingGap: groupRect.top - headingRect.bottom,
          rowGap: firstRow
            ? firstRow.getBoundingClientRect().top -
              groupRect.bottom
            : -1,
          headingStyles,
        };
      });
    assert(
      versionToggleGeometry.minimumHorizontalInset >= 10 &&
        versionToggleGeometry.buttonHeights.every(
          (height) => height >= 32 && height <= 36,
        ) &&
        versionToggleGeometry.groupWidth <= versionToggleGeometry.sectionWidth &&
        versionToggleGeometry.headingGap >= 0 &&
        versionToggleGeometry.headingGap <= 4 &&
        versionToggleGeometry.rowGap >= 10 &&
        versionToggleGeometry.rowGap <= 14 &&
        versionToggleGeometry.headingStyles.every(
          (style) =>
            JSON.stringify(style) ===
            JSON.stringify(versionToggleGeometry.headingStyles[0]),
        ),
      `${width}px: framework heading or compact toggle geometry is incorrect: ${JSON.stringify(versionToggleGeometry)}`,
    );
    assert(
      (await page.locator(".home-framework-score .framework-logo").count()) ===
        Object.keys(database.agents).length &&
        (await page.locator(".home-framework-score-bars").count()) === 0,
      `${width}px: Measured frameworks did not replace support bars with identity rows`,
    );
    const evidenceTable = page.locator(".home-evidence-table");
    const evidenceHeaders = await evidenceTable.locator("thead th").allTextContents();
    assert(
      JSON.stringify(evidenceHeaders.map((value) => value.trim())) ===
        JSON.stringify(["Capability", "Source", "Present", "Retained", "Dropped", "Measured"]),
      `${width}px: evidence table headers are incorrect`,
    );
    assert(
      (await evidenceTable.locator("tbody tr").count()) === 10 &&
        (await page.getByText("Sample activity order until telemetry launches.", {exact: true}).count()) === 1 &&
        !(await evidenceTable.textContent()).includes("%"),
      `${width}px: compact evidence rows or activity disclosure are incorrect`,
    );
    const firstEvidenceRow = evidenceTable.locator("tbody tr").first();
    const firstCapabilityId = await firstEvidenceRow.getAttribute("data-capability-id");
    const firstCapability = database.data[firstCapabilityId];
    const supportCodes = Object.entries(database.agents).map(([agentId, agent]) =>
      (firstCapability.stats[agentId]?.[agent.current_version] ?? "u").trim()[0],
    );
    const measured = supportCodes.filter((code) => code !== "u").length;
    for (const [cellIndex, code] of [["3", "y"], ["4", "a"], ["5", "n"]]) {
      const expected = `${supportCodes.filter((value) => value === code).length} / ${measured}`;
      assert(
        (await firstEvidenceRow.locator(`td:nth-child(${cellIndex})`).textContent()).trim() === expected,
        `${width}px: evidence count ${code} is not deterministic`,
      );
    }
    assert(
      (await firstEvidenceRow.locator(".evidence-source a").getAttribute("href")) ===
        (firstCapability.docs_url ?? firstCapability.spec) &&
        (await firstEvidenceRow.locator("time").getAttribute("datetime")) ===
          firstCapability.measured.run_date,
      `${width}px: evidence source or measured time metadata is incorrect`,
    );
    if (width === 1024) {
      const popular = page.getByRole("radio", {name: "Popular"});
      const trending = page.getByRole("radio", {name: "Trending"});
      const newest = page.getByRole("radio", {name: "New"});
      const cadence = page.getByRole("button", {name: "Activity cadence"});
      const controlsGeometry = await page.evaluate(() => {
        const modes = [...document.querySelectorAll(".explore-mode-toggle [role=radio]")];
        const cadence = document.querySelector(".explore-period-select");
        const cadenceRect = cadence.getBoundingClientRect();
        return {
          groupCount: document.querySelectorAll(".explore-controls .explore-mode-toggle").length,
          modeCount: modes.length,
          cadenceCount: document.querySelectorAll(".explore-period-select").length,
          aligned: modes.every((mode) => {
            const rect = mode.getBoundingClientRect();
            return Math.abs(rect.top - cadenceRect.top) <= 2 &&
              Math.abs(rect.bottom - cadenceRect.bottom) <= 2;
          }),
        };
      });
      assert(
        await popular.isChecked() &&
          controlsGeometry.groupCount === 1 &&
          controlsGeometry.modeCount === 3 &&
          controlsGeometry.cadenceCount === 1 &&
          controlsGeometry.aligned,
        `Explore controls are not one three-mode group plus one cadence: ${JSON.stringify(controlsGeometry)}`,
      );
      const popularWeekFirst = await firstEvidenceRow.getAttribute("data-capability-id");
      await cadence.click();
      await page.locator('[role="option"]').filter({hasText: "All time"}).first().click();
      const popularAllFirst = await evidenceTable.locator("tbody tr").first().getAttribute("data-capability-id");
      assert(popularAllFirst !== popularWeekFirst, "Popular period did not change ordering");
      await trending.click();
      const trendingAllFirst = await evidenceTable.locator("tbody tr").first().getAttribute("data-capability-id");
      await cadence.click();
      await page.locator('[role="option"]').filter({hasText: "Today"}).first().click();
      const trendingDayFirst = await evidenceTable.locator("tbody tr").first().getAttribute("data-capability-id");
      assert(
        trendingDayFirst !== trendingAllFirst &&
          (await cadence.textContent()).includes("Today"),
        "Shared cadence did not update Trending ordering",
      );
      await newest.click();
      const newIds = await evidenceTable.locator("tbody tr").evaluateAll((rows) =>
        rows.map((row) => row.getAttribute("data-capability-id")),
      );
      const expectedNewIds = Object.values(database.data)
        .sort(
          (left, right) =>
            right.measured.run_date.localeCompare(left.measured.run_date) ||
            left.title.localeCompare(right.title) ||
            left.id.localeCompare(right.id),
        )
        .slice(0, 10)
        .map((capability) => capability.id);
      assert(
        JSON.stringify(newIds) === JSON.stringify(expectedNewIds),
        "New mode is not ordered by factual measurement date and stable title ties",
      );
      await page.getByRole("button", {name: `Show all ${Object.keys(database.data).length} capabilities`}).click();
      assert(
        (await evidenceTable.locator("tbody tr").count()) === Object.keys(database.data).length,
        "Show all capabilities did not expand the evidence table",
      );
      await cadence.click();
      await page.locator('[role="option"]').filter({hasText: "This week"}).first().click();
      assert(
        (await evidenceTable.locator("tbody tr").count()) === 10,
        "Changing cadence did not collapse expanded evidence rows",
      );
    }
    const stripGeometry = await page.locator(".feature-strip > *").evaluateAll(
      (elements) =>
        elements.map((element) => {
          const rect = element.getBoundingClientRect();
          const content = element.querySelector("svg")?.parentElement ?? element;
          const contentRect = content.getBoundingClientRect();
          return {
            width: rect.width,
            height: rect.height,
            centerX: rect.x + rect.width / 2,
            centerY: rect.y + rect.height / 2,
            contentCenterX: contentRect.x + contentRect.width / 2,
          };
        }),
    );
    assert(
      stripGeometry.length === 2 &&
        Math.abs(stripGeometry[0].height - stripGeometry[1].height) <= 1 &&
        Math.abs(stripGeometry[0].centerY - stripGeometry[1].centerY) <= 1 &&
        Math.abs(stripGeometry[1].contentCenterX - stripGeometry[1].centerX) <= 1 &&
        (width !== 1024 || stripGeometry[1].width < stripGeometry[0].width),
      `${width}px: index/filter controls are not geometrically aligned`,
    );
    if (width === 390 || width === 1024) {
      const factRect = await page.locator(".home-fact").boundingBox();
      const nextRect = await page
        .getByRole("button", {name: "Next fact"})
        .boundingBox();
      const gap =
        factRect && nextRect ? nextRect.y - (factRect.y + factRect.height) : -1;
      assert(
        gap >= 4 && gap <= 8,
        `${width}px: Next fact gap is ${gap}px instead of 4–8px`,
      );
    }
    if (width === 1024) {
      assert(
        (await page.locator(".home-section").count()) === 3 &&
          (await page.locator(".home-explore").count()) === 1,
        "Homepage does not contain one evidence module and three lower sections",
      );
      assert(
        (await page.getByRole("heading", {name: "Capability groups"}).count()) ===
          0,
        "Capability groups leaked out of the index/filter UI",
      );
      const firstFact = page.locator(".home-fact");
      assert(
        (await firstFact.getAttribute("data-capability-id")) ===
          "destructive-hint",
        "First deterministic fact is not the annotation retained-vs-dropped split",
      );
      assert(
        (await firstFact.textContent()).includes("2 frameworks") &&
          (await firstFact.textContent()).includes("dropped during adaptation by 3"),
        "First fact does not reflect current destructiveHint counts",
      );
      const factSection = page.locator(".home-section-dyk");
      assert(
        (await factSection.getAttribute("data-fact-count")) === "5",
        "Homepage did not build the expected five distinct data-derived facts",
      );
      const nextFact = factSection.getByRole("button", {name: "Next fact"});
      assert((await nextFact.count()) === 1, "Next fact control is missing");
      const initialFactId = await firstFact.getAttribute("data-capability-id");
      await nextFact.click();
      assert(
        (await firstFact.getAttribute("data-capability-id")) !== initialFactId,
        "Next fact control did not visibly cycle to a distinct fact",
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
        assert(
          (await module.locator(".feature-test-controls select").count()) === 2 &&
            (await module.getByRole("button", {name: "Copy command"}).count()) === 1,
          `Search FeatureModule ${index + 1} Test a feature panel is not functional`,
        );
      }
      const destructiveSearchModule = page.locator(
        '.feature-module.is-search-result[data-capability-id="destructive-hint"]',
      );
      assert(
        JSON.stringify(
          (await destructiveSearchModule
            .locator('.support-cell[data-current="true"] .support-note-ref')
            .allTextContents()).map((value) => value.trim()),
        ) === JSON.stringify(["#1", "#2", "#3", "#4", "#5"]),
        "Search-result FeatureModule note markers are not in reading order",
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
      .locator('.support-cell[data-agent-id="crewai"][data-version="1.14.7"]')
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
          element.classList.contains("support-n")
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
      const expectedNotes = Object.entries(database.agents).map(
        ([, agent], index) => ({
          number: index + 1,
          label: `${agent.name} ${agent.current_version}`,
        }),
      );
      const visibleRefs = await page
        .locator('.support-cell[data-current="true"] .support-note-ref')
        .allTextContents();
      assert(
        JSON.stringify(visibleRefs.map((value) => value.trim())) ===
          JSON.stringify(["#1", "#2", "#3", "#4", "#5"]),
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
          '.support-cell[data-agent-id="crewai"][data-version="1.14.7"]',
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
  await assertNoHorizontalOverflow(desktop, "1920px light desktop");
  const reflection = await desktop.evaluate(() => {
    const style = getComputedStyle(document.body, "::before");
    return {
      display: style.display,
      pointerEvents: style.pointerEvents,
      opacity: Number.parseFloat(style.opacity),
    };
  });
  assert(
    reflection.display === "none",
    "Legacy side reflection pools remain visible",
  );
  await desktop.screenshot({
    path: "/tmp/mcp-mirror-home-1920.png",
    fullPage: true,
  });
  await desktop.setViewportSize({width: 1400, height: 1100});
  await desktop.goto(`${baseUrl}#/`, {waitUntil: "networkidle"});
  await desktop.locator("body").click({position: {x: 8, y: 400}});
  const secondaryHeights = await desktop.evaluate(() => {
    const height = (selector) =>
      document.querySelector(selector).getBoundingClientRect().height;
    return {
      fact: height(".home-section-dyk"),
      tools: height(".home-section-tools"),
      frameworks: height(".home-section-scores"),
    };
  });
  assert(
    secondaryHeights.fact < secondaryHeights.frameworks &&
      secondaryHeights.tools < secondaryHeights.frameworks &&
      secondaryHeights.fact <= 170 &&
      secondaryHeights.tools <= 170,
    `Secondary homepage panels remain stretched: ${JSON.stringify(secondaryHeights)}`,
  );
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
  await desktop.goto(`${baseUrl}#/cap/destructive-hint`, {waitUntil: "networkidle"});
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
    compactGeometry.height <= 540 &&
      compactGeometry.radius === "8px" &&
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
        database.data["destructive-hint"].docs_url,
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
    `responsive smoke passed: ${widths.join(", ")}px across index, search, detail, compare, changes, and method`,
  );
} finally {
  await context.close();
  await browser.close();
  await new Promise((resolve, reject) => {
    server.httpServer.close((error) => (error ? reject(error) : resolve()));
  });
}
