import {Link} from "@heroui/react";
import {useMemo, useState} from "react";

import {CapabilityTitle} from "../components/CapabilityText";
import {writeClipboardText} from "../components/CopyCodeBlock";
import {
  SUPPORT_META,
  capabilityHref,
  matchesCapability,
  parseSupport,
} from "../lib/data";
import type {
  Capability,
  MirrorDatabase,
  SupportCode,
} from "../types";
import {FrameworkComparison} from "./ReferencePages";

type StatsView = "capabilities" | "frameworks";
type StatsSort = "name" | "newest" | "present" | "retained" | "dropped";

interface StatsState {
  view: StatsView;
  sort: StatsSort;
  query: string;
  framework: string;
  version: string;
  category: string;
  support: SupportCode | "all";
}

const DEFAULT_STATE: StatsState = {
  view: "capabilities",
  sort: "name",
  query: "",
  framework: "all",
  version: "current",
  category: "all",
  support: "all",
};

const SORT_OPTIONS: Array<{value: StatsSort; label: string}> = [
  {value: "name", label: "Name"},
  {value: "newest", label: "Newest measurement"},
  {value: "present", label: "Most present"},
  {value: "retained", label: "Most retained"},
  {value: "dropped", label: "Most dropped"},
];

const SUPPORT_OPTIONS: Array<{value: SupportCode | "all"; label: string}> = [
  {value: "all", label: "All support states"},
  {value: "y", label: "Present"},
  {value: "a", label: "Changed or retained"},
  {value: "n", label: "Dropped"},
  {value: "x", label: "Revision unreachable"},
  {value: "u", label: "Not yet measured"},
];

function statsStateFromHash(
  hash: string,
  database: MirrorDatabase,
): StatsState {
  const queryString = hash.includes("?") ? hash.split("?").slice(1).join("?") : "";
  const params = new URLSearchParams(queryString);
  const requestedFramework = params.get("framework") ?? "all";
  const framework = database.agents[requestedFramework]
    ? requestedFramework
    : "all";
  const agent = framework === "all" ? undefined : database.agents[framework];
  const requestedVersion = params.get("version") ?? "current";
  const version =
    requestedVersion === "current" ||
    agent?.version_list.some((entry) => entry.version === requestedVersion)
      ? requestedVersion
      : "current";
  const requestedSort = params.get("sort") ?? "name";
  const sort = SORT_OPTIONS.some(({value}) => value === requestedSort)
    ? (requestedSort as StatsSort)
    : "name";
  const requestedSupport = params.get("support") ?? "all";
  const support = SUPPORT_OPTIONS.some(({value}) => value === requestedSupport)
    ? (requestedSupport as SupportCode | "all")
    : "all";
  const requestedCategory = params.get("category") ?? "all";
  const category =
    requestedCategory === "all" ||
    Object.prototype.hasOwnProperty.call(database.cats, requestedCategory)
      ? requestedCategory
      : "all";

  return {
    view:
      hash.startsWith("#/compare") || params.get("view") === "frameworks"
        ? "frameworks"
        : "capabilities",
    sort,
    query: params.get("q") ?? "",
    framework,
    version,
    category,
    support,
  };
}

function statsHash(state: StatsState): string {
  const params = new URLSearchParams();
  if (state.view !== DEFAULT_STATE.view) params.set("view", state.view);
  if (state.sort !== DEFAULT_STATE.sort) params.set("sort", state.sort);
  if (state.query) params.set("q", state.query);
  if (state.framework !== DEFAULT_STATE.framework) {
    params.set("framework", state.framework);
  }
  if (state.version !== DEFAULT_STATE.version) params.set("version", state.version);
  if (state.category !== DEFAULT_STATE.category) {
    params.set("category", state.category);
  }
  if (state.support !== DEFAULT_STATE.support) params.set("support", state.support);
  const query = params.toString();
  return `#/stats${query ? `?${query}` : ""}`;
}

function conciseDate(isoDate: string): string {
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${isoDate.slice(0, 10)}T00:00:00Z`));
}

function csvValue(value: string | number): string {
  const stringValue = String(value);
  return /[",\n]/.test(stringValue)
    ? `"${stringValue.replaceAll('"', '""')}"`
    : stringValue;
}

