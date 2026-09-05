import {Button} from "@heroui/react";
import {useEffect, useRef, useState, type ReactNode} from "react";

import {ClipboardIcon} from "./Icons";

export async function writeClipboardText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // file:// standalone pages and some permission policies reject the
      // async API. Fall through to the selection-based local fallback.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.readOnly = true;
  textarea.setAttribute("aria-hidden", "true");
  textarea.style.position = "fixed";
  textarea.style.inset = "0 auto auto -9999px";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, value.length);

  try {
    if (!document.execCommand("copy")) {
      throw new Error("Clipboard copy was rejected");
    }
  } finally {
    textarea.remove();
  }
}

export function CopyCodeBlock({
  value,
  children,
  className = "",
}: {
  value: string;
  children?: ReactNode;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const resetTimer = useRef<number | undefined>(undefined);

  useEffect(
    () => () => {
      if (resetTimer.current !== undefined) {
        window.clearTimeout(resetTimer.current);
      }
    },
    [],
  );

  return (
    <div className={`copy-code-block ${className}`.trim()}>
      <pre>
        <code>{children ?? value}</code>
      </pre>
      <Button
        className="copy-command-button"
        aria-label="Copy command"
        size="sm"
        variant="tertiary"
        onPress={() => {
          void writeClipboardText(value).then(() => {
            setCopied(true);
            if (resetTimer.current !== undefined) {
              window.clearTimeout(resetTimer.current);
            }
            resetTimer.current = window.setTimeout(
              () => setCopied(false),
              1_600,
            );
          });
        }}
      >
        <ClipboardIcon width={15} height={15} aria-hidden="true" />
        <span aria-hidden="true">{copied ? "Copied" : "Copy"}</span>
        <span className="sr-only" aria-live="polite">
          {copied ? "Copied" : ""}
        </span>
      </Button>
    </div>
  );
}
