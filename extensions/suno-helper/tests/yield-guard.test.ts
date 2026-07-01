import { describe, expect, it } from "vitest";

import { MAX_YIELD_RETRY } from "../../shared/constants";
import { checkDuration, evaluateClips, shouldRetry } from "../lib/yield-guard";
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

  it("Given 片側だけの閾値 When checkDuration Then 指定された境界だけを判定する", () => {
    expect(checkDuration(60, { min_sec: 60 })).toBe(true);
    expect(checkDuration(59.9, { min_sec: 60 })).toBe(false);
    expect(checkDuration(300, { max_sec: 300 })).toBe(true);
    expect(checkDuration(300.1, { max_sec: 300 })).toBe(false);
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

describe("yield-guard: retry 判定", () => {
  it("Given default max retry When shouldRetry Then MAX_YIELD_RETRY 未満だけ true を返す", () => {
    expect(MAX_YIELD_RETRY).toBe(2);
    expect(shouldRetry(0)).toBe(true);
    expect(shouldRetry(1)).toBe(true);
    expect(shouldRetry(2)).toBe(false);
  });

  it("Given custom max retry When shouldRetry Then 上限到達で false を返す", () => {
    expect(shouldRetry(2, 3)).toBe(true);
    expect(shouldRetry(3, 3)).toBe(false);
  });
});
