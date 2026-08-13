import { Button } from "@youtube-automation/ui";
import { useMemo, useState } from "react";

import type { RunTimingReceipt } from "../../shared/constants";
import { formatRunTiming } from "../lib/run-timing";

type CopyState = "idle" | "copied" | "failed";

export function RunTimingPanel({ receipt }: { receipt: RunTimingReceipt }) {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const formatted = useMemo(() => formatRunTiming(receipt), [receipt]);

  const copyJson = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(formatted.json);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  return (
    <section
      aria-labelledby="suno-run-timing-title"
      className="rounded border border-border p-2 text-xs"
      data-suno-control="run-timing"
    >
      <h2 className="font-semibold" id="suno-run-timing-title">
        Run timing
      </h2>
      <ul className="mt-1 space-y-0.5">
        {formatted.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <Button
        className="mt-2"
        data-suno-control="copy-run-timing"
        onClick={() => void copyJson()}
        size="sm"
        type="button"
        variant="outline"
      >
        Timing JSON をコピー
      </Button>
      {copyState === "copied" && <p role="status">コピーしました。</p>}
      {copyState === "failed" && <p role="alert">コピーできませんでした。</p>}
    </section>
  );
}
