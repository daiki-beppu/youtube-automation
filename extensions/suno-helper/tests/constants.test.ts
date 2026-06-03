// popup ⇄ content script ⇄ server 間の契約文字列を固定する回帰テスト。
// 旧実装 `extensions/suno-helper/constants.js` の値を WXT 移行後も不変に保つ。
// これらは yt-collection-serve (#692/#698) との互換契約であり、変更すると
// サーバー側 (`/suno/prompts.json`) と整合しなくなる。
import { describe, expect, it } from "vitest";

import {
  CLIPS_PER_REQUEST,
  COLLECTIONS_ROUTE,
  collectionPromptsRoute,
  DEFAULT_URL,
  MAX_INFLIGHT_REQUESTS,
  PHASE,
  PROMPTS_ROUTE,
  STORAGE_KEY,
} from "../../shared/constants";

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
  it("Given PHASE When 全フェーズを読む Then 既存値に加え waiting-slot を保持する (#816)", () => {
    expect(PHASE).toEqual({
      INJECTING: "injecting",
      GENERATING: "generating",
      WAITING_SLOT: "waiting-slot",
      DONE: "done",
      FINISHED: "finished",
      STOPPED: "stopped",
      ERROR: "error",
    });
  });
});

describe("shared/constants: collection 列挙ルート (#816 dir mode)", () => {
  it("Given COLLECTIONS_ROUTE When 読む Then サーバーの列挙サブパスである", () => {
    // SSOT: src/youtube_automation/scripts/collection_serve.py の dir mode ルート。
    expect(COLLECTIONS_ROUTE).toBe("/collections");
  });

  it("Given collectionPromptsRoute(id) When 組み立てる Then `/collections/<id>/suno/prompts.json` を返す", () => {
    expect(collectionPromptsRoute("20260601-clm-aaa-collection")).toBe(
      "/collections/20260601-clm-aaa-collection/suno/prompts.json",
    );
  });
});

describe("shared/constants: Suno queue 上限 (#816)", () => {
  it("Given 実 DOM 検証値 When 上限定数を読む Then 同時 10 リクエスト / 1 リクエスト=2 clip", () => {
    // order.md 実 DOM 検証: 同時 10 リクエスト = 20 clip、1 Create クリック = 2 clip。
    expect(MAX_INFLIGHT_REQUESTS).toBe(10);
    expect(CLIPS_PER_REQUEST).toBe(2);
  });

  it("Given 上限定数 When 積で最大 clip を求める Then 20 clip になる", () => {
    expect(MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST).toBe(20);
  });
});
