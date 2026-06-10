// overlay ⇄ runner の background 中継ロジック回帰テスト (#892)。
//
// overlay を content script 化したことで `useSunoRunner` は run / stop / queryProgress / progress を
// tabId 指定せず background 宛に送るよう変更された。background は relayTabId で送信元タブを解決し、
// 同一タブの runner content へ転送する。この中継先解決が崩れると overlay 上の run/stop/再開/進捗復元が
// 実機で非機能になる（AI-NEW-useSunoRunner-L65 の回帰防止）。
//
// Vitest env は node（chrome モック無し, vitest.config.ts）。webext-core / browser API そのものではなく、
// 中継の意思決定を担う純関数 relayTabId を tester surface とする（既存の純関数抽出テスト方針に倣う）。
import { describe, expect, it } from "vitest";

import { relayTabId, requireRelayTab } from "../lib/overlay-relay";

describe("relayTabId: content script 起源は同一タブへ中継する", () => {
  it("Given overlay (content script) sender (tab.id=42) When relayTabId Then 同一タブ 42 を返す", () => {
    // overlay の no-tabId メッセージは送信元と同一タブ（runner content が常駐する Suno タブ）へ転送される。
    expect(relayTabId({ tab: { id: 42 } })).toBe(42);
  });

  it("Given runner (content script) sender (tab.id=7) When relayTabId Then 同一タブ 7 を返す（progress 折返し）", () => {
    expect(relayTabId({ tab: { id: 7 } })).toBe(7);
  });
});

describe("relayTabId: tab を持たない送信元は中継しない（loop 防止）", () => {
  it("Given tab フィールド無し sender When relayTabId Then null（runtime 再送ループを防ぐ）", () => {
    // background 自身 / 廃止済み popup など content script でない送信元。素通しすると no-tabId 再送で
    // runtime へ戻り無限ループになるため転送しない。
    expect(relayTabId({})).toBeNull();
  });

  it("Given tab はあるが id 欠落 sender When relayTabId Then null", () => {
    expect(relayTabId({ tab: {} })).toBeNull();
  });

  it("Given tab.id が number でない sender When relayTabId Then null", () => {
    expect(relayTabId({ tab: { id: undefined } })).toBeNull();
  });
});

// run / stop / queryProgress の3中継ハンドラが「null なら throw」骨格を逐語コピペしていた DRY 違反
// (ARCH-NEW-background-L26) の再発防止。共通化した requireRelayTab に境界判定を1箇所へ集約したことを担保する。
describe("requireRelayTab: 応答必須の中継は中継先タブを fail-loud で要求する", () => {
  it("Given content script 起源 sender (tab.id=42) When requireRelayTab Then 同一タブ 42 を返す", () => {
    expect(requireRelayTab({ tab: { id: 42 } }, "run")).toBe(42);
  });

  it("Given tab を持たない sender When requireRelayTab Then action 名を含めて throw する", () => {
    // content script 起源でない＝転送先が無い場合は握りつぶさず throw（fail-loud）。
    expect(() => requireRelayTab({}, "queryProgress")).toThrow(/queryProgress/);
  });

  it("Given tab.id 欠落 sender When requireRelayTab Then throw する", () => {
    expect(() => requireRelayTab({ tab: {} }, "stop")).toThrow(
      "stop の中継先タブを特定できません（content script 起源ではありません）。",
    );
  });
});
