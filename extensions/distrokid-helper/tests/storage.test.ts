// `lib/storage.ts` の契約テスト。
//
// サーバー URL の永続化は @wxt-dev/storage（chrome.storage 必須）で行うため、
// 実 read/write は拡張ランタイム側に委ねる。ここでは popup の初期値となる
// 既定サーバー URL の契約を固定する（suno-helper の DEFAULT_URL と対称）。
//
// 設計契約（draft が実装する前提）:
//   - DEFAULT_SERVER_URL: yt-collection-serve の DEFAULT_PORT=7873 と一致

import { describe, it, expect } from "vitest";
import { DEFAULT_SERVER_URL } from "../lib/storage";

describe("DEFAULT_SERVER_URL", () => {
  it("yt-collection-serve の既定ポート 7873 を指す", () => {
    expect(DEFAULT_SERVER_URL).toBe("http://localhost:7873");
  });
});
