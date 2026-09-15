import {
  Card,
  Link,
  ToggleButton,
  ToggleButtonGroup,
} from "@heroui/react";

import {CapabilityCard} from "../components/CapabilityCard";
import type {GridMode} from "../components/CapabilityGrid";
import {CapabilityTitle} from "../components/CapabilityText";
import {CopyCodeBlock} from "../components/CopyCodeBlock";
import {GridIcon, ListIcon} from "../components/Icons";
import {capabilityHref, currentSupport, isMeasured} from "../lib/data";
import type {Capability, MirrorDatabase, SupportCode} from "../types";

export type ResultsMode = "tables" | "list";

const EDITORIAL_POPULAR_IDS = [
  "destructive-hint",
  "read-only-hint",
  "required",
  "nested-objects",
  "enum",
] as const;

const MCP_FACTS = [
  {
    label: "MCP messages use JSON-RPC 2.0.",
    path: "basic",
  },
  {
    label: "Clients and servers negotiate a protocol revision during initialization.",
    path: "basic/lifecycle",
  },
  {
    label: "Servers can expose tools, resources, and reusable prompts.",
    path: "server",
  },
] as const;

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

  const capabilityById = new Map(
    capabilities.map((capability) => [capability.id, capability]),
  );
  const latestCapabilities = capabilities
    .filter(isMeasured)
    .sort(
      (left, right) =>
        (right.measured.run_date ?? "").localeCompare(
          left.measured.run_date ?? "",
        ) || left.title.localeCompare(right.title),
    )
    .slice(0, 5);
  const observedPopularity =
    database.popularity?.mode === "observed" ? database.popularity : undefined;
  const popularityWindow = observedPopularity?.windows.includes("week")
    ? "week"
    : observedPopularity?.windows[0];
  const observedCounts = new Map(
    (observedPopularity?.entries ?? []).map((entry) => [
      entry.capability_id,
      popularityWindow ? (entry.counts[popularityWindow]?.[0] ?? 0) : 0,
    ]),
  );
  const popularCapabilities = observedPopularity
    ? [...capabilities]
        .sort(
          (left, right) =>
            (observedCounts.get(right.id) ?? 0) -
              (observedCounts.get(left.id) ?? 0) ||
            left.title.localeCompare(right.title),
        )
        .slice(0, 5)
    : EDITORIAL_POPULAR_IDS.map((id) => capabilityById.get(id)).filter(
        (capability): capability is Capability => Boolean(capability),
      );
  const measuredFrameworkCount = Object.values(database.agents).filter(
    (agent) => (agent.measurement_status ?? "measured") === "measured",
  ).length;
  const incompatibleFrameworkCount = Object.values(database.agents).filter(
    (agent) => agent.measurement_status === "sdk_incompatible",
  ).length;
  const mismatchedFrameworkCount = Object.values(database.agents).filter(
    (agent) => agent.measurement_status === "protocol_mismatch",
  ).length;

  return (
    <main className="site-shell page-main index-home" id="main-content">
      <h1 className="sr-only">Can AI use MCP capabilities?</h1>
      <div className="home-sections">
        <section className="home-section home-section-scores">
          <h2>Frameworks</h2>
          <p className="home-section-intro">
            {database.coverage
              ? `${database.coverage.measured} of ${database.coverage.total} MCP ${database.mcp_spec} capabilities have measurements.`
              : `${capabilities.length} capabilities are catalogued for MCP ${database.mcp_spec}.`}{" "}
            {measuredFrameworkCount} of {Object.keys(database.agents).length} frameworks
            produced same-revision captures.
            {incompatibleFrameworkCount
              ? ` ${incompatibleFrameworkCount} cannot negotiate this revision.`
              : ""}
            {mismatchedFrameworkCount
              ? ` ${mismatchedFrameworkCount} negotiated another revision in the recorded run.`
              : ""}
          </p>
          <ol
            className="home-list home-framework-scores"
            data-version-kind="current_version"
          >
            {Object.entries(database.agents).map(([agentId, agent]) => {
              const counts: Record<SupportCode, number> = {
                y: 0,
                a: 0,
                n: 0,
                x: 0,
                u: 0,
              };
              capabilities.forEach((capability) => {
                counts[currentSupport(database, capability, agentId).code] += 1;
              });
              const total = capabilities.length || 1;
              return (
                <li
                  className="home-framework-score"
                  data-agent-id={agentId}
                  data-summary-version={agent.current_version}
                  key={agentId}
                  aria-label={`${agent.name} ${agent.current_version}`}
                >
                  <span className="home-framework-score-label">
                    {agent.name}{" "}
                    <strong className="framework-summary-version">
                      {agent.current_version}
                    </strong>
                  </span>
                  <span className="home-framework-score-bars" aria-hidden="true">
                    {(["y", "a", "n", "x", "u"] as const).map((code) =>
                      counts[code] ? (
                        <i
                          className={`home-score-segment support-${code}`}
                          key={code}
                          style={{width: `${(counts[code] / total) * 100}%`}}
                        />
                      ) : null,
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
          <Link className="home-score-note" href="#/stats?view=frameworks">
            Compare all frameworks
          </Link>
        </section>

        <section className="home-section home-section-new">
          <h2>New</h2>
          <ul className="home-list">
            {latestCapabilities.map((capability) => (
              <li data-capability-id={capability.id} key={capability.id}>
                <Link href={capabilityHref(capability.id)}>
                  <CapabilityTitle capability={capability} />
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="home-section home-section-popular">
          <h2>Popular</h2>
          <ul className="home-list">
            {popularCapabilities.map((capability) => (
              <li data-capability-id={capability.id} key={capability.id}>
                <Link href={capabilityHref(capability.id)}>
                  <CapabilityTitle capability={capability} />
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="home-section home-section-test">
          <h2>Test a capability</h2>
          <p>
            Scan your MCP server against the current framework adapters. The
            command runs locally and does not call a model.
          </p>
          <CopyCodeBlock
            className="home-command"
            value={`uvx mcp-mirror scan "python your_server.py" --spec-version ${database.mcp_spec}`}
          />
          <Link href="#/method">How measurements work</Link>
        </section>

        <section className="home-section home-section-dyk">
          <h2>MCP facts</h2>
          <ul className="home-list">
            {MCP_FACTS.map((fact) => (
              <li key={fact.path}>
                <Link
                  href={`https://modelcontextprotocol.io/specification/${database.mcp_spec}/${fact.path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {fact.label}
                </Link>
              </li>
            ))}
          </ul>
          <Link href="#/stats">Explore measured adapter behavior</Link>
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
              <Link
                href={`./data/data-${database.mcp_spec}.json`}
                target="_blank"
              >
                Published JSON data for MCP {database.mcp_spec}
              </Link>
            </li>
            <li>
              <Link href="#/stats">Filter and export measured support</Link>
            </li>
          </ul>
        </section>

        <section className="home-section home-section-how">
          <h2>How it works</h2>
          <div className="home-how-copy">
            <p>
              Can AI use compares the tool definition published by an MCP
              server with the shape each framework exposes at a documented
              capture boundary. That shows what stayed present, changed, or
              disappeared. The comparison does not call a model.
            </p>
            <p>
              Help extend the index.{" "}
              <Link
                href={`${database.repo || "https://github.com/"}/issues/new`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Suggest a capability
              </Link>
              , or{" "}
              <Link
                href={`${database.repo || "https://github.com/"}/blob/main/CONTRIBUTING.md`}
                target="_blank"
                rel="noopener noreferrer"
              >
                contribute a reproducible fixture and evidence.
              </Link>
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}
