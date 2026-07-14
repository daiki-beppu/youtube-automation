import { describe, expect, it } from "vitest";

import { MAX_YIELD_RETRY } from "../../shared/constants";
import { checkDuration, decideDurationAttempt, evaluateClips, shouldRetryDurationOutlier } from "../lib/yield-guard";
import type { DurationFilter } from "../../shared/api";

const FILTER: DurationFilter = { min_sec: 120, max_sec: 300 };

describe("yield-guard: duration 判定", () => {
  it("Given duration が閾値内 When checkDuration Then true を返す", () => {
    expect(checkDuration(120, FILTER)).toBe(true);
    expect(checkDuration(240, FILTER)).toBe(true);
    expect(checkDuration(300, FILTER)).toBe(true);
  });

  it("Given duration が閾値外 When checkDuration Then false を返す", () => {
    expect(checkDuration(119.9, FILTER)).toBe(false);
    expect(checkDuration(300.1, FILTER)).toBe(false);
  });

  it("Given 非有限値 When checkDuration Then false を返す", () => {
    expect(checkDuration(Number.NaN, FILTER)).toBe(false);
    expect(checkDuration(Number.POSITIVE_INFINITY, FILTER)).toBe(false);
  });
});

describe("yield-guard: clips 分類", () => {
  it("Given duration undefined When evaluateClips Then feed 未取得として NG に分類する", () => {
    expect(evaluateClips([{ id: "clip-a" }, { id: "clip-b", duration: 180 }], FILTER)).toEqual({
      ok: ["clip-b"],
      ng: ["clip-a"],
    });
  });

  it("Given 両方 OK When evaluateClips Then ok に 2 clip を分類する", () => {
    expect(
      evaluateClips(
        [
          { id: "clip-a", duration: 180 },
          { id: "clip-b", duration: 240 },
        ],
        FILTER,
      ),
    ).toEqual({
      ok: ["clip-a", "clip-b"],
      ng: [],
    });
  });

  it("Given 両方 NG When evaluateClips Then ng に 2 clip を分類する", () => {
    expect(
      evaluateClips(
        [
          { id: "clip-a", duration: 90 },
          { id: "clip-b", duration: 360 },
        ],
        FILTER,
      ),
    ).toEqual({
      ok: [],
      ng: ["clip-a", "clip-b"],
    });
  });

  it("Given 片方だけ OK When evaluateClips Then ok/ng に分けて分類する", () => {
    expect(
      evaluateClips(
        [
          { id: "clip-a", duration: 180 },
          { id: "clip-b", duration: 360 },
        ],
        FILTER,
      ),
    ).toEqual({
      ok: ["clip-a"],
      ng: ["clip-b"],
    });
  });
});

describe("yield-guard: retry 上限判定", () => {
  it("Given retry 回数 When 上限判定 Then MAX_YIELD_RETRY 未満だけ true を返す", () => {
    expect(MAX_YIELD_RETRY).toBe(2);
    expect(shouldRetryDurationOutlier({ attemptCount: 0 })).toBe(true);
    expect(shouldRetryDurationOutlier({ attemptCount: 1 })).toBe(true);
    expect(shouldRetryDurationOutlier({ attemptCount: 2 })).toBe(false);
  });

  it("Given custom max retry When retry 判定 Then 上限到達で false を返す", () => {
    expect(shouldRetryDurationOutlier({ attemptCount: 2, maxRetry: 3 })).toBe(true);
    expect(shouldRetryDurationOutlier({ attemptCount: 3, maxRetry: 3 })).toBe(false);
  });
});

describe("yield-guard: attempt 状態決定", () => {
  it("Given OFF とOK/NG混在 When decide Then 警告付きで全clipを採用する", () => {
    expect(
      decideDurationAttempt({
        clipIds: ["clip-ok", "clip-ng"],
        result: { kind: "evaluated", evaluation: { ok: ["clip-ok"], ng: ["clip-ng"] } },
        filter: FILTER,
        policy: { kind: "retain" },
        attemptCount: 0,
      }),
    ).toEqual({
      kind: "accept",
      acceptedClipIds: ["clip-ok", "clip-ng"],
      warning: "duration guard NG (120-300s): clip-ng; 再生成 OFF のため全 clip を採用候補として保持します",
    });
  });

  it("Given ON と全NG When retry上限前後 Then retryからfailへ遷移する", () => {
    const base = {
      clipIds: ["clip-ng"],
      result: { kind: "evaluated" as const, evaluation: { ok: [], ng: ["clip-ng"] } },
      filter: FILTER,
      policy: { kind: "regenerate" as const },
    };
    expect(decideDurationAttempt({ ...base, attemptCount: 1 })).toEqual({
      kind: "retry",
      message: "duration guard NG (120-300s): clip-ng",
    });
    expect(decideDurationAttempt({ ...base, attemptCount: 2 })).toEqual({
      kind: "fail",
      message: "duration guard NG (120-300s): clip-ng",
      reason: "outlier",
    });
  });

  it("Given duration評価失敗 When decide Then ONはretryしOFFはfailする", () => {
    const base = {
      clipIds: ["clip-a"],
      result: { kind: "evaluation-failed" as const, message: "feed unavailable" },
      filter: FILTER,
      attemptCount: 0,
    };
    expect(decideDurationAttempt({ ...base, policy: { kind: "regenerate" } })).toEqual({
      kind: "retry",
      message: "feed unavailable",
    });
    expect(decideDurationAttempt({ ...base, policy: { kind: "retain" } })).toEqual({
      kind: "fail",
      message: "feed unavailable",
      reason: "evaluation",
    });
  });
});