function downloadData(
  contents: string,
  filename: string,
  type: string,
): void {
  const url = URL.createObjectURL(new Blob([contents], {type}));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function StatsPage({
  database,
  capabilities,
}: {
  database: MirrorDatabase;
  capabilities: Capability[];
}) {
  const [state, setState] = useState<StatsState>(() =>
    statsStateFromHash(window.location.hash, database),
  );
  const [shareStatus, setShareStatus] = useState("");
  const agentEntries = Object.entries(database.agents);
  const measuredFrameworkCount = agentEntries.filter(
    ([, agent]) => (agent.measurement_status ?? "measured") === "measured",
  ).length;

  const updateState = (patch: Partial<StatsState>) => {
    setState((current) => {
      const next = {...current, ...patch};
      window.history.replaceState(null, "", statsHash(next));
      return next;
    });
    setShareStatus("");
  };

  const selectedAgent =
    state.framework === "all" ? undefined : database.agents[state.framework];
  const versionOptions = selectedAgent
    ? Array.from(
        new Set([
          selectedAgent.current_version,
          ...selectedAgent.version_list.map(({version}) => version),
        ]),
      )
    : [];
  const versionByAgent = useMemo(
    () =>
      Object.fromEntries(
        agentEntries.map(([agentId, agent]) => [
          agentId,
          agentId === state.framework && state.version !== "current"
            ? state.version
            : agent.current_version,
        ]),
      ),
    [agentEntries, state.framework, state.version],
  );

  const rows = useMemo(() => {
    const supportCountsFor = (capability: Capability) => {
      const counts: Record<SupportCode, number> = {y: 0, a: 0, n: 0, x: 0, u: 0};
      agentEntries.forEach(([agentId]) => {
        const code = parseSupport(
          capability.stats[agentId]?.[versionByAgent[agentId]],
        ).code;
        counts[code] += 1;
      });
      return counts;
    };

    return capabilities
      .filter((capability) => matchesCapability(capability, state.query))
      .filter(
        (capability) =>
          state.category === "all" ||
          capability.categories?.includes(state.category),
      )
      .filter((capability) => {
        if (state.support === "all") return true;
        if (state.framework !== "all") {
          return (
            parseSupport(
              capability.stats[state.framework]?.[
                versionByAgent[state.framework]
              ],
            ).code === state.support
          );
        }
        return agentEntries.some(
          ([agentId]) =>
            parseSupport(
              capability.stats[agentId]?.[versionByAgent[agentId]],
            ).code === state.support,
        );
      })
      .map((capability) => ({
        capability,
        counts: supportCountsFor(capability),
      }))
      .sort((left, right) => {
        const byTitle =
          left.capability.title.localeCompare(right.capability.title) ||
          left.capability.id.localeCompare(right.capability.id);
        if (state.sort === "name") return byTitle;
        if (state.sort === "newest") {
          // Unmeasured rows have no run date and sort to the bottom rather than the top.
          return (
            (right.capability.measured.run_date ?? "").localeCompare(
              left.capability.measured.run_date ?? "",
            ) || byTitle
          );
        }
        const code =
          state.sort === "present"
            ? "y"
            : state.sort === "retained"
              ? "a"
              : "n";
        return right.counts[code] - left.counts[code] || byTitle;
      });
  }, [
    agentEntries,
    capabilities,
    state.category,
    state.framework,
    state.query,
    state.sort,
    state.support,
    versionByAgent,
  ]);

  const filteredCapabilities = rows.map(({capability}) => capability);
  const filtersActive =
    state.sort !== DEFAULT_STATE.sort ||
    state.query !== DEFAULT_STATE.query ||
    state.framework !== DEFAULT_STATE.framework ||
    state.version !== DEFAULT_STATE.version ||
    state.category !== DEFAULT_STATE.category ||
    state.support !== DEFAULT_STATE.support;

  const exportRows = () =>
    rows.map(({capability, counts}) => {
      const row: Record<string, string | number> = {
        id: capability.id,
        capability: capability.title.replaceAll("`", ""),
        categories: (capability.categories ?? []).join("|"),
        measured: capability.measured.run_date ?? "not yet measured",
        source: capability.docs_url ?? capability.spec,
      };
      agentEntries.forEach(([agentId, agent]) => {
        const code = parseSupport(
          capability.stats[agentId]?.[versionByAgent[agentId]],
        ).code;
        row[`${agent.name} ${versionByAgent[agentId]}`] =
          SUPPORT_META[code].shortLabel;
      });
      row.present = counts.y;
      row.retained = counts.a;
      row.dropped = counts.n;
      row.unmeasured = counts.u;
      return row;
    });

  const exportCsv = () => {
    const exportable = exportRows();
    const headers = exportable.length
      ? Object.keys(exportable[0])
      : [
          "id",
          "capability",
          "categories",
          "measured",
          "source",
          ...agentEntries.map(
            ([agentId, agent]) => `${agent.name} ${versionByAgent[agentId]}`,
          ),
          "present",
          "retained",
          "dropped",
          "unmeasured",
        ];
    const csv = [
      headers.map(csvValue).join(","),
      ...exportable.map((row) =>
        headers.map((header) => csvValue(row[header] ?? "")).join(","),
      ),
    ].join("\n");
    downloadData(
      csv,
      `can-ai-use-mcp-${database.mcp_spec}-stats-${database.updated.slice(0, 10)}.csv`,
      "text/csv;charset=utf-8",
    );
  };

  const exportJson = () => {
    downloadData(
      JSON.stringify(
        {
          schema: "mcp-mirror.stats-export.v1",
          source_updated: database.updated,
          mcp_spec: database.mcp_spec,
          filters: state,
          frameworks: Object.fromEntries(
            agentEntries.map(([agentId, agent]) => [
              agentId,
              {
                name: agent.name,
                version: versionByAgent[agentId],
              },
            ]),
          ),
          capabilities: exportRows(),
        },
        null,
        2,
      ),
      `can-ai-use-mcp-${database.mcp_spec}-stats-${database.updated.slice(0, 10)}.json`,
      "application/json",
    );
  };

  return (
    <main className="site-shell page-main stats-page" id="main-content">
      <header className="page-intro stats-page-intro">
        <p className="eyebrow">MCP {database.mcp_spec} snapshot</p>
        <h1>Stats</h1>
        <p>
          Inspect every capability against every tested framework release.
          {agentEntries.length - measuredFrameworkCount > 0
            ? ` ${measuredFrameworkCount} of ${agentEntries.length} frameworks produced same-protocol measurements; the others cannot negotiate this revision, so every one of their cells is unreachable rather than unmeasured. `
            : ` All ${agentEntries.length} frameworks produced same-protocol measurements. `}
          Counts are observations, not a composite framework ranking.
        </p>
      </header>

      <section className="stats-workbench" aria-label="Stats controls">
        <div className="stats-view-tabs" role="tablist" aria-label="Stats view">
          <button
            id="stats-tab-capabilities"
            type="button"
            role="tab"
            aria-controls="stats-panel-capabilities"
            aria-selected={state.view === "capabilities"}
            onClick={() => updateState({view: "capabilities"})}
          >
            Capabilities
            <span>{capabilities.length}</span>
          </button>
          <button
            id="stats-tab-frameworks"
            type="button"
            role="tab"
            aria-controls="stats-panel-frameworks"
            aria-selected={state.view === "frameworks"}
            onClick={() => updateState({view: "frameworks"})}
          >
            Frameworks
            <span>{agentEntries.length}</span>
          </button>
        </div>

        <form
          className="stats-filter-grid"
          aria-label="Filter statistics"
          onSubmit={(event) => event.preventDefault()}
        >
          <label>
            <span>Find capability</span>
            <input
              type="search"
              value={state.query}
              placeholder="enum, annotation, nested…"
              onChange={(event) => updateState({query: event.currentTarget.value})}
            />
          </label>
          <label>
            <span>Sort</span>
            <select
              value={state.sort}
              onChange={(event) =>
                updateState({sort: event.currentTarget.value as StatsSort})
              }
            >
              {SORT_OPTIONS.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Framework</span>
            <select
              value={state.framework}
              onChange={(event) =>
                updateState({
                  framework: event.currentTarget.value,
                  version: "current",
                })
              }
            >
              <option value="all">All frameworks</option>
              {agentEntries.map(([agentId, agent]) => (
                <option value={agentId} key={agentId}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Version</span>
            <select
              disabled={!selectedAgent}
              value={state.version}
              onChange={(event) =>
                updateState({version: event.currentTarget.value})
              }
            >
              {!selectedAgent ? (
                <option value="current">Current tested versions</option>
              ) : (
                <>
                  <option value="current">
                    Current ({selectedAgent.current_version})
                  </option>
                  {versionOptions
                    .filter((version) => version !== selectedAgent.current_version)
                    .map((version) => (
                      <option value={version} key={version}>
                        {version}
                      </option>
                    ))}
                </>
              )}
            </select>
          </label>
          <label>
            <span>Category</span>
            <select
              value={state.category}
              onChange={(event) =>
                updateState({category: event.currentTarget.value})
              }
            >
              <option value="all">All categories</option>
              {Object.keys(database.cats).map((category) => (
                <option value={category} key={category}>
                  {category}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Support state</span>
            <select
              value={state.support}
              onChange={(event) =>
                updateState({
                  support: event.currentTarget.value as SupportCode | "all",
                })
              }
            >
              {SUPPORT_OPTIONS.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </form>

        <div className="stats-action-row">
          <p aria-live="polite">
            <strong>{rows.length}</strong> of {capabilities.length} capabilities
            {" · "}
            {agentEntries.length} framework columns
          </p>
          <div className="stats-actions">
            <button
              type="button"
              disabled={!filtersActive}
              onClick={() =>
                updateState({...DEFAULT_STATE, view: state.view})
              }
            >
              Reset filters
            </button>
            <button
              type="button"
              onClick={() => {
                void writeClipboardText(window.location.href)
                  .then(() => setShareStatus("Link copied"))
                  .catch(() => setShareStatus("Copy unavailable"));
              }}
            >
              Copy view link
            </button>
            <button type="button" onClick={exportCsv}>Export CSV</button>
            <button type="button" onClick={exportJson}>Export JSON</button>
          </div>
          <span className="stats-share-status" role="status">
            {shareStatus}
          </span>
        </div>
      </section>

      {state.view === "capabilities" ? (
        <section
          id="stats-panel-capabilities"
          className="stats-panel"
          role="tabpanel"
          aria-labelledby="stats-tab-capabilities"
        >
          <div className="stats-matrix-wrap">
            <table className="stats-matrix">
              <thead>
                <tr>
                  <th scope="col">Capability</th>
                  {agentEntries.map(([agentId, agent]) => (
                    <th
                      scope="col"
                      data-focused={state.framework === agentId || undefined}
                      key={agentId}
                    >
                      <span>{agent.name}</span>
                      <small>{versionByAgent[agentId]}</small>
                    </th>
                  ))}
                  <th scope="col">Present</th>
                  <th scope="col">Retained</th>
                  <th scope="col">Dropped</th>
                </tr>
              </thead>
              <tbody>
                {rows.length ? (
                  rows.map(({capability, counts}) => {
                    const measured = counts.y + counts.a + counts.n;
                    return (
                      <tr data-capability-id={capability.id} key={capability.id}>
                        <th scope="row">
                          <Link href={capabilityHref(capability.id)}>
                            <CapabilityTitle capability={capability} />
                          </Link>
                          <small>
                            {(capability.categories ?? []).join(" · ") ||
                              "Uncategorized"}
                            {capability.measured.run_date ? (
                              <>
                                {" · measured "}
                                <time dateTime={capability.measured.run_date}>
                                  {conciseDate(capability.measured.run_date)}
                                </time>
                              </>
                            ) : (
                              " · not yet measured"
                            )}
                          </small>
                        </th>
                        {agentEntries.map(([agentId, agent]) => {
                          const version = versionByAgent[agentId];
                          const code = parseSupport(
                            capability.stats[agentId]?.[version],
                          ).code;
                          const meta = SUPPORT_META[code];
                          return (
                            <td
                              className="stats-framework-cell"
                              data-label={`${agent.abbr} ${version}`}
                              data-focused={
                                state.framework === agentId || undefined
                              }
                              key={agentId}
                            >
                              <span
                                className={`stats-support support-${code}`}
                                aria-label={`${agent.name} ${version}: ${meta.label}`}
                                title={meta.label}
                              >
                                <b aria-hidden="true">{meta.symbol}</b>
                                <span>{meta.shortLabel}</span>
                              </span>
                            </td>
                          );
                        })}
                        {(
                          [
                            ["y", "Present"],
                            ["a", "Retained"],
                            ["n", "Dropped"],
                          ] as const
                        ).map(([code, label]) => (
                          <td
                            className={`stats-total stats-total-${code}`}
                            data-label={label}
                            key={code}
                          >
                            <strong>{counts[code]}</strong>
                            <span aria-hidden="true"> / {measured}</span>
                          </td>
                        ))}
                      </tr>
                    );
                  })
                ) : (
                  <tr className="stats-empty-row">
                    <td colSpan={agentEntries.length + 4}>
                      No capabilities match these filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <section
          id="stats-panel-frameworks"
          className="stats-panel stats-framework-panel"
          role="tabpanel"
          aria-labelledby="stats-tab-frameworks"
        >
          <header className="stats-panel-intro">
            <div>
              <p className="eyebrow">Current filtered population</p>
              <h2>Compare frameworks</h2>
            </div>
            <p>
              Distribution of observed transformations across the filtered
              capabilities. This is not a “best framework” leaderboard.{" "}
              <Link href="#/method">Read the method.</Link>
            </p>
          </header>
          <FrameworkComparison
            database={database}
            capabilities={filteredCapabilities}
            versions={versionByAgent}
          />
        </section>
      )}
    </main>
  );
}
