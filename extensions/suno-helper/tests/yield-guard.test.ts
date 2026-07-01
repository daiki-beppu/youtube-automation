import { describe, expect, it } from "vitest";

import { MAX_YIELD_RETRY } from "../../shared/constants";
import { checkDuration, evaluateClips, shouldRetry } from "../lib/yield-guard";

describe("yield-guard: duration 判定", () => {
  it("Given 既定範囲 60-300s When duration を判定する Then 範囲内だけ OK", () => {
    expect(checkDuration(60, { minSec: 60, maxSec: 300 })).toEqual({ ok: true, durationSec: 60 });
    expect(checkDuration(300, { minSec: 60, maxSec: 300 })).toEqual({ ok: true, durationSec: 300 });
    expect(checkDuration(59, { minSec: 60, maxSec: 300 })).toEqual({
      ok: false,
      durationSec: 59,
      reason: "too-short",
    });
    expect(checkDuration(301, { minSec: 60, maxSec: 300 })).toEqual({
      ok: false,
      durationSec: 301,
      reason: "too-long",
    });
    expect(checkDuration(undefined, { minSec: 60, maxSec: 300 })).toEqual({
      ok: false,
      reason: "missing-duration",
    });
  });

  it("Given 2 clips 中 1 clip が OK When evaluateClips Then acceptedClipIds に OK だけを返す", () => {
    const result = evaluateClips([
      { id: "short", durationSec: 30 },
      { id: "ok", durationSec: 180 },
    ]);

    expect(result.acceptedClipIds).toEqual(["ok"]);
    expect(result.rejectedClipIds).toEqual(["short"]);
  });

  it("Given retryCount When shouldRetry Then MAX_YIELD_RETRY 未満だけ retry 可", () => {
    expect(shouldRetry(0)).toBe(true);
    expect(shouldRetry(MAX_YIELD_RETRY - 1)).toBe(true);
    expect(shouldRetry(MAX_YIELD_RETRY)).toBe(false);
  });
});
