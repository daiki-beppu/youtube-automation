import { describe, expect, it } from "vitest";

import { PHASE } from "../../shared/constants";
import {
  beginRunTiming,
  finalizeRunTiming,
  formatRunTiming,
  resumeRunTiming,
  transitionRunTiming,
} from "../lib/run-timing";

describe("run timing receipt", () => {
  it("should calculate deterministic phase durations and an unmeasured gap", () => {
    let receipt = beginRunTiming(PHASE.INJECTING, 1_000);
    receipt = transitionRunTiming(receipt, PHASE.GENERATING, 1_100);
    receipt = transitionRunTiming(receipt, PHASE.WAITING_SLOT, 1_400);
    receipt = transitionRunTiming(receipt, PHASE.ADDING_TO_PLAYLIST, 1_900);
    receipt = transitionRunTiming(receipt, PHASE.DOWNLOADING, 2_000);
    receipt = transitionRunTiming(receipt, PHASE.PLACING_ARCHIVE, 2_400);
    receipt = finalizeRunTiming(receipt, "finished", 2_500);

    expect(receipt).toMatchObject({
      version: 1,
      started_at_ms: 1_000,
      ended_at_ms: 2_500,
      outcome: "finished",
      active_duration_ms: 1_500,
      unmeasured_gap_ms: 0,
    });
    expect(
      receipt.events.map(({ phase, duration_ms }) => [phase, duration_ms])
    ).toEqual([
      [PHASE.INJECTING, 100],
      [PHASE.GENERATING, 300],
      [PHASE.WAITING_SLOT, 500],
      [PHASE.ADDING_TO_PLAYLIST, 100],
      [PHASE.DOWNLOADING, 400],
      [PHASE.PLACING_ARCHIVE, 100],
    ]);
  });

  it("should exclude stopped wall time and preserve attempts after resume", () => {
    let receipt = beginRunTiming(PHASE.GENERATING, 1_000);
    receipt = finalizeRunTiming(receipt, "stopped", 1_200);
    receipt = resumeRunTiming(receipt, PHASE.GENERATING, 9_000);
    receipt = finalizeRunTiming(receipt, "finished", 9_300);

    expect(receipt.active_duration_ms).toBe(500);
    expect(receipt.sessions).toEqual([
      { started_at_ms: 1_000, ended_at_ms: 1_200 },
      { started_at_ms: 9_000, ended_at_ms: 9_300 },
    ]);
    expect(receipt.events.map(({ attempt }) => attempt)).toEqual([1, 2]);
  });

  it("should preserve retry attempts and terminal error phase", () => {
    let receipt = beginRunTiming(PHASE.ADDING_TO_PLAYLIST, 1_000);
    receipt = transitionRunTiming(
      receipt,
      PHASE.ADDING_TO_PLAYLIST,
      1_100,
      true
    );
    receipt = finalizeRunTiming(receipt, "error", 1_250);

    expect(receipt.events).toEqual([
      {
        phase: PHASE.ADDING_TO_PLAYLIST,
        attempt: 1,
        started_at_ms: 1_000,
        ended_at_ms: 1_100,
        duration_ms: 100,
      },
      {
        phase: PHASE.ADDING_TO_PLAYLIST,
        attempt: 2,
        started_at_ms: 1_100,
        ended_at_ms: 1_250,
        duration_ms: 150,
      },
    ]);
    expect(receipt.outcome).toBe("error");
    expect(receipt.failed_phase).toBe(PHASE.ADDING_TO_PLAYLIST);
  });

  it("should format phase seconds, total and copy-safe JSON without payload data", () => {
    const receipt = finalizeRunTiming(
      beginRunTiming(PHASE.DOWNLOADING, 1_000),
      "finished",
      2_250
    );
    const formatted = formatRunTiming(receipt);

    expect(formatted.lines).toContain("downloading #1: 1.25s");
    expect(formatted.lines).toContain("total: 1.25s");
    expect(formatted.lines).toContain("unmeasured gap: 0.00s");
    expect(JSON.parse(formatted.json)).toEqual(receipt);
    expect(Object.keys(receipt)).not.toEqual(
      expect.arrayContaining(["prompt", "title", "url", "cookie", "token"])
    );
  });
});
