import {Link} from "@heroui/react";

import type {MirrorDatabase, Route} from "../types";
import {GitHubIcon} from "./Icons";
import {NewsTicker} from "./NewsTicker";

interface SiteHeaderProps {
  database: MirrorDatabase;
  route: Route;
  onHomeReset: () => void;
}

const navItems = [
  {label: "Home", shortLabel: "Home", href: "#/", route: "index"},
  {label: "News", shortLabel: "News", href: "#/changes", route: "changes"},
  {
    label: "Compare frameworks",
    shortLabel: "Compare",
    href: "#/compare",
    route: "compare",
  },
  {label: "About", shortLabel: "About", href: "#/method", route: "method"},
] as const;

export function SiteHeader({database, route, onHomeReset}: SiteHeaderProps) {
  return (
    <header className="site-header">
      <div className="header-announcement">
        <div className="site-shell header-ticker-row">
          <NewsTicker />
        </div>
      </div>
      <div className="site-shell header-main-row">
        <div className="header-left-cluster">
          <Link
            className="header-brand"
            href="#/"
            aria-label="MCP Mirror home"
            onPress={onHomeReset}
          >
            <span className="mirror-mark" aria-hidden="true">
              <i />
              <i />
            </span>
            <span>MCP Mirror</span>
          </Link>
          <nav className="site-nav" aria-label="Primary navigation">
            {navItems.map((item) => {
              const active =
                route.name === item.route ||
                (item.route === "index" && route.name === "capability");
              return (
                <Link
                  className="nav-link"
                  data-active={active || undefined}
                  href={item.href}
                  key={item.route}
                  aria-current={active ? "page" : undefined}
                  aria-label={item.label}
                  onPress={item.route === "index" ? onHomeReset : undefined}
                >
                  {item.label !== item.shortLabel ? (
                    <>
                      <span>{item.shortLabel}</span>
                      {" "}
                      <span className="site-nav-extra-text">
                        {item.label.slice(item.shortLabel.length).trim()}
                      </span>
                    </>
                  ) : item.shortLabel}
                </Link>
              );
            })}
          </nav>
        </div>
        <Link
          className="header-source"
          href={database.repo || "https://github.com/"}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="MCP Mirror source on GitHub, opens externally"
        >
          <GitHubIcon width={15} height={15} />
          <span>Source</span>
        </Link>
      </div>
    </header>
  );
}
