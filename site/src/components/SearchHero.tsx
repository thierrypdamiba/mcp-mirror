import {Button, Link, SearchField} from "@heroui/react";
import {useEffect, useRef, useState} from "react";

import {SearchIcon} from "./Icons";

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
}

export function SearchHero({
  query,
  resultCount,
  onChange,
  onHomeReset,
}: SearchHeroProps) {
  const [recentSearches, setRecentSearches] = useState<string[]>(
    readRecentSearches,
  );
  const [isRecentOpen, setIsRecentOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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

  return (
    <section className="search-hero" aria-label="Capability search">
      <div className="site-shell search-hero-inner">
        <h1>
          <Link
            className="search-wordmark"
            href="#/"
            aria-label="Reset capability search"
            onPress={onHomeReset}
          >
            <span>MCP capability support</span>{" "}
            <strong>across agent frameworks</strong>
          </Link>
        </h1>
        <p className="hero-copy">
          Search a tool-definition capability to see whether each framework
          preserves it across exact tested versions.
        </p>

        <div className="hero-interaction-row">
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
                <span className="search-input-icon" aria-hidden="true">
                  <SearchIcon width={17} height={17} />
                </span>
                <SearchField.Input
                  id="capability-search"
                  ref={inputRef}
                  autoFocus
                  autoComplete="off"
                  placeholder="Can I rely on…?"
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
          <div className="hero-actions">
            <Button
              className="hero-browse"
              variant="primary"
              onPress={() => {
                const target = document.getElementById("explore-heading");
                target?.scrollIntoView({behavior: "smooth", block: "start"});
                target?.focus({preventScroll: true});
              }}
            >
              Browse capabilities
            </Button>
            <Link className="hero-method" href="#/method">
              How measurements work
              <Link.Icon />
            </Link>
          </div>
        </div>
      </div>
      <div className="search-context" aria-live="polite">
        {query.trim()
          ? `${resultCount} ${resultCount === 1 ? "result" : "results"}`
          : null}
      </div>
    </section>
  );
}
