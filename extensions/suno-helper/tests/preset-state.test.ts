// lib/preset-state.ts の jitter 純関数回帰テスト。
// 実行モード選択と preset 永続化は #1573 で廃止済み。
import { describe, expect, it } from "vitest";

import { BALANCED_RUN_PACING } from "../../shared/constants";
import { applyJitter } from "../lib/preset-state";

describe("applyJitter: Balanced 固定ペーシングの jitter 範囲", () => {
  it("Given random=()=>0 When BALANCED_RUN_PACING で算出 Then min = 3000", () => {
    expect(applyJitter(BALANCED_RUN_PACING.interCreateDelayMs, BALANCED_RUN_PACING.jitterMs, () => 0)).toBe(3000);
  });

  it("Given random=()=>1 When BALANCED_RUN_PACING で算出 Then max = 9000", () => {
    expect(applyJitter(BALANCED_RUN_PACING.interCreateDelayMs, BALANCED_RUN_PACING.jitterMs, () => 1)).toBe(9000);
  });

  it("Given random=()=>0.5 When BALANCED_RUN_PACING で算出 Then 中央 = 6000", () => {
    expect(applyJitter(BALANCED_RUN_PACING.interCreateDelayMs, BALANCED_RUN_PACING.jitterMs, () => 0.5)).toBe(6000);
  });

  it("Given random 省略 When BALANCED_RUN_PACING で多数サンプル Then 全て 3000〜9000ms に収まる", () => {
    for (let i = 0; i < 1000; i++) {
      const delay = applyJitter(BALANCED_RUN_PACING.interCreateDelayMs, BALANCED_RUN_PACING.jitterMs);
      expect(delay).toBeGreaterThanOrEqual(3000);
      expect(delay).toBeLessThanOrEqual(9000);
    }
  });
});
