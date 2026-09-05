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

  const match = raw.trim().match(/^([yanu])((?:\s+#\d+)*)$/);
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
  const counts: Record<SupportCode, number> = {y: 0, a: 0, n: 0, u: 0};
  for (const agentId of Object.keys(database.agents)) {
    counts[currentSupport(database, capability, agentId).code] += 1;
  }
  return counts;
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
  if (hash.startsWith("#/cap/")) {
    return {
      name: "capability",
      capabilityId: decodeURIComponent(hash.slice("#/cap/".length)),
    };
  }
  if (hash === "#/changes") {
    return {name: "changes"};
  }
  if (hash === "#/compare") {
    return {name: "compare"};
  }
  if (hash === "#/method") {
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
  const job = capability?.reproduce?.match(/--job\s+(\S+)/)?.[1];
  const jobArgument = job ? ` --job ${job}` : "";

  if (agent.registry === "npm") {
    return `npm i ${agent.package}@${version} && uvx mcp-mirror scan "python your_server.py" --frameworks ${agentId}${jobArgument}`;
  }
  return `uvx --with ${agent.package}==${version} mcp-mirror scan "python your_server.py" --frameworks ${agentId}${jobArgument}`;
}
