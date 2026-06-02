// popup ⇄ content script ⇄ server 間の契約文字列を固定する回帰テスト。
// 旧実装 `extensions/suno-helper/constants.js` の値を WXT 移行後も不変に保つ。
// これらは yt-collection-serve (#692/#698) との互換契約であり、変更すると
// サーバー側 (`/suno/prompts.json`) と整合しなくなる。
import { describe, expect, it } from "vitest";

import { DEFAULT_URL, PHASE, PROMPTS_ROUTE, STORAGE_KEY } from "../../shared/constants";

describe("shared/constants: サーバー互換の契約値", () => {
  it("Given 移行後の定数 When STORAGE_KEY を読む Then 旧実装と同じ key 名である", () => {
    expect(STORAGE_KEY).toBe("sunoServerUrl");
  });

  it("Given 移行後の定数 When PROMPTS_ROUTE を読む Then #698 のサブパス分離後ルートである", () => {
    // SSOT: src/youtube_automation/scripts/suno_artifacts.py SUNO_PROMPTS_ROUTE
    expect(PROMPTS_ROUTE).toBe("/suno/prompts.json");
  });

  it("Given 移行後の定数 When DEFAULT_URL を読む Then 旧実装と同じローカル配信元である", () => {
    expect(DEFAULT_URL).toBe("http://localhost:7873");
  });
});

describe("shared/constants: 進捗フェーズ (PHASE)", () => {
  it("Given PHASE When 全フェーズを読む Then 旧実装の文字列値を保持する", () => {
    expect(PHASE).toEqual({
      INJECTING: "injecting",
      GENERATING: "generating",
      DONE: "done",
      FINISHED: "finished",
      STOPPED: "stopped",
      ERROR: "error",
    });
  });
});
