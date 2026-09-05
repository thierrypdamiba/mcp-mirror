import {FeatureModule} from "../components/FeatureModule";
import type {GridMode} from "../components/CapabilityGrid";
import type {Capability, MirrorDatabase} from "../types";

export function CapabilityPage({
  database,
  capability,
  starred,
  onToggleStar,
  gridMode,
  onGridModeChange,
}: {
  database: MirrorDatabase;
  capability: Capability;
  starred: boolean;
  onToggleStar: () => void;
  gridMode: GridMode;
  onGridModeChange: (mode: GridMode) => void;
}) {
  return (
    <main className="site-shell page-main capability-page" id="main-content">
      <FeatureModule
        database={database}
        capability={capability}
        starred={starred}
        onToggleStar={onToggleStar}
        gridMode={gridMode}
        onGridModeChange={onGridModeChange}
        detail
      />
    </main>
  );
}
