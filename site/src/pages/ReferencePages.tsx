import {Card, Chip, Link} from "@heroui/react";

import {capabilityHref, currentSupport, shortDate, titleCaseRule} from "../lib/data";
import type {Capability, MirrorDatabase, SupportCode} from "../types";
import {ArrowUpRightIcon, ChevronRightIcon} from "../components/Icons";

function PageIntro({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <header className="page-intro">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{children}</p>
    </header>
  );
}

function DistributionBar({
  counts,
}: {
  counts: Record<SupportCode, number>;
}) {
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  return (
    <div className="support-bar" aria-hidden="true">
      {(Object.keys(counts) as SupportCode[]).map((code) =>
        counts[code] ? (
          <span
            className={`support-segment support-${code}`}
            key={code}
            style={{width: `${(counts[code] / total) * 100}%`}}
          />
        ) : null,
      )}
    </div>
  );
}

export function ChangesPage({
  database,
  capabilities,
}: {
  database: MirrorDatabase;
  capabilities: Capability[];
}) {
  const byDate = new Map<string, Capability[]>();
  for (const capability of capabilities) {
    byDate.set(capability.measured.run_date, [
      ...(byDate.get(capability.measured.run_date) ?? []),
      capability,
    ]);
  }

  return (
    <main className="site-shell page-main" id="main-content">
      <PageIntro eyebrow="Measurement history" title="Changes">
        Every dated entry is a deterministic adapter run. Git history remains
        the line-by-line changelog for each capability file.
      </PageIntro>

      <div className="change-stack">
        {Array.from(byDate.entries())
          .sort(([left], [right]) => right.localeCompare(left))
          .map(([date, entries]) => (
            <Card className="change-card" key={date}>
              <Card.Header className="change-card-date">
                <Card.Title>
                  <time dateTime={date}>{shortDate(date)}</time>
                </Card.Title>
                <Card.Description>
                  Adapter measurements against MCP {database.mcp_spec}
                </Card.Description>
              </Card.Header>
              <Card.Content className="change-card-content">
                {entries.map((capability) => (
                  <Link
                    className="change-row"
                    href={capabilityHref(capability.id)}
                    key={capability.id}
                  >
                    <span>
                      <strong>{capability.title}</strong>
                      <small>{capability.verdict.headline}</small>
                    </span>
                    <ChevronRightIcon />
                  </Link>
                ))}
              </Card.Content>
            </Card>
          ))}
      </div>
    </main>
  );
}

export function ComparePage({
  database,
  capabilities,
}: {
  database: MirrorDatabase;
  capabilities: Capability[];
}) {
  return (
    <main className="site-shell page-main" id="main-content">
      <PageIntro eyebrow="Current tested releases" title="Compare frameworks">
        A distribution of observed transformations, not a score. Retaining a
        value out of band and dropping it are shown as different facts.
      </PageIntro>

      <div className="framework-card-grid">
        {Object.entries(database.agents).map(([agentId, agent]) => {
          const counts: Record<SupportCode, number> = {y: 0, a: 0, n: 0, u: 0};
          for (const capability of capabilities) {
            counts[currentSupport(database, capability, agentId).code] += 1;
          }
          const release = agent.version_list.find(
            (version) => version.era === 0,
          );

          return (
            <Card className="framework-card" key={agentId}>
              <Card.Header>
                <span className={`framework-avatar language-${agent.type}`}>
                  {agent.abbr}
                </span>
                <div>
                  <Card.Title>{agent.name}</Card.Title>
                  <Card.Description>
                    {agent.package} {agent.current_version}
                  </Card.Description>
                </div>
              </Card.Header>
              <Card.Content>
                <DistributionBar counts={counts} />
                <div className="distribution-tally">
                  <span><b>{counts.y}</b> present</span>
                  <span><b>{counts.a}</b> retained</span>
                  <span><b>{counts.n}</b> dropped</span>
                  {counts.u ? <span><b>{counts.u}</b> unmeasured</span> : null}
                </div>
                <p className="adapter-name">{agent.adapter}</p>
              </Card.Content>
              <Card.Footer>
                <Chip size="sm" variant="tertiary">{agent.type}</Chip>
                <span>released {shortDate(release?.release_date)}</span>
              </Card.Footer>
            </Card>
          );
        })}
      </div>
    </main>
  );
}

export function MethodPage({database}: {database: MirrorDatabase}) {
  const methodCards = [
    {
      title: "The measurement",
      body:
        "Each cell compares what an MCP server publishes with the tool definition a framework adapter produces. No model is called, so the same inputs produce the same result.",
      variant: "default" as const,
    },
    {
      title: "The data shape",
      body:
        "Frameworks carry version lists and release dates. Capabilities carry one support code per tested framework version, plus numbered notes that name the mechanism.",
      variant: "secondary" as const,
    },
    {
      title: "No percentage without a source",
      body:
        "There is no adoption weighting yet. A future weighting must name its corpus, collection period, and method before it appears here.",
      variant: "secondary" as const,
    },
    {
      title: "Licensing and corrections",
      body:
        "Code is MIT. Support data is CC BY 4.0. A framework can reuse its own row, reproduce it, and submit a correction through the same public data files.",
      variant: "tertiary" as const,
    },
  ];

  return (
    <main className="site-shell page-main" id="main-content">
      <PageIntro eyebrow="Reproducibility" title="Method and defaults">
        Most of this site is measured fact. The explicit defaults below are the
        choices that determine what appears and what earns each status.
      </PageIntro>

      <div className="method-card-grid">
        {methodCards.map((item) => (
          <Card className="method-card" key={item.title} variant={item.variant}>
            <Card.Header>
              <Card.Title>{item.title}</Card.Title>
              <Card.Description>{item.body}</Card.Description>
            </Card.Header>
          </Card>
        ))}
      </div>

      <section className="defaults-section" aria-labelledby="defaults-title">
        <div className="section-heading">
          <p className="eyebrow">Published choices</p>
          <h2 id="defaults-title">Defaults</h2>
        </div>
        <div className="defaults-stack">
          {Object.entries(database.defaults).map(([name, value], index) => (
            <Card
              className="default-card"
              key={name}
              variant={index % 2 ? "secondary" : "default"}
            >
              <Card.Header>
                <Chip size="sm" variant="soft">
                  {String(index + 1).padStart(2, "0")}
                </Chip>
                <Card.Title>{titleCaseRule(name)}</Card.Title>
              </Card.Header>
              <Card.Content>
                <p>{value}</p>
              </Card.Content>
            </Card>
          ))}
        </div>
      </section>

      <Card className="contribute-card">
        <Card.Header>
          <Card.Title>Inspect or correct the data</Card.Title>
          <Card.Description>
            Every status links back to a capability file and a deterministic
            reproduction command.
          </Card.Description>
        </Card.Header>
        <Card.Footer>
          <Link
            href={database.repo || "https://github.com/"}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open the repository
            <ArrowUpRightIcon width={16} height={16} />
          </Link>
        </Card.Footer>
      </Card>
    </main>
  );
}
