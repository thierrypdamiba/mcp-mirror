export type SupportCode = "y" | "a" | "n" | "u";

export interface VersionEntry {
  version: string;
  release_date?: string;
  release_date_unix?: number | null;
  era: number;
}

export interface Agent {
  name: string;
  abbr: string;
  type: "python" | "typescript" | string;
  package: string;
  registry: "pypi" | "npm" | string;
  adapter: string;
  renderer: string;
  current_version: string;
  stable_version: string;
  dev_version: string | null;
  version_list: VersionEntry[];
}

export interface CapabilityExample {
  before_label?: string;
  before: string[];
  after_label?: string;
  after: string[];
}

export interface Capability {
  schema: string;
  id: string;
  title: string;
  description: string;
  question?: string;
  spec: string;
  spec_label?: string;
  docs_url?: string;
  docs_label?: string;
  status: string;
  categories?: string[];
  keywords?: string;
  stats: Record<string, Record<string, string>>;
  notes?: string;
  notes_by_num?: Record<string, string>;
  verdict: {
    code: SupportCode;
    headline: string;
    detail?: string;
  };
  usage_perc_y?: number | null;
  usage_perc_a?: number | null;
  usage_note?: string;
  links?: Array<{url: string; title: string}>;
  known_issues?: string[];
  example?: CapabilityExample;
  why: string;
  reproduce?: string;
  measured: {
    run_date: string;
    mcp_spec: string;
    fixture?: string;
  };
  shown?: boolean;
}

export interface MirrorDatabase {
  schema: string;
  updated: string;
  mcp_spec: string;
  repo?: string;
  eras: Record<string, string>;
  agents: Record<string, Agent>;
  statuses: Record<string, {short: string; label: string}>;
  support_codes: Record<SupportCode, string>;
  defaults: Record<string, string>;
  popularity?: {
    schema: string;
    mode: "mock" | "observed";
    generated_at: string;
    windows: string[];
    entries: Array<{
      capability_id: string;
      counts: Record<string, [number, number]>;
    }>;
  };
  cats: Record<string, string[]>;
  data: Record<string, Capability>;
}

declare global {
  interface Window {
    __MCP_MIRROR_DATA__?: MirrorDatabase;
  }
}

export interface ParsedSupport {
  code: SupportCode;
  noteRefs: number[];
}

export type Route =
  | {name: "index"}
  | {name: "capability"; capabilityId: string}
  | {name: "changes"}
  | {name: "compare"}
  | {name: "method"};
