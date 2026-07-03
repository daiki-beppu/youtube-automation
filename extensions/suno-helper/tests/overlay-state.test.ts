// lib/overlay-state.ts の純ロジック回帰テスト (#892 要件2)。
//
// overlay-state は「overlay 位置・最小化状態の永続化」と「viewport 外に保存された位置の
// 内側 clamp 復元」を支える純関数 + chrome.storage I/O を 1 箇所に集約する想定。
// Vitest env は node（chrome モック無し, vitest.config.ts）のため、storage.defineItem を包む
// I/O (read/write) はここでは検証せず、node でテスト可能な純関数のみを tester surface とする
// （既存 resume-state.test.ts / lib/storage.ts が untested なのと同方針）。
//   - clampPosition: overlay box (top-left=position, size) を viewport 内へ収める。要件2 の clamp 復元。
//
// 想定インターフェース（draft step で lib/overlay-state.ts に実装すること）:
//   export interface OverlayState { position: { x: number; y: number }; minimized: boolean; hidden: boolean }
//   export function clampPosition(
//     pos: { x: number; y: number },
//     viewport: { width: number; height: number },
//     size: { width: number; height: number },
//   ): { x: number; y: number }
// clamp 規約: x ∈ [0, max(0, viewport.width - size.width)] / y ∈ [0, max(0, viewport.height - size.height)]。
import { afterEach, describe, expect, it, vi } from "vitest";

import { clampPosition } from "../lib/overlay-state";
import type { OverlayState } from "../lib/overlay-state";

// 代表的な viewport / overlay サイズ。overlay は viewport より十分小さい前提。
const VIEWPORT = { width: 1000, height: 800 };
const SIZE = { width: 200, height: 150 };
// 上記から導かれる clamp 上限。位置は top-left 基準なので右下端は (viewport - size)。
const MAX_X = VIEWPORT.width - SIZE.width; // 800
const MAX_Y = VIEWPORT.height - SIZE.height; // 650

describe("clampPosition: viewport 内に収まる位置 (no-op)", () => {
  it("Given 完全に内側の位置 When clamp Then そのまま返す（移動しない）", () => {
    expect(clampPosition({ x: 300, y: 400 }, VIEWPORT, SIZE)).toEqual({ x: 300, y: 400 });
  });

  it("Given 左上端 (0,0) When clamp Then そのまま返す（境界 inclusive）", () => {
    expect(clampPosition({ x: 0, y: 0 }, VIEWPORT, SIZE)).toEqual({ x: 0, y: 0 });
  });

  it("Given 右下端ちょうど (maxX,maxY) When clamp Then そのまま返す（境界 inclusive）", () => {
    expect(clampPosition({ x: MAX_X, y: MAX_Y }, VIEWPORT, SIZE)).toEqual({ x: MAX_X, y: MAX_Y });
  });
});

describe("clampPosition: viewport 外の位置を内側へ clamp (要件2 復元)", () => {
  it("Given x が負 When clamp Then x=0 へ寄せる（左にはみ出さない）", () => {
    expect(clampPosition({ x: -50, y: 400 }, VIEWPORT, SIZE)).toEqual({ x: 0, y: 400 });
  });

  it("Given y が負 When clamp Then y=0 へ寄せる（上にはみ出さない）", () => {
    expect(clampPosition({ x: 300, y: -120 }, VIEWPORT, SIZE)).toEqual({ x: 300, y: 0 });
  });

  it("Given x が右端超過 When clamp Then x=maxX へ寄せる（右にはみ出さない）", () => {
    expect(clampPosition({ x: 5000, y: 400 }, VIEWPORT, SIZE)).toEqual({ x: MAX_X, y: 400 });
  });

  it("Given y が下端超過 When clamp Then y=maxY へ寄せる（下にはみ出さない）", () => {
    expect(clampPosition({ x: 300, y: 5000 }, VIEWPORT, SIZE)).toEqual({ x: 300, y: MAX_Y });
  });

  it("Given 左上方向に両軸はみ出し When clamp Then (0,0) へ寄せる", () => {
    expect(clampPosition({ x: -999, y: -999 }, VIEWPORT, SIZE)).toEqual({ x: 0, y: 0 });
  });

  it("Given 右下方向に両軸はみ出し When clamp Then (maxX,maxY) へ寄せる", () => {
    expect(clampPosition({ x: 9999, y: 9999 }, VIEWPORT, SIZE)).toEqual({ x: MAX_X, y: MAX_Y });
  });
});

describe("clampPosition: overlay が viewport より大きい退化ケース", () => {
  it("Given overlay 幅 > viewport 幅 When clamp Then x=0（負の上限へ吸い込まれない＝max(0,...)）", () => {
    const bigWidth = { width: 1200, height: 150 };
    expect(clampPosition({ x: 300, y: 100 }, VIEWPORT, bigWidth)).toEqual({ x: 0, y: 100 });
  });

  it("Given overlay 高さ > viewport 高さ When clamp Then y=0", () => {
    const bigHeight = { width: 200, height: 1200 };
    expect(clampPosition({ x: 100, y: 300 }, VIEWPORT, bigHeight)).toEqual({ x: 100, y: 0 });
  });
});

describe("clampPosition: viewport 縮小（resize）後の再 clamp", () => {
  it("Given 旧 viewport では内側だった位置 + 縮小後 viewport When clamp Then 縮小後の内側へ寄せる（要件2 resize clamp）", () => {
    // 以前は (700,600) に置いていたが、ウィンドウが 760x520 まで縮んだ → 内側へ引き戻す。
    const shrunk = { width: 760, height: 520 };
    expect(clampPosition({ x: 700, y: 600 }, shrunk, SIZE)).toEqual({
      x: shrunk.width - SIZE.width, // 560
      y: shrunk.height - SIZE.height, // 370
    });
  });
});

describe("OverlayState: 永続化する状態の形 (要件2)", () => {
  it("Given position/minimized/hidden を持つ state When position を clamp Then OverlayState の position 形と互換である", () => {
    const state: OverlayState = { position: { x: -10, y: 5000 }, minimized: true, hidden: false };

    const clamped = clampPosition(state.position, VIEWPORT, SIZE);

    expect(clamped).toEqual({ x: 0, y: MAX_Y });
    // minimized / hidden は clamp 対象外（位置のみ補正される）。
    expect(state.minimized).toBe(true);
    expect(state.hidden).toBe(false);
  });
});

// --- writeOverlayState: storage 書き込み失敗時の握りつぶし回帰テスト (#1217) ---
// overlay-state.ts は拡張更新後の invalidated context で storage アクセスが失敗するケースを
// try-catch で握りつぶし console.warn のみで続行する。この挙動が維持されることを検証する。
// 上記の純関数テスト群とは異なり storage I/O を mock するため vi.doMock + 動的 import で隔離する。
describe("writeOverlayState: storage 書き込み失敗は throw せず console.warn する", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("Given setValue が reject When writeOverlayState Then throw しない + console.warn が呼ばれる", async () => {
    vi.resetModules();
    vi.doMock("wxt/utils/storage", () => ({
      storage: {
        defineItem: () => ({
          getValue: vi.fn(() => Promise.resolve(null)),
          setValue: vi.fn(() => Promise.reject(new Error("Extension context invalidated"))),
        }),
      },
    }));

    const { writeOverlayState } = await import("../lib/overlay-state");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const state: OverlayState = { position: { x: 100, y: 200 }, minimized: false, hidden: false };

    // throw しないことを検証
    await expect(writeOverlayState(state)).resolves.toBeUndefined();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("overlay state 書き込み失敗"), expect.any(Error));
  });
});
