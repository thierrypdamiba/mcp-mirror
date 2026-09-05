import {
  Button,
  Link,
  Tabs,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
} from "@heroui/react";
import {useEffect, useId, useMemo, useState} from "react";

import {
  capabilityHref,
  parseSupport,
  reproduceCommand,
  shortDate,
  supportCounts,
} from "../lib/data";
import type {Capability, MirrorDatabase, SupportCode} from "../types";
import {CapabilityGrid, type GridMode} from "./CapabilityGrid";
import {CapabilityTitle, DocsLink, InlineCode} from "./CapabilityText";
import {CopyCodeBlock, writeClipboardText} from "./CopyCodeBlock";
import {GitHubIcon, StarIcon} from "./Icons";

type DetailKey = "notes" | "test" | "issues" | "resources" | "feedback";

function baselineHeadline(counts: Record<SupportCode, number>) {
  const observedKinds = (["y", "a", "n"] as SupportCode[]).filter(
    (code) => counts[code] > 0,
  );
  if (observedKinds.length > 1) return "Mixed handling across tested releases";
  if (counts.y) return "Present across tested releases";
  if (counts.a) return "Retained outside model input";
  if (counts.n) return "Dropped across tested releases";
  return "Not yet measured";
}

function focusNote(prefix: string, note: number) {
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      const target = document.getElementById(`${prefix}-note-${note}`);
      target?.focus({preventScroll: true});
      target?.scrollIntoView({behavior: "smooth", block: "nearest"});
    });
  });
}

function ExampleComparison({capability}: {capability: Capability}) {
  if (!capability.example) return null;
  return (
    <div className="feature-example-comparison">
      <section>
        <h4>{capability.example.before_label ?? "Server publishes"}</h4>
        <CopyCodeBlock value={capability.example.before.join("\n")} />
      </section>
      <section>
        <h4>{capability.example.after_label ?? "Adapter produces"}</h4>
        <CopyCodeBlock value={capability.example.after.join("\n")} />
      </section>
    </div>
  );
}

