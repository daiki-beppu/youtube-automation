// lib/overlay-state.ts の overlay 表示 toggle 純ロジック回帰テスト (#897)。
//
// #892 (PR #895) の overlay 実装は `if (hidden) return null;` で hidden=true 時に OverlayShell を
// unmount していたため、toggleOverlay リスナーごと消滅し「一度 hide すると復帰不能」な片方向 bug を
// 生んでいた (#897)。修正は (1) unmount せず CSS で隠す, (2) hidden の状態遷移を純関数化して
// toggleOverlay 受信時の hidden:true → false 遷移を機械担保する、の 2 点。
//
// Vitest env は node（chrome モック無し, vitest.config.ts）のため、storage.defineItem を包む
// I/O (read/write) は検証せず、node でテスト可能な純関数のみを tester surface とする
// （既存 overlay-state.test.ts / resume-state.test.ts と同方針）。
//   - toggleHidden: toggleOverlay 受信時の hidden 反転。position/minimized は保持（要件2/4/5）。
//   - hiddenStyle: hidden を unmount でなく CSS（display）で表現（要件1/3）。
//
// 想定インターフェース（draft step で lib/overlay-state.ts に実装すること）:
//   export function toggleHidden(state: OverlayState): OverlayState
//   export function hiddenStyle(hidden: boolean): { display: "none" | "block" }
import { describe, expect, it } from "vitest";

import { hiddenStyle, toggleHidden } from "../lib/overlay-state";
import type { OverlayState } from "../lib/overlay-state";

function makeOverlayState(overrides: Partial<OverlayState> = {}): OverlayState {
  return {
    position: { x: 230, y: 2 },
    minimized: false,
    hidden: false,
    ...overrides,
  };
}

describe("toggleHidden: toggleOverlay 受信時の hidden 反転 (要件2/5)", () => {
  it("Given hidden=true When toggle Then hidden=false（拡張アイコンで復帰する経路 = #897 の本丸）", () => {
    const state = makeOverlayState({ hidden: true });
    expect(toggleHidden(state).hidden).toBe(false);
  });

  it("Given hidden=false When toggle Then hidden=true（visible → hide）", () => {
    const state = makeOverlayState({ hidden: false });
    expect(toggleHidden(state).hidden).toBe(true);
  });

  it("Given 任意 state When toggle 2 回 Then 元の hidden に戻る（反転の冪等性）", () => {
    const state = makeOverlayState({ hidden: true });
    expect(toggleHidden(toggleHidden(state)).hidden).toBe(true);
  });
});

describe("toggleHidden: hidden 以外のフィールド保持 (要件4 回帰防止)", () => {
  it("Given position/minimized を持つ state When toggle Then position は保持される（位置永続化に回帰なし）", () => {
    const state = makeOverlayState({
      position: { x: 230, y: 2 },
      hidden: true,
    });
    expect(toggleHidden(state).position).toEqual({ x: 230, y: 2 });
  });

  it("Given minimized=true When toggle Then minimized は保持される（最小化状態に回帰なし）", () => {
    const state = makeOverlayState({ minimized: true, hidden: true });
    expect(toggleHidden(state).minimized).toBe(true);
  });

  it("Given hidden=true 以外フル指定 When toggle Then hidden だけが反転し他は完全一致", () => {
    const state = makeOverlayState({
      position: { x: 11, y: 22 },
      minimized: true,
      hidden: true,
    });
    expect(toggleHidden(state)).toEqual({
      position: { x: 11, y: 22 },
      minimized: true,
      hidden: false,
    });
  });
});

describe("toggleHidden: 純関数性（入力非破壊）", () => {
  it("Given state When toggle Then 入力 state を変異しない（新オブジェクトを返す）", () => {
    const state = makeOverlayState({ hidden: true });

    toggleHidden(state);

    expect(state.hidden).toBe(true);
  });
});

describe("hiddenStyle: hidden を unmount でなく CSS で表現 (要件1/3)", () => {
  it("Given hidden=true When style 算出 Then display:none（DOM に残しつつ非表示 = unmount しない）", () => {
    expect(hiddenStyle(true)).toEqual({ display: "none" });
  });

  it("Given hidden=false When style 算出 Then display:block（visible・pointer 干渉なし）", () => {
    expect(hiddenStyle(false)).toEqual({ display: "block" });
  });
});
