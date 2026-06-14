// background の fire-and-forget 中継（toggleOverlay / progress）が reject したときのログ整形回帰テスト (#937)。
//
// background.ts は `void sendMessage(...)` で Promise を投げ捨てていたため、content script 未注入の
// タブ（suno.com 以外でのアイコンクリック / 拡張リロード後の stale タブ）で
// `Uncaught (in promise) Error: Could not establish connection. Receiving end does not exist.`
// が未処理 rejection として chrome://extensions のエラーバッジに蓄積されていた。
// 修正は catch して describeRelayFailure でログ level と文言を決めて消費する。
// 本テストはその純関数部分（components/runner-errors.ts::describeRelayFailure）を担保する
// （Vitest env は node・chrome モック無しのため、既存 content-script-missing-hint.test.ts と同方針）。
import { describe, expect, it } from "vitest";

import { describeRelayFailure } from "../components/runner-errors";

describe("describeRelayFailure: content script 未注入（想定内）は info に落とす (#937)", () => {
  it("Given missing-receiver エラー When 整形 Then level=info + ハードリロード案内を含む", () => {
    const { level, text } = describeRelayFailure(
      "toggleOverlay",
      "Could not establish connection. Receiving end does not exist.",
    );
    expect(level).toBe("info");
    expect(text).toMatch(/toggleOverlay/);
    expect(text).toMatch(/ハードリロード/);
  });

  it.each(["Receiving end does not exist", "could not establish connection", "RECEIVING END DOES NOT EXIST"])(
    "Given 大文字小文字ゆらぎ %j When 整形 Then level=info（isContentScriptMissingError の i フラグ経路）",
    (message) => {
      expect(describeRelayFailure("toggleOverlay", message).level).toBe("info");
    },
  );
});

describe("describeRelayFailure: 想定外エラーは warn で残す (#937)", () => {
  it("Given 一般エラー When 整形 Then level=warn + action とメッセージを含む", () => {
    const { level, text } = describeRelayFailure("toggleOverlay", "No tab with id: 123");
    expect(level).toBe("warn");
    expect(text).toMatch(/toggleOverlay/);
    expect(text).toMatch(/No tab with id: 123/);
  });

  it("Given 空メッセージ When 整形 Then level=warn（missing-receiver 扱いにしない）", () => {
    expect(describeRelayFailure("toggleOverlay", "").level).toBe("warn");
  });
});
