// lib/preset-state.ts の jitter 純関数回帰テスト。
// speed preset 永続化は #1573 で廃止済み。run mode の既定値だけ #1586 で保持する。
import { beforeEach, describe, expect, it, vi } from "vitest";

const runModeStorage = vi.hoisted(() => ({
  getValue: vi.fn(),
  setValue: vi.fn(),
  defineItem: vi.fn(),
}));

vi.mock("wxt/utils/storage", () => ({
  storage: {
    defineItem: runModeStorage.defineItem.mockReturnValue(runModeStorage),
  },
}));

import { BALANCED_RUN_PACING } from "../../shared/constants";
import {
  applyJitter,
  DEFAULT_RUN_MODE_ID,
  readRunModeId,
  writeRunModeId,
} from "../lib/preset-state";

describe("DEFAULT_RUN_MODE_ID: 既定の投入方式 (#1586)", () => {
  it("Given 定数 When 読む Then serial である（既存の直列実行を既定として維持する）", () => {
    expect(DEFAULT_RUN_MODE_ID).toBe("serial");
  });
});

describe("run mode storage I/O (#2906)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    runModeStorage.getValue.mockResolvedValue(DEFAULT_RUN_MODE_ID);
    runModeStorage.setValue.mockResolvedValue(undefined);
  });

  it("初回 read は正しい key/fallback の遅延 item から既定値を返す", async () => {
    await expect(readRunModeId()).resolves.toBe("serial");
    expect(runModeStorage.defineItem).toHaveBeenCalledWith(
      "local:sunoRunMode",
      { fallback: DEFAULT_RUN_MODE_ID }
    );
  });

  it("write 後の read は保存値を直接返す", async () => {
    runModeStorage.getValue.mockResolvedValueOnce("queue");

    await writeRunModeId("queue");
    await expect(readRunModeId()).resolves.toBe("queue");

    expect(runModeStorage.setValue).toHaveBeenCalledWith("queue");
  });
});

describe("applyJitter: Balanced 固定ペーシングの jitter 範囲", () => {
  it("Given random=()=>0 When BALANCED_RUN_PACING で算出 Then min = 3000", () => {
    expect(
      applyJitter(
        BALANCED_RUN_PACING.interCreateDelayMs,
        BALANCED_RUN_PACING.jitterMs,
        () => 0
      )
    ).toBe(3000);
  });

  it("Given random=()=>1 When BALANCED_RUN_PACING で算出 Then max = 9000", () => {
    expect(
      applyJitter(
        BALANCED_RUN_PACING.interCreateDelayMs,
        BALANCED_RUN_PACING.jitterMs,
        () => 1
      )
    ).toBe(9000);
  });

  it("Given random=()=>0.5 When BALANCED_RUN_PACING で算出 Then 中央 = 6000", () => {
    expect(
      applyJitter(
        BALANCED_RUN_PACING.interCreateDelayMs,
        BALANCED_RUN_PACING.jitterMs,
        () => 0.5
      )
    ).toBe(6000);
  });

  it("Given random 省略 When BALANCED_RUN_PACING で多数サンプル Then 全て 3000〜9000ms に収まる", () => {
    for (let i = 0; i < 1000; i++) {
      const delay = applyJitter(
        BALANCED_RUN_PACING.interCreateDelayMs,
        BALANCED_RUN_PACING.jitterMs
      );
      expect(delay).toBeGreaterThanOrEqual(3000);
      expect(delay).toBeLessThanOrEqual(9000);
    }
  });
});
