import {Link} from "@heroui/react";

import type {Capability} from "../types";
import {ArrowUpRightIcon, DocumentIcon} from "./Icons";

export function InlineCode({text}: {text: string}) {
  return (
    <>
      {text.split(/(`[^`]+`)/g).map((part, index) =>
        part.startsWith("`") && part.endsWith("`") ? (
          <code key={`${part}-${index}`}>{part.slice(1, -1)}</code>
        ) : (
          part
        ),
      )}
    </>
  );
}

export function CapabilityTitle({capability}: {capability: Capability}) {
  return (
    <span className="capability-title">
      <InlineCode text={capability.title} />
    </span>
  );
}

export function DocsLink({capability}: {capability: Capability}) {
  const label = capability.docs_label ?? capability.spec_label ?? "Docs";
  return (
    <Link
      className="spec-link"
      href={capability.docs_url ?? capability.spec}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${label} for ${capability.title.replaceAll("`", "")}`}
    >
      <DocumentIcon className="spec-link-document-icon" width={14} height={14} />
      <span>{label}</span>
      <ArrowUpRightIcon width={14} height={14} />
    </Link>
  );
}