function TestPanel({
  database,
  capability,
}: {
  database: MirrorDatabase;
  capability: Capability;
}) {
  const entries = Object.entries(database.agents);
  const [agentId, setAgentId] = useState(entries[0]?.[0] ?? "");
  const agent = database.agents[agentId];
  const testedVersion =
    agent?.version_list.find((entry) => entry.era === 0)?.version ??
    agent?.current_version ??
    "";
  const [version, setVersion] = useState(testedVersion);

  useEffect(() => setVersion(testedVersion), [agentId, testedVersion]);

  return (
    <div className="feature-test-panel">
      <p>
        Reproduce this adapter comparison locally. No model call or model API
        key is required.
      </p>
      <div className="feature-test-controls">
        <label>
          Framework
          <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
            {entries.map(([id, candidate]) => (
              <option value={id} key={id}>{candidate.name}</option>
            ))}
          </select>
        </label>
        <label>
          Version
          <select value={version} onChange={(event) => setVersion(event.target.value)}>
            {agent?.version_list.map((entry) => (
              <option value={entry.version} key={entry.version}>
                {entry.version}{entry.era === 0 ? " (tested)" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      <CopyCodeBlock
        className="command-box"
        value={
          agent ? reproduceCommand(agentId, agent, version, capability) : ""
        }
      />
    </div>
  );
}

export function FeatureModule({
  database,
  capability,
  starred,
  onToggleStar,
  gridMode,
  onGridModeChange,
  detail = false,
}: {
  database: MirrorDatabase;
  capability: Capability;
  starred: boolean;
  onToggleStar: () => void;
  gridMode: GridMode;
  onGridModeChange: (mode: GridMode) => void;
  detail?: boolean;
}) {
  const reactId = useId().replace(/:/g, "");
  const scope = `feature-${capability.id}-${reactId}`;
  const [selectedDetail, setSelectedDetail] = useState<DetailKey>("notes");
  const [showAllVersions, setShowAllVersions] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const counts = supportCounts(database, capability);
  const frameworkCount = Object.keys(database.agents).length;
  const notes = Object.entries(capability.notes_by_num ?? {}).sort(
    ([left], [right]) => Number(left) - Number(right),
  );
  const noteReferences = useMemo(() => {
    const references = new Map<number, string[]>();
    Object.entries(database.agents).forEach(([agentId, agent]) => {
      agent.version_list.forEach(({version}) => {
        parseSupport(capability.stats[agentId]?.[version]).noteRefs.forEach(
          (note) => {
            const labels = references.get(note) ?? [];
            labels.push(`${agent.name} ${version}`);
            references.set(note, labels);
          },
        );
      });
    });
    return references;
  }, [capability, database.agents]);
  const issues = capability.known_issues ?? [];
  const resources = capability.links ?? [];
  const issueUrl = useMemo(
    () =>
      `${database.repo || "https://github.com/"}${"/issues/new?title="}${encodeURIComponent(
        `Correction: ${capability.title.replaceAll("`", "")}`,
      )}`,
    [database.repo, capability.title],
  );

  const activateNote = (note: number) => {
    setSelectedDetail("notes");
    focusNote(scope, note);
  };

  const permalink = () => {
    const url = `${window.location.href.split("#")[0]}${capabilityHref(capability.id)}`;
    void writeClipboardText(url).then(() => {
      setLinkCopied(true);
      window.setTimeout(() => setLinkCopied(false), 1600);
    });
  };

  return (
    <article
      className={`feature-module${detail ? " is-detail" : " is-search-result"}`}
      data-capability-id={capability.id}
      aria-labelledby={`${scope}-title`}
    >
      <aside className="feature-action-rail" aria-label="Capability actions">
        <Tooltip delay={250}>
          <Tooltip.Trigger>
            <Button
              aria-label="Copy a link to this capability"
              isIconOnly
              size="sm"
              variant="ghost"
              onPress={permalink}
            >
              <span className="permalink-symbol" aria-hidden="true">#</span>
            </Button>
          </Tooltip.Trigger>
          <Tooltip.Content>{linkCopied ? "Link copied" : "Copy link"}</Tooltip.Content>
        </Tooltip>
        <Button
          aria-label={starred ? "Remove star" : "Star this capability"}
          isIconOnly
          size="sm"
          variant="ghost"
          onPress={onToggleStar}
        >
          <StarIcon filled={starred} />
        </Button>
      </aside>

      <div className="feature-module-main">
        <header className="feature-module-header">
          <div className="feature-heading-copy">
            <div className="feature-title-line">
              <h2 id={`${scope}-title`}>
                {detail ? (
                  <CapabilityTitle capability={capability} />
                ) : (
                  <Link href={capabilityHref(capability.id)}>
                    <CapabilityTitle capability={capability} />
                  </Link>
                )}
              </h2>
              <DocsLink capability={capability} />
            </div>
            <section
              className="measurement-baseline"
              aria-label="Measurement baseline"
              data-region="measurement-baseline"
            >
              <strong>{baselineHeadline(counts)}</strong>
              <span>
                MCP {capability.measured.mcp_spec} · tested{" "}
                <time dateTime={capability.measured.run_date}>
                  {shortDate(capability.measured.run_date)}
                </time>{" "}
                · {frameworkCount} releases ·{" "}
                <code>{capability.measured.fixture ?? "custom fixture"}</code>
              </span>
            </section>
          </div>
          <p className="feature-observed-summary" aria-label="Observed support summary">
            <span>Observed</span>
            <strong>{counts.y} present · {counts.a} retained · {counts.n} dropped</strong>
            <small>{frameworkCount} tested releases</small>
          </p>
        </header>

        <div className="feature-description" data-region="description">
          <InlineCode text={capability.description} />
        </div>

        <div className="feature-display-controls" data-region="display-controls">
          <span className="alignment-label">Current aligned</span>
          <ToggleButtonGroup
            aria-label="Version cell detail"
            disallowEmptySelection
            selectionMode="single"
            selectedKeys={[gridMode]}
            size="sm"
            onSelectionChange={(keys) => {
              const mode = Array.from(keys)[0];
              if (mode === "support" || mode === "date") onGridModeChange(mode);
            }}
          >
            <ToggleButton id="support">Result</ToggleButton>
            <ToggleButtonGroup.Separator />
            <ToggleButton id="date">Release date</ToggleButton>
          </ToggleButtonGroup>
          <ToggleButtonGroup
            aria-label="Versions shown"
            disallowEmptySelection
            selectionMode="single"
            selectedKeys={[showAllVersions ? "all" : "filtered"]}
            size="sm"
            onSelectionChange={(keys) => {
              const value = Array.from(keys)[0];
              if (value === "all" || value === "filtered") {
                setShowAllVersions(value === "all");
              }
            }}
          >
            <ToggleButton id="filtered">Filtered</ToggleButton>
            <ToggleButtonGroup.Separator />
            <ToggleButton id="all">All</ToggleButton>
          </ToggleButtonGroup>
        </div>

        <div className="feature-matrix" data-region="framework-matrix">
          <CapabilityGrid
            database={database}
            capability={capability}
            hideToolbar
            mode={gridMode}
            onModeChange={onGridModeChange}
            showAllVersions={showAllVersions}
            showCaption={false}
            noteTargetPrefix={scope}
            onNoteActivate={activateNote}
          />
        </div>

        <Tabs
          className="feature-tabs"
          selectedKey={selectedDetail}
          variant="secondary"
          onSelectionChange={(key) => setSelectedDetail(String(key) as DetailKey)}
        >
          <Tabs.ListContainer>
            <Tabs.List aria-label={`${capability.title.replaceAll("`", "")} details`}>
              <Tabs.Tab id="notes" aria-label="Notes">
                <Tabs.Indicator /><span>Notes</span>
              </Tabs.Tab>
              <Tabs.Tab id="test" aria-label="Test a feature">
                <Tabs.Indicator />
                <span className="tab-label-full">Test a feature</span>
                <span className="tab-label-short" aria-hidden="true">Test</span>
              </Tabs.Tab>
              <Tabs.Tab id="issues" aria-label={`Known issues, ${issues.length}`}>
                <Tabs.Indicator />
                <span className="tab-label-full">Known issues ({issues.length})</span>
                <span className="tab-label-short" aria-hidden="true">Issues ({issues.length})</span>
              </Tabs.Tab>
              <Tabs.Tab id="resources" aria-label={`Resources, ${resources.length}`}>
                <Tabs.Indicator />
                <span className="tab-label-full">Resources ({resources.length})</span>
                <span className="tab-label-short" aria-hidden="true">Resources ({resources.length})</span>
              </Tabs.Tab>
              <Tabs.Tab id="feedback" aria-label="Feedback">
                <Tabs.Indicator /><span>Feedback</span>
              </Tabs.Tab>
            </Tabs.List>
          </Tabs.ListContainer>

          <Tabs.Panel id="notes">
            <div className="feature-panel-content">
              {capability.notes ? <p><InlineCode text={capability.notes} /></p> : null}
              {notes.length ? (
                <ul className="numbered-notes">
                  {notes.map(([number, note]) => {
                    const labels = noteReferences.get(Number(number)) ?? [];
                    const visibleLabel = `#${number} · ${labels.join(", ")}`;
                    return (
                    <li
                      id={`${scope}-note-${number}`}
                      key={number}
                      tabIndex={-1}
                      aria-label={`${visibleLabel}: ${note}`}
                    >
                      <strong className="note-reference-label">{visibleLabel}</strong>
                      <span><InlineCode text={note} /></span>
                    </li>
                    );
                  })}
                </ul>
              ) : (
                <p>No additional notes are recorded.</p>
              )}
            </div>
          </Tabs.Panel>
          <Tabs.Panel id="test">
            <div className="feature-panel-content">
              <TestPanel database={database} capability={capability} />
            </div>
          </Tabs.Panel>
          <Tabs.Panel id="issues">
            <div className="feature-panel-content">
              {issues.length ? (
                <ul>{issues.map((issue) => <li key={issue}><InlineCode text={issue} /></li>)}</ul>
              ) : <p>No known issues are recorded.</p>}
            </div>
          </Tabs.Panel>
          <Tabs.Panel id="resources">
            <div className="feature-panel-content">
              {resources.length ? (
                <ul>
                  {resources.map((resource) => (
                    <li key={resource.url}>
                      <Link href={resource.url} target="_blank" rel="noopener noreferrer">
                        {resource.title}<Link.Icon />
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : <p>No additional resources are recorded.</p>}
              <ExampleComparison capability={capability} />
            </div>
          </Tabs.Panel>
          <Tabs.Panel id="feedback">
            <div className="feature-panel-content feature-feedback">
              <p>Found a source mismatch or adapter change? Submit a correction with evidence.</p>
              <Link href={issueUrl} target="_blank" rel="noopener noreferrer">
                <GitHubIcon width={16} height={16} />
                Correct this measurement
              </Link>
              <DocsLink capability={capability} />
            </div>
          </Tabs.Panel>
        </Tabs>

      </div>
    </article>
  );
}
