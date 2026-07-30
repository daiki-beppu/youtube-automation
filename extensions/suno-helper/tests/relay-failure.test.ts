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

import {
  EXTENSION_RELOAD_REQUIRED_MESSAGE,
  describeRelayFailure,
  formatRunError,
  formatStopError,
  isExtensionContextInvalidatedError,
} from "../components/runner-errors";

describe("describeRelayFailure: content script 未注入（想定内）は info に落とす (#937)", () => {
  it("Given missing-receiver エラー When 整形 Then level=info + ハードリロード案内を含む", () => {
    const { level, text } = describeRelayFailure(
      "toggleOverlay",
      "Could not establish connection. Receiving end does not exist."
    );
    expect(level).toBe("info");
    expect(text).toMatch(/toggleOverlay/);
    expect(text).toMatch(/ハードリロード/);
  });

  it.each([
    "Receiving end does not exist",
    "could not establish connection",
    "RECEIVING END DOES NOT EXIST",
  ])(
    "Given 大文字小文字ゆらぎ %j When 整形 Then level=info（isContentScriptMissingError の i フラグ経路）",
    (message) => {
      expect(describeRelayFailure("toggleOverlay", message).level).toBe("info");
    }
  );
});

describe("describeRelayFailure: 想定外エラーは warn で残す (#937)", () => {
  it("Given 一般エラー When 整形 Then level=warn + action とメッセージを含む", () => {
    const { level, text } = describeRelayFailure(
      "toggleOverlay",
      "No tab with id: 123"
    );
    expect(level).toBe("warn");
    expect(text).toMatch(/toggleOverlay/);
    expect(text).toMatch(/No tab with id: 123/);
  });

  it("Given 空メッセージ When 整形 Then level=warn（missing-receiver 扱いにしない）", () => {
    expect(describeRelayFailure("toggleOverlay", "").level).toBe("warn");
  });
});

describe("拡張更新後の context invalidated を再読み込み案内へ集約する (#1718)", () => {
  it.each([
    "Extension context invalidated.",
    "Error: No response at sendMessage",
    "Error: 'wxt/storage' must be loaded in a web extension environment",
  ])("Given %j When 判定 Then 更新後エラーとして扱う", (message) => {
    expect(isExtensionContextInvalidatedError(message)).toBe(true);
    expect(formatRunError(message)).toContain(
      EXTENSION_RELOAD_REQUIRED_MESSAGE
    );
  });
});

describe("run/stop error formatter の完全な利用者向け文言 (#2902)", () => {
  it.each([
    [
      "通常エラー",
      "Advanced tab is closed",
      "開始失敗: Advanced tab is closed\nSuno の Advanced タブを開き、Lyrics mode を確認してから実行してください。",
      "停止リクエスト失敗: Advanced tab is closed",
    ],
    [
      "content missing",
      "Could not establish connection. Receiving end does not exist.",
      "開始失敗: Could not establish connection. Receiving end does not exist.\n拡張が更新されました。Suno タブをハードリロードしてから操作してください。（⌘+Shift+R / Ctrl+Shift+R）",
      "停止リクエスト失敗: Could not establish connection. Receiving end does not exist.\n拡張が更新されました。Suno タブをハードリロードしてから操作してください。（⌘+Shift+R / Ctrl+Shift+R）",
    ],
    [
      "context invalidated",
      "Extension context invalidated.",
      "開始失敗: Extension context invalidated.\n拡張が更新されました。Suno タブをハードリロードしてから操作してください。（⌘+Shift+R / Ctrl+Shift+R）",
      "停止リクエスト失敗: Extension context invalidated.\n拡張が更新されました。Suno タブをハードリロードしてから操作してください。（⌘+Shift+R / Ctrl+Shift+R）",
    ],
  ])("%s", (_label, message, runText, stopText) => {
    expect(formatRunError(message)).toBe(runText);
    expect(formatStopError(message)).toBe(stopText);
  });
});
