import {Chip, Tooltip} from "@heroui/react";

import {
  currentSupport,
  SUPPORT_META,
  supportCounts,
} from "../lib/data";
import type {Capability, MirrorDatabase, SupportCode} from "../types";

const chipColor: Record<
  SupportCode,
  "success" | "warning" | "danger" | "default"
> = {
  x: "default",
  y: "success",
  a: "warning",
  n: "danger",
  u: "default",
};

export function SupportChip({
  code,
  showSymbol = true,
  compact = false,
}: {
  code: SupportCode;
  showSymbol?: boolean;
  compact?: boolean;
}) {
  const meta = SUPPORT_META[code];
  return (
    <Chip
      color={chipColor[code]}
      size={compact ? "sm" : "md"}
      variant="soft"
    >
      {showSymbol ? `${meta.symbol} ` : ""}
      {compact ? meta.shortLabel : meta.label}
    </Chip>
  );
}

export function SupportBar({
  database,
  capability,
}: {
  database: MirrorDatabase;
  capability: Capability;
}) {
  const counts = supportCounts(database, capability);
  const total = Object.keys(database.agents).length;
  const label = (Object.keys(counts) as SupportCode[])
    .map((code) => `${counts[code]} ${SUPPORT_META[code].shortLabel.toLowerCase()}`)
    .join(", ");

  return (
    <div
      className="support-bar"
      role="img"
      aria-label={`${label}, across ${total} frameworks`}
    >
      {(Object.keys(counts) as SupportCode[]).map((code) =>
        counts[code] ? (
          <span
            key={code}
            className={`support-segment support-${code}`}
            style={{width: `${(counts[code] / total) * 100}%`}}
          />
        ) : null,
      )}
    </div>
  );
}

export function FrameworkPills({
  database,
  capability,
}: {
  database: MirrorDatabase;
  capability: Capability;
}) {
  return (
    <div className="framework-pills" aria-label="Current framework results">
      {Object.entries(database.agents).map(([agentId, agent]) => {
        const support = currentSupport(database, capability, agentId);
        return (
          <Tooltip key={agentId} delay={300}>
            <Tooltip.Trigger>
              <span
                className={`framework-pill support-${support.code}`}
                tabIndex={0}
              >
                <b>{agent.abbr}</b>
                <span aria-hidden="true">{SUPPORT_META[support.code].symbol}</span>
                <span className="sr-only">
                  {agent.name}: {SUPPORT_META[support.code].label}
                </span>
              </span>
            </Tooltip.Trigger>
            <Tooltip.Content showArrow>
              <Tooltip.Arrow />
              {agent.name}: {SUPPORT_META[support.code].label}
            </Tooltip.Content>
          </Tooltip>
        );
      })}
    </div>
  );
}
