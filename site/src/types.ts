export type SupportCode = "y" | "a" | "n" | "x" | "u";

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
  capture_boundary: {
    capture_api: string;
    capture_object: string;
    capture_stage:
      | "framework_tool_definition"
      | "provider_format"
      | "provider_request";
    provider_request_captured: boolean;
    negotiated_mcp_spec_version: string | null;
    protocol_version_evidence: string;
  };
  measurement_status?:
    | "measured"
    | "sdk_incompatible"
    | "protocol_mismatch";
  measurement_note?: string;
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
    // Null on a row the protocol defines but no scan has exercised yet.
    run_date: string | null;
    mcp_spec: string;
    fixture?: string | null;
  };
  shown?: boolean;
  /** Which part of the protocol this row belongs to, from the spec surface. */
  area?: string;
  measurement_state?: "measured" | "not_measured";
  /** What a scan would have to do to turn this row into a measurement. */
  probe?: string;
  /** The wire methods, notifications or fields the feature is carried by. */
  wire?: string[];
}

export interface CoverageArea {
  area: string;
  measured: number;
  total: number;
}

/** How much of the protocol revision we have measured, computed at build time. */
export interface Coverage {
  revision: string;
  catalogued: boolean;
  source: string;
  measured: number;
  total: number;
  by_area: CoverageArea[];
  note: string;
  omissions: string[];
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
  coverage?: Coverage | null;
  cats: Record<string, string[]>;
  data: Record<string, Capability>;
}

export interface SpecIndexEntry {
  id: string;
  label: string;
  file: string;
  updated: string;
  measured_frameworks: number;
  total_frameworks: number;
  coverage?: Coverage | null;
}

export interface SpecIndex {
  schema: string;
  default_spec: string;
  specs: SpecIndexEntry[];
}

declare global {
  interface Window {
    __MCP_MIRROR_DATA__?: MirrorDatabase;
    __MCP_MIRROR_DATASETS__?: Record<string, MirrorDatabase>;
    __MCP_MIRROR_SPEC_INDEX__?: SpecIndex;
  }
}

export interface ParsedSupport {
  code: SupportCode;
  noteRefs: number[];
}

export type Route =
  | {name: "index"}
  | {name: "capability"; capabilityId: string}
  | {name: "stats"}
  | {name: "changes"}
  | {name: "method"};
