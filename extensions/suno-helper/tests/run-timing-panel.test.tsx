// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { PHASE, type RunTimingReceipt } from "../../shared/constants";
import { RunTimingPanel } from "../components/RunTimingPanel";

const RECEIPT: RunTimingReceipt = {
  version: 1,
  started_at_ms: 1_000,
  ended_at_ms: 2_500,
  outcome: "finished",
  failed_phase: null,
  sessions: [{ started_at_ms: 1_000, ended_at_ms: 2_500 }],
  events: [
    {
      phase: PHASE.DOWNLOADING,
      attempt: 1,
      started_at_ms: 1_000,
      ended_at_ms: 2_000,
      duration_ms: 1_000,
    },
    {
      phase: PHASE.PLACING_ARCHIVE,
      attempt: 1,
      started_at_ms: 2_000,
      ended_at_ms: 2_500,
      duration_ms: 500,
    },
  ],
  active_duration_ms: 1_500,
  unmeasured_gap_ms: 0,
};

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const writeText = vi.fn<(text: string) => Promise<void>>();

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it("should display persisted timing and copy the same privacy-safe JSON", async () => {
  await act(async () =>
    root.render(createElement(RunTimingPanel, { receipt: RECEIPT }))
  );

  expect(container.textContent).toContain("downloading #1: 1.00s");
  expect(container.textContent).toContain("placing-archive #1: 0.50s");
  expect(container.textContent).toContain("total: 1.50s");
  expect(container.textContent).toContain("unmeasured gap: 0.00s");

  await act(async () =>
    container.querySelector<HTMLButtonElement>("button")?.click()
  );
  expect(JSON.parse(writeText.mock.calls[0][0])).toEqual(RECEIPT);
});
