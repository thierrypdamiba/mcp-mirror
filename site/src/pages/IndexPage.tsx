import {
  Button,
  Card,
  Label,
  Link,
  ListBox,
  Select,
  ToggleButton,
  ToggleButtonGroup,
} from "@heroui/react";
import {useState} from "react";

import {CapabilityCard} from "../components/CapabilityCard";
import {CapabilityTitle} from "../components/CapabilityText";
import type {GridMode} from "../components/CapabilityGrid";
import {FrameworkLogo} from "../components/FrameworkLogo";
import {ChevronRightIcon, GridIcon, ListIcon} from "../components/Icons";
import {
  capabilityHref,
  currentSupport,
  supportCounts,
} from "../lib/data";
import type {Capability, MirrorDatabase, SupportCode} from "../types";

export type ResultsMode = "tables" | "list";
type ExploreMode = "popular" | "trending" | "new";

const COMPACT_ROW_COUNT = 10;

function conciseDate(isoDate: string): string {
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${isoDate}T00:00:00Z`));
}

function measuredCounts(
  database: MirrorDatabase,
  capability: Capability,
): Record<SupportCode, number> & {measured: number} {
  const counts = supportCounts(database, capability);
  return {...counts, measured: counts.y + counts.a + counts.n};
}

interface CapabilityFact {
  capability: Capability;
  prefix: string;
  suffix: string;
}

function buildCapabilityFacts(
  database: MirrorDatabase,
  capabilities: Capability[],
): CapabilityFact[] {
  const measured = capabilities.map((capability) => {
    const counts = {y: 0, a: 0, n: 0, u: 0};
    Object.keys(database.agents).forEach((agentId) => {
      counts[currentSupport(database, capability, agentId).code] += 1;
    });
    return {
      capability,
      counts,
      measuredCount: counts.y + counts.a + counts.n,
    };
  });
  const byTitle = (
    left: (typeof measured)[number],
    right: (typeof measured)[number],
  ) =>
    left.capability.title.localeCompare(right.capability.title) ||
    left.capability.id.localeCompare(right.capability.id);
  const selected: typeof measured = [];
  const takeFirst = (
    predicate: (entry: (typeof measured)[number]) => boolean,
  ) => {
    const entry = measured
      .filter(
        (candidate) =>
          !selected.some(
            ({capability}) => capability.id === candidate.capability.id,
          ) && predicate(candidate),
      )
      .sort(byTitle)[0];
    if (entry) {
      selected.push(entry);
    }
  };

  // The first fact is the first annotation, alphabetically, with a measured
  // retained-vs-dropped split. The remaining selectors deliberately cover
  // distinct result shapes before falling back to title order.
  takeFirst(
    ({capability, counts}) =>
      capability.keywords?.toLowerCase().includes("annotations") === true &&
      counts.a > 0 &&
      counts.n > 0,
  );
  takeFirst(({counts, measuredCount}) => measuredCount > 0 && counts.y === measuredCount);
  takeFirst(({counts}) => counts.y > 0 && counts.n > 0);
  takeFirst(({counts, measuredCount}) => measuredCount > 0 && counts.n === measuredCount);
  takeFirst(({counts}) => counts.a > 0 && counts.y > 0);

  measured
    .filter(
      (entry) =>
        !selected.some(
          ({capability}) => capability.id === entry.capability.id,
        ),
    )
    .sort(byTitle)
    .forEach((entry) => {
      if (selected.length < 5) {
        selected.push(entry);
      }
    });

  return selected.map(({capability, counts, measuredCount}) => {
    if (counts.a > 0 && counts.n > 0) {
      return {
        capability,
        prefix: `Across ${measuredCount} current tested releases, `,
        suffix: ` is retained outside model input by ${counts.a} frameworks and dropped during adaptation by ${counts.n}.`,
      };
    }
    if (counts.y === measuredCount && measuredCount > 0) {
      return {
        capability,
        prefix: "Across current tested releases, ",
        suffix: ` is present in model input for all ${counts.y} measured frameworks.`,
      };
    }
    if (counts.n === measuredCount && measuredCount > 0) {
      return {
        capability,
        prefix: "Across current tested releases, ",
        suffix: ` is dropped during adaptation by all ${counts.n} measured frameworks.`,
      };
    }
    if (counts.y > 0 && counts.n > 0) {
      return {
        capability,
        prefix: `Across ${measuredCount} current tested releases, `,
        suffix: ` is present in model input for ${counts.y} frameworks and dropped by ${counts.n}.`,
      };
    }
    return {
      capability,
      prefix: `Across ${measuredCount} current tested releases, `,
      suffix: ` is present in model input for ${counts.y}, retained outside it by ${counts.a}, and dropped by ${counts.n}.`,
    };
  });
}

export function IndexPage({
  database,
  capabilities,
  query,
  resultsMode,
  onResultsModeChange,
  stars,
  onToggleStar,
  gridMode,
  onGridModeChange,
}: {
  database: MirrorDatabase;
  capabilities: Capability[];
  query: string;
  resultsMode: ResultsMode;
  onResultsModeChange: (mode: ResultsMode) => void;
  stars: string[];
  onToggleStar: (capabilityId: string) => void;
  gridMode: GridMode;
  onGridModeChange: (mode: GridMode) => void;
}) {
  const isSearching = Boolean(query.trim());
  const [factIndex, setFactIndex] = useState(0);
  const [exploreMode, setExploreMode] = useState<ExploreMode>("popular");
  const [exploreCadence, setExploreCadence] = useState("week");
  const [showAllCapabilities, setShowAllCapabilities] = useState(false);
  const [frameworkVersionMode, setFrameworkVersionMode] = useState<
    "stable_version" | "dev_version"
  >("stable_version");

  if (isSearching) {
    return (
      <main className="site-shell page-main" id="main-content">
        <div className="results-heading search-results-heading">
          <div>
            <p className="eyebrow">Search results</p>
            <h2>
              {capabilities.length
                ? `Matches for “${query.trim()}”`
                : "No matching capability"}
            </h2>
          </div>

          <ToggleButtonGroup
            aria-label="Search result layout"
            disallowEmptySelection
            selectionMode="single"
            selectedKeys={[resultsMode]}
            size="sm"
            onSelectionChange={(keys) => {
              const selected = Array.from(keys)[0];
              if (selected === "tables" || selected === "list") {
                onResultsModeChange(selected);
              }
            }}
          >
            <ToggleButton id="tables">
              <GridIcon width={16} height={16} />
              Tables
            </ToggleButton>
            <ToggleButton id="list">
              <ToggleButtonGroup.Separator />
              <ListIcon width={16} height={16} />
              List
            </ToggleButton>
          </ToggleButtonGroup>
        </div>

        {capabilities.length ? (
          <div
            className={
              resultsMode === "tables"
                ? "search-results-tables"
                : "capability-card-grid search-results-cards"
            }
          >
            {capabilities.map((capability) => (
              <CapabilityCard
                capability={capability}
                database={database}
                key={capability.id}
                presentation={resultsMode === "tables" ? "table" : "compact"}
                starred={stars.includes(capability.id)}
                onToggleStar={() => onToggleStar(capability.id)}
                gridMode={gridMode}
                onGridModeChange={onGridModeChange}
              />
            ))}
          </div>
        ) : (
          <Card className="empty-card" variant="secondary">
            <Card.Header>
              <Card.Title>Nothing measured under that name</Card.Title>
              <Card.Description>
                Try a schema term such as enum, required, format, nested, or an
                MCP annotation name.
              </Card.Description>
            </Card.Header>
          </Card>
        )}
      </main>
    );
  }

  const activityByCapability = new Map(
    (database.popularity?.entries ?? []).map((entry) => [
      entry.capability_id,
      entry,
    ]),
  );
  const trendLabels: Record<string, string> = {
    hour: "Past hour",
    day: "Today",
    week: "This week",
    month: "This month",
    quarter: "This quarter",
    year: "This year",
    all_time: "All time",
  };
  const byTitle = (left: Capability, right: Capability) =>
    left.title.localeCompare(right.title) || left.id.localeCompare(right.id);
  const exploredCapabilities = [...capabilities].sort((left, right) => {
    if (exploreMode === "new") {
      return (
        right.measured.run_date.localeCompare(left.measured.run_date) ||
        byTitle(left, right)
      );
    }
    const leftPair =
      activityByCapability.get(left.id)?.counts[exploreCadence] ?? [0, 0];
    const rightPair =
      activityByCapability.get(right.id)?.counts[exploreCadence] ?? [0, 0];
    if (exploreMode === "popular") {
      return rightPair[0] - leftPair[0] || byTitle(left, right);
    }
    const leftEligible = leftPair[0] >= 10;
    const rightEligible = rightPair[0] >= 10;
    const leftGrowth = leftEligible
      ? (leftPair[0] - leftPair[1]) / Math.max(leftPair[1], 1)
      : Number.NEGATIVE_INFINITY;
    const rightGrowth = rightEligible
      ? (rightPair[0] - rightPair[1]) / Math.max(rightPair[1], 1)
      : Number.NEGATIVE_INFINITY;
    return (
      Number(rightEligible) - Number(leftEligible) ||
      rightGrowth - leftGrowth ||
      rightPair[0] - leftPair[0] ||
      byTitle(left, right)
    );
  });
  const visibleCapabilities = showAllCapabilities
    ? exploredCapabilities
    : exploredCapabilities.slice(0, COMPACT_ROW_COUNT);
  const currentFrameworkCount = Object.keys(database.agents).length;
  const facts = buildCapabilityFacts(database, capabilities);
  const fact = facts[factIndex % Math.max(facts.length, 1)];

  return (
    <main className="site-shell page-main index-home" id="main-content">
      <h1 className="sr-only">MCP capability support</h1>
      <div className="home-sections">
        <section className="home-explore" aria-labelledby="explore-heading">
          <div className="home-explore-header">
            <div>
              <h2 id="explore-heading" tabIndex={-1}>Explore measured capabilities</h2>
              <p id="explore-mode-description">
                Popular and Trending order page and search activity, not
                fidelity or framework quality. New orders recently measured
                evidence by its published measurement date.
              </p>
            </div>
            <div className="explore-controls">
              <ToggleButtonGroup
                className="explore-mode-toggle"
                aria-label="Capability activity ordering"
                aria-describedby="explore-mode-description"
                disallowEmptySelection
                selectionMode="single"
                selectedKeys={[exploreMode]}
                size="sm"
                onSelectionChange={(keys) => {
                  const selected = Array.from(keys)[0];
                  if (
                    selected === "popular" ||
                    selected === "trending" ||
                    selected === "new"
                  ) {
                    setExploreMode(selected);
                    setShowAllCapabilities(false);
                  }
                }}
              >
                <ToggleButton id="popular">Popular</ToggleButton>
                <ToggleButtonGroup.Separator />
                <ToggleButton id="trending">Trending</ToggleButton>
                <ToggleButtonGroup.Separator />
                <ToggleButton id="new">New</ToggleButton>
              </ToggleButtonGroup>
              <Select
                aria-label="Activity cadence"
                className="explore-period-select"
                value={exploreCadence}
                onChange={(nextValue) => {
                  setExploreCadence(String(nextValue));
                  setShowAllCapabilities(false);
                }}
              >
                <Label className="sr-only">Activity cadence</Label>
                <Select.Trigger>
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {(database.popularity?.windows ?? []).map((period) => (
                      <ListBox.Item
                        id={period}
                        key={period}
                        textValue={trendLabels[period] ?? period}
                      >
                        {trendLabels[period] ?? period}
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
            </div>
          </div>

          <div className="home-evidence-table-wrap">
            <table className="home-evidence-table">
              <thead>
                <tr>
                  {[
                    "Capability",
                    "Source",
                    "Present",
                    "Retained",
                    "Dropped",
                    "Measured",
                  ].map((heading) => <th key={heading}>{heading}</th>)}
                </tr>
              </thead>
              <tbody aria-live="polite">
                {visibleCapabilities.map((capability) => {
                  const counts = measuredCounts(database, capability);
                  const docsUrl = capability.docs_url ?? capability.spec;
                  const docsLabel =
                    capability.docs_label ?? capability.spec_label ?? "Docs";
                  const metric = (
                    code: "y" | "a" | "n",
                    label: string,
                  ) => (
                    <td
                      className={`evidence-metric evidence-${code}`}
                      data-label={label}
                      aria-label={`${label.toLowerCase()} for ${counts[code]} of ${counts.measured} measured current framework releases`}
                    >
                      <strong>{counts[code]}</strong>
                      <span aria-hidden="true"> / {counts.measured}</span>
                    </td>
                  );
                  return (
                    <tr data-capability-id={capability.id} key={capability.id}>
                      <th data-label="Capability" scope="row">
                        <Link href={capabilityHref(capability.id)}>
                          <CapabilityTitle capability={capability} />
                          {stars.includes(capability.id) ? (
                            <span aria-label="Starred"> ★</span>
                          ) : null}
                        </Link>
                      </th>
                      <td className="evidence-source" data-label="Source">
                        <Link
                          href={docsUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`${docsLabel}, opens externally`}
                        >
                          {docsLabel}
                          <Link.Icon />
                        </Link>
                      </td>
                      {metric("y", "Present")}
                      {metric("a", "Retained")}
                      {metric("n", "Dropped")}
                      <td className="evidence-date" data-label="Measured">
                        <time dateTime={capability.measured.run_date}>
                          {conciseDate(capability.measured.run_date)}
                        </time>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <footer className="home-explore-footer">
            <div>
              <span>
                {capabilities.length} capabilities · {currentFrameworkCount} current
                framework releases
              </span>
              <small>Sample activity order until telemetry launches.</small>
            </div>
            {capabilities.length > COMPACT_ROW_COUNT ? (
              <Button
                className="explore-show-all"
                size="sm"
                variant="ghost"
                onPress={() => setShowAllCapabilities((current) => !current)}
              >
                {showAllCapabilities
                  ? "Show fewer capabilities"
                  : `Show all ${capabilities.length} capabilities`}
              </Button>
            ) : null}
          </footer>
        </section>

        <section
          className="home-section home-section-dyk"
          data-fact-count={facts.length}
        >
          <h2>Did you know?</h2>
          {fact ? (
            <p className="home-fact" data-capability-id={fact.capability.id}>
              {fact.prefix}
              <Link href={capabilityHref(fact.capability.id)}>
                <CapabilityTitle capability={fact.capability} />
              </Link>
              {fact.suffix}
            </p>
          ) : null}
          {facts.length > 1 ? (
            <Button
              className="home-next-fact"
              aria-label="Next fact"
              size="sm"
              variant="ghost"
              onPress={() =>
                setFactIndex((index) => (index + 1) % facts.length)
              }
            >
              <span>Next fact</span>
              <ChevronRightIcon width={14} height={14} />
            </Button>
          ) : null}
        </section>

        <section className="home-section home-section-tools">
          <h2>Tools</h2>
          <ul className="home-list">
            <li>
              <Link
                href={database.repo || "https://github.com/"}
                target="_blank"
                rel="noopener noreferrer"
              >
                mcp-mirror CLI, scan an MCP server locally
              </Link>
            </li>
            <li>
              <Link href="./data/data-1.0.json" target="_blank">
                Published JSON data feed
              </Link>
            </li>
          </ul>
        </section>

        <section className="home-section home-section-scores">
          <h2>Measured frameworks</h2>
          <ToggleButtonGroup
            className="home-version-toggle"
            aria-label="Framework version summary"
            disallowEmptySelection
            selectionMode="single"
            selectedKeys={[frameworkVersionMode]}
            size="sm"
            onSelectionChange={(keys) => {
              const selected = Array.from(keys)[0];
              if (selected === "stable_version" || selected === "dev_version") {
                setFrameworkVersionMode(selected);
              }
            }}
          >
            <ToggleButton id="stable_version">Current version</ToggleButton>
            <ToggleButtonGroup.Separator />
            <ToggleButton id="dev_version">Dev version</ToggleButton>
          </ToggleButtonGroup>
          <ol
            className="home-list home-framework-scores"
            data-version-kind={frameworkVersionMode}
          >
            {Object.entries(database.agents).map(([agentId, agent]) => {
              const version = agent[frameworkVersionMode];
              const visibleVersion = version ?? "Not tracked";
              return (
                <li
                  className="home-framework-score"
                  data-agent-id={agentId}
                  data-summary-version={version ?? ""}
                  key={agentId}
                  aria-label={`${agent.name} ${visibleVersion}`}
                >
                  <FrameworkLogo frameworkId={agentId} name={agent.name} />
                  <span className="home-framework-score-label">
                    <span>{agent.name}</span>
                    <strong className="framework-summary-version">
                      {visibleVersion}
                    </strong>
                  </span>
                </li>
              );
            })}
          </ol>
          <Link className="home-score-note" href="#/method">
            About these results
          </Link>
        </section>
      </div>
    </main>
  );
}
