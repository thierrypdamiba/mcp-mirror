import {Button, Link} from "@heroui/react";

import type {MirrorDatabase, Route} from "../types";
import {FilterIcon} from "./Icons";

function stripLabel(
  route: Route,
  query: string,
  resultCount: number,
  selectedCategoryCount: number,
): string {
  if (route.name === "index") {
    return query.trim() || selectedCategoryCount
      ? `${resultCount} matching capabilities`
      : "Index of capabilities";
  }
  if (route.name === "capability") {
    return "Capability support table";
  }
  if (route.name === "compare") {
    return "Compare frameworks";
  }
  if (route.name === "changes") {
    return "Measurement changes";
  }
  return "About MCP Mirror";
}

export function FeatureStrip({
  database,
  route,
  query,
  resultCount,
  isFilterOpen,
  selectedCategories,
  onFilterOpenChange,
  onCategoryChange,
  onClearFilters,
}: {
  database: MirrorDatabase;
  route: Route;
  query: string;
  resultCount: number;
  isFilterOpen: boolean;
  selectedCategories: string[];
  onFilterOpenChange: (isOpen: boolean) => void;
  onCategoryChange: (category: string, selected: boolean) => void;
  onClearFilters: () => void;
}) {
  return (
    <section className="site-shell feature-filter-shell">
      <div className="feature-strip">
        <Link href="#/">
          {stripLabel(
            route,
            query,
            resultCount,
            selectedCategories.length,
          )}
        </Link>
        <Button
          className={`filter-button${isFilterOpen ? " is-selected" : ""}`}
          aria-controls="capability-filter-panel"
          aria-expanded={isFilterOpen}
          variant="ghost"
          onPress={() => onFilterOpenChange(!isFilterOpen)}
        >
          <FilterIcon />
          Filter capabilities
        </Button>
      </div>

      {isFilterOpen ? (
        <form
          className="capability-filter-panel"
          id="capability-filter-panel"
          onSubmit={(event) => {
            event.preventDefault();
            onFilterOpenChange(false);
          }}
        >
          <fieldset>
            <legend>Capability categories</legend>
            <div className="filter-options">
              {Object.keys(database.cats).map((category) => (
                <label key={category}>
                  <input
                    type="checkbox"
                    checked={selectedCategories.includes(category)}
                    onChange={(event) =>
                      onCategoryChange(category, event.currentTarget.checked)
                    }
                  />
                  <span>{category}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="filter-panel-actions">
            <span aria-live="polite">
              {resultCount} {resultCount === 1 ? "capability" : "capabilities"}
            </span>
            <Button
              isDisabled={!selectedCategories.length}
              type="button"
              variant="ghost"
              onPress={onClearFilters}
            >
              Clear filters
            </Button>
            <Button type="submit" variant="primary">
              Show results
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
