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
  INJECT_ACK_TIMEOUT_MS,
  INTER_CREATE_DELAY_MS,
  MAX_INFLIGHT_REQUESTS,
  MAX_INJECT_RETRY,
  PHASE,
  PROMPTS_ROUTE,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
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
  it("Given PHASE When 全フェーズを読む Then 既存値に加え waiting-slot / adding-to-playlist を保持する (#816, #854)", () => {
    expect(PHASE).toEqual({
      INJECTING: "injecting",
      GENERATING: "generating",
      WAITING_SLOT: "waiting-slot",
      DONE: "done",
      ADDING_TO_PLAYLIST: "adding-to-playlist",
      FINISHED: "finished",
      STOPPED: "stopped",
      ERROR: "error",
    });
  });

  it("Given PHASE When ADDING_TO_PLAYLIST を読む Then clip 一括 playlist 追加 phase の値である (#854)", () => {
    expect(PHASE.ADDING_TO_PLAYLIST).toBe("adding-to-playlist");
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

describe("shared/constants: queue 上限エラー回復タイミング (#847)", () => {
  it("Given INTER_CREATE_DELAY_MS When 読む Then 投入間 3 秒の待機である (Create→DOM 反映ラグ吸収, #864 で 1s→3s)", () => {
    // #864: 1 秒では clip-row DOM 反映ラグの間に次 inject が走り silent drop されるため 3 秒へ延長。
    expect(INTER_CREATE_DELAY_MS).toBe(3000);
  });

  it("Given QUEUE_ERROR_WAIT_MS When 読む Then toast 消失後 30 秒の安全マージンである", () => {
    expect(QUEUE_ERROR_WAIT_MS).toBe(30000);
  });
});

describe("shared/constants: inject 検証 + queue 待機 timeout 独立化 (#864)", () => {
  it("Given QUEUE_SLOT_WAIT_TIMEOUT_MS When 読む Then queue 空き待ち専用の 5 分 timeout である", () => {
    // #864 root cause 1: single clip 完了待ち GENERATE_TIMEOUT_MS=3分 の流用は、20 clip 積んだ
    // 最初の空き待ちで焼き切れる。queue 空き待ちは別系統の 5 分 timeout として独立させる。
    expect(QUEUE_SLOT_WAIT_TIMEOUT_MS).toBe(300000);
  });

  it("Given INJECT_ACK_TIMEOUT_MS When 読む Then inject 後の in-flight 増分 ack 待ち上限 30 秒である", () => {
    // #864 root cause 3: inject 後に in-flight が CLIPS_PER_REQUEST 増えるまで poll wait する上限。
    expect(INJECT_ACK_TIMEOUT_MS).toBe(30000);
  });

  it("Given MAX_INJECT_RETRY When 読む Then silent drop 時の最大 retry 回数 2 である", () => {
    // #864 root cause 3: ack されなければ同じ entry を最大 2 回 retry、それでも増えなければ fail-loud。
    expect(MAX_INJECT_RETRY).toBe(2);
  });
});
