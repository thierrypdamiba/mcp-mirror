import {siCrewai, siLangchain, siPydantic} from "simple-icons";

const ICONS: Record<string, {path: string; title: string}> = {
  crewai: siCrewai,
  langchain: siLangchain,
  "pydantic-ai": siPydantic,
};

export function FrameworkLogo({
  frameworkId,
  name,
}: {
  frameworkId: string;
  name: string;
}) {
  const icon = ICONS[frameworkId];
  if (icon) {
    return (
      <svg
        className="framework-logo"
        viewBox="0 0 24 24"
        role="img"
        aria-label={`${name} logo`}
      >
        <path d={icon.path} />
      </svg>
    );
  }

  return (
    <svg
      className="framework-logo framework-logo-fallback"
      viewBox="0 0 24 24"
      role="img"
      aria-label={`${name} package`}
    >
      <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9" />
    </svg>
  );
}
