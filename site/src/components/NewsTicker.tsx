import {Link} from "@heroui/react";
import {useLayoutEffect, useRef, useState} from "react";

import news from "../data/news.json";

const CRAWL_SPEED_PX_PER_SECOND = 42;

function HeadlineGroup({
  cloned = false,
}: {
  cloned?: boolean;
}) {
  return (
    <div
      className="news-crawl-group"
      aria-hidden={cloned || undefined}
      inert={cloned || undefined}
      data-clone={cloned || undefined}
    >
      {news.map((item) => (
        <span className="news-crawl-item" key={`${cloned ? "clone-" : ""}${item.id}`}>
          <Link
            className="news-ticker-link"
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`${item.title}, ${item.source}, published ${item.date}`}
          >
            {item.title}
          </Link>
          <span className="news-crawl-source-divider" aria-hidden="true">•</span>
          <span className="news-crawl-source">{item.source}</span>
          <span className="news-crawl-divider" aria-hidden="true">◆</span>
        </span>
      ))}
    </div>
  );
}

export function NewsTicker() {
  const groupRef = useRef<HTMLDivElement | null>(null);
  const [duration, setDuration] = useState(40);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [interacting, setInteracting] = useState(false);
  const paused = hovered || focused || interacting;

  useLayoutEffect(() => {
    const group = groupRef.current;
    if (!group) return undefined;
    const updateDuration = () => {
      setDuration(
        Math.max(20, group.scrollWidth / CRAWL_SPEED_PX_PER_SECOND),
      );
    };
    updateDuration();
    const observer = new ResizeObserver(updateDuration);
    observer.observe(group);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      className="news-ticker"
      aria-label="MCP news headlines"
      data-paused={paused || undefined}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
      onPointerDown={() => setInteracting(true)}
      onPointerUp={() => setInteracting(false)}
      onPointerCancel={() => setInteracting(false)}
    >
      <div
        className="news-crawl-track"
        style={{
          "--crawl-duration": `${duration}s`,
          animationPlayState: paused ? "paused" : "running",
        } as React.CSSProperties}
      >
        <div ref={groupRef}><HeadlineGroup /></div>
        <HeadlineGroup cloned />
      </div>
      <div className="news-crawl-reduced">
        <Link
          className="news-ticker-link"
          href={news[0].url}
          target="_blank"
          rel="noopener noreferrer"
        >
          {news[0].title}
        </Link>
        <span aria-hidden="true">•</span>
        <span className="news-crawl-source">{news[0].source}</span>
      </div>
    </div>
  );
}
