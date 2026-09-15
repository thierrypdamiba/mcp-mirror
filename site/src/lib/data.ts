import type {
  Agent,
  Capability,
  MirrorDatabase,
  ParsedSupport,
  Route,
  SupportCode,
} from "../types";

export const SUPPORT_META: Record<
  SupportCode,
  {label: string; shortLabel: string; symbol: string}
> = {
  y: {
    label: "Present at capture boundary",
    shortLabel: "Present",
    symbol: "✓",
  },
  a: {
    label: "Changed or retained elsewhere",
    shortLabel: "Changed/retained",
    symbol: "◐",
  },
  n: {
    label: "Dropped during adaptation",
    shortLabel: "Dropped",
    symbol: "×",
  },
  x: {
    label: "Adapter cannot negotiate this revision",
    shortLabel: "Unreachable",
    symbol: "⊘",
  },
  u: {
    label: "Not yet measured",
    shortLabel: "Unmeasured",
    symbol: "?",
  },
};

export function parseSupport(raw?: string): ParsedSupport {
  if (!raw) {
    return {code: "u", noteRefs: []};
  }

  const match = raw.trim().match(/^([yanxu])((?:\s+#\d+)*)$/);
  if (!match) {
    return {code: "u", noteRefs: []};
  }

  return {
    code: match[1] as SupportCode,
    noteRefs: (match[2].match(/#(\d+)/g) ?? []).map((value) =>
      Number(value.slice(1)),
    ),
  };
}

export function currentSupport(
  database: MirrorDatabase,
  capability: Capability,
  agentId: string,
): ParsedSupport {
  const agent = database.agents[agentId];
  return parseSupport(capability.stats[agentId]?.[agent.current_version]);
}

export function supportCounts(
  database: MirrorDatabase,
  capability: Capability,
): Record<SupportCode, number> {
  const counts: Record<SupportCode, number> = {y: 0, a: 0, n: 0, x: 0, u: 0};
  for (const agentId of Object.keys(database.agents)) {
    counts[currentSupport(database, capability, agentId).code] += 1;
  }
  return counts;
}

/**
 * A row backed by an actual adapter run. Rows the protocol defines but no scan has
 * exercised are published with every cell unmeasured, and they have no run date, so they
 * are excluded anywhere the page is reporting measurement history.
 */
export function isMeasured(capability: Capability): boolean {
  return (
    capability.measurement_state !== "not_measured" &&
    Boolean(capability.measured.run_date)
  );
}

export function shownCapabilities(database: MirrorDatabase): Capability[] {
  return Object.values(database.data)
    .filter((capability) => capability.shown !== false)
    .sort((left, right) => left.title.localeCompare(right.title));
}

export function matchesCapability(
  capability: Capability,
  rawQuery: string,
): boolean {
  const query = rawQuery.trim().toLowerCase();
  if (!query) {
    return true;
  }

  const haystack = [
    capability.title,
    capability.description,
    capability.question ?? "",
    capability.keywords ?? "",
    ...(capability.categories ?? []),
  ]
    .join(" ")
    .toLowerCase();

  return query
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term));
}

export function shortDate(iso?: string): string {
  return iso ? iso.slice(0, 10) : "Unknown";
}

export function measuredRelease(agent: Agent) {
  return (
    agent.version_list.find((version) => version.era === 0) ??
    agent.version_list.find((version) => version.version === agent.current_version)
  );
}

export function titleCaseRule(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

export function routeFromHash(hash: string): Route {
  const path = hash.split("?")[0];
  if (path.startsWith("#/cap/")) {
    return {
      name: "capability",
      capabilityId: decodeURIComponent(path.slice("#/cap/".length)),
    };
  }
  if (path === "#/stats" || path === "#/compare") {
    return {name: "stats"};
  }
  if (path === "#/changes") {
    return {name: "changes"};
  }
  if (path === "#/method") {
    return {name: "method"};
  }
  return {name: "index"};
}

export function capabilityHref(capabilityId: string): string {
  return `#/cap/${encodeURIComponent(capabilityId)}`;
}

export function reproduceCommand(
  agentId: string,
  agent: Agent,
  version: string,
  capability?: Capability,
): string {
  if (capability?.reproduce && !capability.reproduce.includes("mcp-mirror scan")) {
    return capability.reproduce;
  }
  const job = capability?.reproduce?.match(/--job\s+(\S+)/)?.[1];
  const jobArgument = job ? ` --job ${job}` : "";
  const specArgument = capability?.measured.mcp_spec
    ? ` --spec-version ${capability.measured.mcp_spec}`
    : "";

  if (agent.registry === "npm") {
    return `npm i ${agent.package}@${version} && uv run mcp-mirror scan "python3 your_server.py" --frameworks ${agentId}${jobArgument}${specArgument}`;
  }
  return `uv run --with ${agent.package}==${version} mcp-mirror scan "python3 your_server.py" --frameworks ${agentId}${jobArgument}${specArgument}`;
}
