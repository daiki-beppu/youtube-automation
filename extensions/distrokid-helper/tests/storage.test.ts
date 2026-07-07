// `lib/storage.ts` の契約テスト。
//
// サーバー URL の永続化は @wxt-dev/storage（chrome.storage 必須）で行うため、
// 実 read/write は拡張ランタイム側に委ねる。ここでは serverUrlItem の fallback が
// shared/constants.ts の DEFAULT_URL（SSOT）を参照していることを検証する。
//
// 設計契約:
//   - serverUrlItem.fallback === DEFAULT_URL === "http://youtube-automation.localhost:7873"

import { describe, it, expect } from "vitest";
import { DEFAULT_URL } from "../../shared/constants";

describe("DEFAULT_URL (shared constants)", () => {
  it("yt-collection-serve の既定ポート 7873 を指す", () => {
    expect(DEFAULT_URL).toBe("http://youtube-automation.localhost:7873");
  });
});
