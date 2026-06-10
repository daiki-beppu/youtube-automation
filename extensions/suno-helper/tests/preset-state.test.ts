// lib/preset-state.ts の純ロジック回帰テスト (#875)。
//
// preset-state は「速度設定の解決・jitter 算出・永続化」を集約する。Vitest env は node
// (chrome モック無し, vitest.config.ts) のため、storage.defineItem を包む I/O
// (readSpeedPresetId / writeSpeedPresetId) はここでは検証せず、node でテスト可能な純関数のみを
// tester surface とする（既存 resume-state.test.ts / storage.ts が storage I/O を untested とする
// のと同方針）。
//   - DEFAULT_SPEED_PRESET_ID: 既定 preset（要件2: デフォルトは Balanced）
//   - resolveSpeedPreset: id → SpeedPreset の解決（不正 id は fail-loud で throw）。要件3
//   - applyJitter: baseMs + (random()*2-1)*jitterMs の純関数。random を DI して min/max を pin。要件3/7
//
// 契約 (draft が実装する public API, suno-helper/lib/preset-state.ts):
//   type SpeedPresetId = "fast" | "balanced" | "safe";
//   const DEFAULT_SPEED_PRESET_ID: SpeedPresetId;  // = "balanced"
//   function resolveSpeedPreset(id: SpeedPresetId): SpeedPreset;  // = SPEED_PRESETS[id]、不正 id は throw
//   function applyJitter(baseMs: number, jitterMs: number, random?: () => number): number;
//     = baseMs + (random()*2-1)*jitterMs。random 既定は Math.random（content から省略呼び出し）。
import { describe, expect, it } from "vitest";

import { SPEED_PRESETS } from "../../shared/constants";
import { applyJitter, DEFAULT_SPEED_PRESET_ID, resolveSpeedPreset, type SpeedPresetId } from "../lib/preset-state";

describe("DEFAULT_SPEED_PRESET_ID: 既定 preset (要件2)", () => {
  it("Given 定数 When 読む Then balanced である（デフォルトは Balanced）", () => {
    expect(DEFAULT_SPEED_PRESET_ID).toBe("balanced");
  });
});

describe("resolveSpeedPreset: id → SpeedPreset の解決 (要件3)", () => {
  it.each(["fast", "balanced", "safe"] as const)("Given id '%s' When 解決する Then SPEED_PRESETS[id] を返す", (id) => {
    expect(resolveSpeedPreset(id)).toEqual(SPEED_PRESETS[id]);
  });

  it("Given 不正な id When 解決する Then throw する（fail-loud, silent fallback しない）", () => {
    // 設定取り違えを silent に既定 preset へ落とさず、即エラーにする。
    expect(() => resolveSpeedPreset("turbo" as SpeedPresetId)).toThrow();
  });
});

describe("applyJitter: jitter 範囲の算出 (要件3/7)", () => {
  describe("balanced (base=10000, jitter=±3000) → 受け入れ基準 7-13s", () => {
    it("Given random=()=>0 When 算出 Then min = base - jitter = 7000", () => {
      expect(applyJitter(10000, 3000, () => 0)).toBe(7000);
    });

    it("Given random=()=>1 When 算出 Then max = base + jitter = 13000", () => {
      expect(applyJitter(10000, 3000, () => 1)).toBe(13000);
    });

    it("Given random=()=>0.5 When 算出 Then 中央 = base = 10000（jitter 0 寄与）", () => {
      expect(applyJitter(10000, 3000, () => 0.5)).toBe(10000);
    });
  });

  describe("safe (base=20000, jitter=±5000) → 受け入れ基準 15-25s", () => {
    it("Given random=()=>0 When 算出 Then min = 15000", () => {
      expect(applyJitter(20000, 5000, () => 0)).toBe(15000);
    });

    it("Given random=()=>1 When 算出 Then max = 25000", () => {
      expect(applyJitter(20000, 5000, () => 1)).toBe(25000);
    });
  });

  describe("fast (jitter=0) → 固定値（現状と同等）", () => {
    it.each([0, 0.5, 1])("Given jitter=0, random=()=>%s When 算出 Then random によらず base を返す", (r) => {
      expect(applyJitter(3000, 0, () => r)).toBe(3000);
    });
  });

  describe("既定 random (Math.random) → jitter 域に収まる", () => {
    // content.ts は applyJitter(preset.interCreateDelayMs, preset.jitterMs) を random 省略で呼ぶ
    // （production 呼び出しは random を渡さない＝デフォルト引数の許容ケース）。
    it("Given random 省略 When safe preset 値で多数サンプル Then 全て 15000〜25000ms に収まる", () => {
      for (let i = 0; i < 1000; i++) {
        const delay = applyJitter(20000, 5000);
        expect(delay).toBeGreaterThanOrEqual(15000);
        expect(delay).toBeLessThanOrEqual(25000);
      }
    });

    it("Given random 省略 When balanced preset 値で多数サンプル Then 全て 7000〜13000ms に収まる", () => {
      for (let i = 0; i < 1000; i++) {
        const delay = applyJitter(10000, 3000);
        expect(delay).toBeGreaterThanOrEqual(7000);
        expect(delay).toBeLessThanOrEqual(13000);
      }
    });
  });

  it("Given SPEED_PRESETS.safe を直接渡す When applyJitter Then preset 値から 15000〜25000ms を生成する", () => {
    // preset → applyJitter の配線（content.ts が runAll で行う計算）を preset 値そのもので検証する。
    const preset = SPEED_PRESETS.safe;
    expect(applyJitter(preset.interCreateDelayMs, preset.jitterMs, () => 0)).toBe(15000);
    expect(applyJitter(preset.interCreateDelayMs, preset.jitterMs, () => 1)).toBe(25000);
  });
});
