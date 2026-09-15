import {Link} from "@heroui/react";

import type {MirrorDatabase, Route} from "../types";
import {NewsTicker} from "./NewsTicker";

interface SiteHeaderProps {
  database: MirrorDatabase;
  route: Route;
  onHomeReset: () => void;
}

const navItems = [
  {label: "Home", shortLabel: "Home", href: "#/", route: "index"},
  {label: "Stats", shortLabel: "Stats", href: "#/stats", route: "stats"},
  {label: "News", shortLabel: "News", href: "#/changes", route: "changes"},
  {label: "About", shortLabel: "About", href: "#/method", route: "method"},
] as const;

export function SiteHeader({route, onHomeReset}: SiteHeaderProps) {
  return (
    <header className="site-header">
      <div className="site-shell header-main-row">
        <nav className="site-nav" aria-label="Primary navigation">
          <ul className="site-nav-list">
            {navItems.map((item) => {
              const active =
                route.name === item.route ||
                (item.route === "index" && route.name === "capability");
              return (
                <li key={item.route}>
                  <Link
                    className="nav-link"
                    data-active={active || undefined}
                    href={item.href}
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
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="header-ticker-row">
          <NewsTicker />
        </div>
      </div>
    </header>
  );
}
