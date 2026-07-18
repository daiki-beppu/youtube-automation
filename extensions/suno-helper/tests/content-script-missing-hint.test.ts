// useSunoRunner の content script 未注入エラー検知 + メッセージ整形の回帰テスト。
// 拡張をリロードした後 Suno タブをハードリロードしないと出る Chrome 標準エラー
// (`Could not establish connection. Receiving end does not exist.`) を検知し、
// 対処法（⌘+Shift+R）を popup のメッセージに含めるロジックの担保。
import { describe, expect, it } from "vitest";

import {
  formatRunError,
  formatStopError,
  isContentScriptMissingError,
} from "../components/runner-errors";

describe("isContentScriptMissingError", () => {
  it.each([
    ["Could not establish connection. Receiving end does not exist.", true],
    ["Receiving end does not exist", true],
    ["could not establish connection", true],
    ["RECEIVING END DOES NOT EXIST", true],
    ["yt-collection-serve に接続できません", false],
    ["fetch failed", false],
    ["", false],
  ])("Given message %j When 判定 Then %s", (message, expected) => {
    expect(isContentScriptMissingError(message)).toBe(expected);
  });
});

describe("formatRunError", () => {
  it("Given content-script-missing error When formatRunError Then ハードリロード案内を含む", () => {
    const text = formatRunError(
      "Could not establish connection. Receiving end does not exist."
    );
    expect(text).toMatch(/ハードリロード/);
    expect(text).toMatch(/⌘\+Shift\+R/);
  });

  it("Given 他のエラー When formatRunError Then Advanced と Lyrics mode の案内を返す", () => {
    const text = formatRunError("アクティブなタブが見つかりません。");
    expect(text).toMatch(/Advanced タブ/);
    expect(text).toMatch(/Lyrics mode/);
    expect(text).not.toMatch(/ハードリロード/);
  });
});

describe("formatStopError", () => {
  it("Given content-script-missing error When formatStopError Then ハードリロード案内を含む", () => {
    const text = formatStopError("Receiving end does not exist");
    expect(text).toMatch(/ハードリロード/);
    expect(text).toMatch(/⌘\+Shift\+R/);
  });

  it("Given 他のエラー When formatStopError Then 案内追記なし（従来挙動）", () => {
    const text = formatStopError("network error");
    expect(text).toBe("停止リクエスト失敗: network error");
  });
});
