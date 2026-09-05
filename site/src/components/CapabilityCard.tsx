import {Card, Chip, Link} from "@heroui/react";
import {useId} from "react";

import {capabilityHref, supportCounts} from "../lib/data";
import type {Capability, MirrorDatabase, SupportCode} from "../types";
import type {GridMode} from "./CapabilityGrid";
import {CapabilityTitle, DocsLink, InlineCode} from "./CapabilityText";
import {FeatureModule} from "./FeatureModule";
import {ChevronRightIcon} from "./Icons";
import {FrameworkPills, SupportBar, SupportChip} from "./Support";

function currentSummary(
  database: MirrorDatabase,
  capability: Capability,
): string {
  const counts = supportCounts(database, capability);
  const labels: Record<SupportCode, string> = {
    y: "present",
    a: "retained",
    n: "dropped",
    u: "unmeasured",
  };
  return (["y", "a", "n", "u"] as SupportCode[])
    .filter((code) => counts[code])
    .map((code) => `${counts[code]} ${labels[code]}`)
    .join(", ");
}

export function CapabilityCard({
  database,
  capability,
  presentation = "compact",
  starred = false,
  onToggleStar = () => undefined,
  gridMode = "support",
  onGridModeChange = () => undefined,
}: {
  database: MirrorDatabase;
  capability: Capability;
  presentation?: "compact" | "table";
  starred?: boolean;
  onToggleStar?: () => void;
  gridMode?: GridMode;
  onGridModeChange?: (mode: GridMode) => void;
}) {
  const headingId = useId();

  if (presentation === "table") {
    return (
      <FeatureModule
        database={database}
        capability={capability}
        starred={starred}
        onToggleStar={onToggleStar}
        gridMode={gridMode}
        onGridModeChange={onGridModeChange}
      />
    );
  }

  const category = (capability.categories ?? ["Other"])[0];
  return (
    <Card
      className="capability-card capability-card-compact"
      role="article"
      aria-labelledby={headingId}
    >
      <Card.Header className="capability-card-header">
        <span className="capability-glyph" aria-hidden="true">
          {capability.title.replaceAll("`", "").slice(0, 2).toUpperCase()}
        </span>
        <div className="capability-heading-copy">
          <div className="capability-title-row">
            <Card.Title id={headingId}>
              <Link href={capabilityHref(capability.id)}>
                <CapabilityTitle capability={capability} />
              </Link>
            </Card.Title>
            <DocsLink capability={capability} />
          </div>
          <Card.Description>
            <InlineCode text={capability.description} />
          </Card.Description>
        </div>
      </Card.Header>
      <Card.Content className="capability-card-content">
        <div className="capability-status-line">
          <SupportChip code={capability.verdict.code} compact />
          <span>{currentSummary(database, capability)}</span>
        </div>
        <SupportBar database={database} capability={capability} />
        <FrameworkPills database={database} capability={capability} />
      </Card.Content>
      <Card.Footer className="capability-card-footer">
        <Chip size="sm" variant="tertiary">{category}</Chip>
        <Link href={capabilityHref(capability.id)}>
          Open measurement
          <ChevronRightIcon width={15} height={15} />
        </Link>
      </Card.Footer>
    </Card>
  );
}

export {InlineCode};
export {DocsLink as SpecLink};
