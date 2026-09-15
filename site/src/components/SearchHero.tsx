import {Button, Link, SearchField} from "@heroui/react";
import {useEffect, useRef, useState} from "react";

import type {GridMode} from "./CapabilityGrid";
import type {SpecIndex} from "../types";
import {GearIcon} from "./Icons";

const RECENT_SEARCH_STORAGE_KEY = "mcp-mirror:recent-searches:v1";
const MAX_RECENT_SEARCHES = 6;

function readRecentSearches(): string[] {
  try {
    const value = JSON.parse(
      localStorage.getItem(RECENT_SEARCH_STORAGE_KEY) ?? "[]",
    );
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string").slice(0, 6)
      : [];
  } catch {
    return [];
  }
}

function normalizeQuery(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

interface SearchHeroProps {
  query: string;
  resultCount: number;
  onChange: (value: string) => void;
  onHomeReset: () => void;
  specIndex: SpecIndex | null;
  selectedSpec: string;
  onSpecChange: (value: string) => void;
  gridMode: GridMode;
  onGridModeChange: (value: GridMode) => void;
}

export function SearchHero({
  query,
  resultCount,
  onChange,
  onHomeReset,
  specIndex,
  selectedSpec,
  onSpecChange,
  gridMode,
  onGridModeChange,
}: SearchHeroProps) {
  const [recentSearches, setRecentSearches] = useState<string[]>(
    readRecentSearches,
  );
  const [isRecentOpen, setIsRecentOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const settingsRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setIsRecentOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);

  const persistRecent = (next: string[]) => {
    setRecentSearches(next);
    localStorage.setItem(RECENT_SEARCH_STORAGE_KEY, JSON.stringify(next));
  };

  const commitCurrentQuery = () => {
    const normalized = normalizeQuery(query);
    if (normalized.length < 2 || resultCount < 1) return;
    persistRecent([
      normalized,
      ...recentSearches.filter(
        (item) => item.toLocaleLowerCase() !== normalized.toLocaleLowerCase(),
      ),
    ].slice(0, MAX_RECENT_SEARCHES));
  };
  const selectedSpecEntry = specIndex?.specs.find(
    (entry) => entry.id === selectedSpec,
  );
  const openSettings = () => {
    setIsRecentOpen(false);
    settingsRef.current?.showModal();
  };

  return (
    <section className="search-hero" aria-label="Capability search">
      <div className="site-shell search-hero-inner">
        <Link
          className="search-wordmark"
          href="#/"
          aria-label="Reset Can AI use search"
          onPress={onHomeReset}
        >
          Can AI use
        </Link>

        <div
          className="capability-search-wrap"
          ref={wrapperRef}
          onKeyDown={(event) => {
            if (event.key === "Escape") setIsRecentOpen(false);
          }}
        >
          <SearchField
            aria-label="Search MCP capabilities"
            className="capability-search"
            fullWidth
            value={query}
            onChange={(value) => {
              onChange(value);
              if (value) setIsRecentOpen(false);
            }}
          >
            <SearchField.Group>
              <SearchField.Input
                id="capability-search"
                ref={inputRef}
                autoFocus
                autoComplete="off"
                spellCheck={false}
                onFocus={() => {
                  if (!query && recentSearches.length) setIsRecentOpen(true);
                }}
                onBlur={commitCurrentQuery}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commitCurrentQuery();
                }}
              />
            </SearchField.Group>
          </SearchField>
          {isRecentOpen && !query && recentSearches.length ? (
            <div
              className="recent-searches"
              role="region"
              aria-label="Recent searches"
            >
              <div className="recent-searches-heading">
                <strong>Recent searches</strong>
              </div>
              <ul>
                {recentSearches.map((item) => (
                  <li key={item.toLocaleLowerCase()}>
                    <Button
                      className="recent-search-run"
                      variant="ghost"
                      onPress={() => {
                        onChange(item);
                        setIsRecentOpen(false);
                        inputRef.current?.focus();
                      }}
                    >
                      {item}
                    </Button>
                    <Button
                      className="recent-search-remove"
                      aria-label={`Remove recent search ${item}`}
                      isIconOnly
                      variant="ghost"
                      onPress={() =>
                        persistRecent(
                          recentSearches.filter((candidate) => candidate !== item),
                        )
                      }
                    >
                      ×
                    </Button>
                  </li>
                ))}
              </ul>
              <Button
                className="recent-search-clear"
                variant="ghost"
                onPress={() => {
                  persistRecent([]);
                  setIsRecentOpen(false);
                }}
              >
                Clear recent searches
              </Button>
            </div>
          ) : null}
        </div>

        <span className="search-question" aria-hidden="true">?</span>
        <Button
          className="search-settings"
          variant="ghost"
          aria-haspopup="dialog"
          onPress={openSettings}
        >
          <GearIcon />
          <span>Settings</span>
        </Button>
      </div>
      <div className="search-context">
        <span className="search-result-context" aria-live="polite">
          {query.trim()
            ? `${resultCount} ${resultCount === 1 ? "result" : "results"}`
            : null}
        </span>
        {specIndex ? (
          <label className="spec-selector">
            <span>Protocol snapshot</span>
            <select
              aria-label="MCP specification revision"
              value={selectedSpec}
              onFocus={() => setIsRecentOpen(false)}
              onChange={(event) => {
                setIsRecentOpen(false);
                onSpecChange(event.currentTarget.value);
              }}
            >
              {specIndex.specs.map((entry) => (
                <option value={entry.id} key={entry.id}>
                  {entry.label}
                </option>
              ))}
            </select>
            {selectedSpecEntry ? (
              <small>
                {selectedSpecEntry.measured_frameworks} of{" "}
                {selectedSpecEntry.total_frameworks} frameworks reach this
                revision
              </small>
            ) : null}
          </label>
        ) : null}
      </div>
      <dialog
        className="settings-dialog"
        ref={settingsRef}
        aria-labelledby="settings-title"
        onClick={(event) => {
          if (event.target === event.currentTarget) event.currentTarget.close();
        }}
      >
        <form method="dialog" className="settings-panel">
          <div className="settings-heading">
            <div>
              <p className="eyebrow">Display preferences</p>
              <h2 id="settings-title">Settings</h2>
            </div>
            <Button
              aria-label="Close settings"
              isIconOnly
              type="submit"
              variant="ghost"
              onPress={() => settingsRef.current?.close()}
            >
              ×
            </Button>
          </div>

          <label className="settings-field">
            <span>MCP protocol snapshot</span>
            <select
              value={selectedSpec}
              onChange={(event) => onSpecChange(event.currentTarget.value)}
            >
              {specIndex?.specs.map((entry) => (
                <option value={entry.id} key={entry.id}>
                  {entry.label}
                </option>
              ))}
            </select>
            {selectedSpecEntry ? (
              <small>
                {selectedSpecEntry.measured_frameworks} of{" "}
                {selectedSpecEntry.total_frameworks} frameworks produced
                same-revision measurements.
              </small>
            ) : null}
          </label>

          <fieldset className="settings-field">
            <legend>Capability table cells</legend>
            <label>
              <input
                type="radio"
                name="grid-mode"
                checked={gridMode === "support"}
                onChange={() => onGridModeChange("support")}
              />
              Support status
            </label>
            <label>
              <input
                type="radio"
                name="grid-mode"
                checked={gridMode === "date"}
                onChange={() => onGridModeChange("date")}
              />
              Measurement date
            </label>
          </fieldset>

          <div className="settings-actions">
            <Link href="#/method" onPress={() => settingsRef.current?.close()}>
              Measurement method
            </Link>
            <Button
              type="submit"
              variant="primary"
              onPress={() => settingsRef.current?.close()}
            >
              Done
            </Button>
          </div>
        </form>
      </dialog>
    </section>
  );
}
