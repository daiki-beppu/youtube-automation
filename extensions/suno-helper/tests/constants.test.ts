// overlay ⇄ content script ⇄ server 間の契約文字列を固定する回帰テスト。
// 旧実装 `extensions/suno-helper/constants.js` の値を WXT 移行後も不変に保つ。
// これらは yt-collection-serve (#692/#698) との互換契約であり、変更すると
// サーバー側 (`/suno/prompts.json`) と整合しなくなる。
import { describe, expect, it } from "vitest";

import {
  BRIDGE_MSG,
  CLIPS_PER_REQUEST,
  COLLECTIONS_ROUTE,
  collectionPromptsRoute,
  DEFAULT_URL,
  FEED_V2_PATH,
  FEED_V3_METHOD,
  FEED_V3_PATH,
  INJECT_ACK_TIMEOUT_MS,
  INTER_CREATE_DELAY_MS,
  MAX_INFLIGHT_REQUESTS,
  MAX_INJECT_RETRY,
  MAX_YIELD_RETRY,
  OVERLAY_STATE_KEY,
  PHASE,
  PROMPTS_ROUTE,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
  SPEED_PRESET_STORAGE_KEY,
  SPEED_PRESETS,
  STORAGE_KEY,
  type ObservedClip,
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

  it("Given overlay 化 (#892) When OVERLAY_STATE_KEY を読む Then overlay 位置・最小化を永続化する key 名である", () => {
    // overlay の position/minimized/hidden を chrome.storage.local に保存する単一 key (order.md §1)。
    // lib/overlay-state.ts がこれを SSOT として参照する。
    expect(OVERLAY_STATE_KEY).toBe("sunoOverlayState");
  });

  it("Given storage key 群 When OVERLAY_STATE_KEY を他 key と比較 Then 既存 key と衝突しない", () => {
    // 同一 chrome.storage.local 名前空間で resume / server URL state と key が被らないこと。
    expect(new Set([STORAGE_KEY, "sunoResumeState", OVERLAY_STATE_KEY]).size).toBe(3);
  });
});

describe("shared/constants: 進捗フェーズ (PHASE)", () => {
  it("Given PHASE When 全フェーズを読む Then 既存値に加え waiting-slot / adding-to-playlist / waiting-captcha / entry-failed / downloading を保持する (#816, #854, #948, #1215)", () => {
    expect(PHASE).toEqual({
      INJECTING: "injecting",
      GENERATING: "generating",
      WAITING_SLOT: "waiting-slot",
      WAITING_CAPTCHA: "waiting-captcha",
      DONE: "done",
      ENTRY_FAILED: "entry-failed",
      DOWNLOADING: "downloading",
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

  it("Given スペース入り collection id When collectionPromptsRoute(id) Then id を path segment encode する", () => {
    expect(collectionPromptsRoute("20260526-rainy jazz-collection")).toBe(
      "/collections/20260526-rainy%20jazz-collection/suno/prompts.json",
    );
  });

  it("Given 空 collection id When collectionPromptsRoute(id) Then throw する", () => {
    expect(() => collectionPromptsRoute("")).toThrow(/collectionId/);
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

describe("shared/constants: Suno feed bridge 契約 (#1258)", () => {
  it("Given feed endpoint constants When 読む Then v2 GET poll と v3 POST 用 path/method を固定する", () => {
    expect(FEED_V2_PATH).toBe("/api/feed/v2");
    expect(FEED_V3_PATH).toBe("/api/feed/v3");
    expect(FEED_V3_METHOD).toBe("POST");
  });

  it("Given BRIDGE_MSG When feed v3 poll の message type を読む Then v2 と別名で固定されている", () => {
    expect(BRIDGE_MSG.FEED_POLL_REQUEST).toBe("feed-poll-request");
    expect(BRIDGE_MSG.FEED_POLL_RESPONSE).toBe("feed-poll-response");
    expect(BRIDGE_MSG.FEED_V3_POLL_REQUEST).toBe("feed-v3-poll-request");
    expect(BRIDGE_MSG.FEED_V3_POLL_RESPONSE).toBe("feed-v3-poll-response");
  });

  it("Given ObservedClip When duration を持つ clip / 持たない clip を扱う Then optional field として型付けできる", () => {
    const withDuration = { id: "clip-1", status: "complete", duration: 241.2 } satisfies ObservedClip;
    const withoutDuration = { id: "clip-2", status: "queued" } satisfies ObservedClip;

    expect(withDuration.duration).toBe(241.2);
    expect("duration" in withoutDuration).toBe(false);
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

  it("Given MAX_YIELD_RETRY When 読む Then duration NG 時の最大 retry 回数 2 である", () => {
    expect(MAX_YIELD_RETRY).toBe(2);
  });
});

describe("shared/constants: 速度プリセット (#875)", () => {
  // 契約 (draft が実装する public API, shared/constants.ts):
  //   - SPEED_PRESET_STORAGE_KEY: string = "sunoSpeedPreset"
  //   - SPEED_PRESETS: Record<"fast"|"balanced"|"safe", SpeedPreset>
  //     SpeedPreset = { interCreateDelayMs; jitterMs; maxInflightRequests;
  //                     maxInjectRetry; injectAckTimeoutMs; label; riskNote }
  // 値の SSOT は order.md L23-27 の表。Fast は現状定数を残置し参照する（現状と同等を担保）。

  it("Given SPEED_PRESET_STORAGE_KEY When 読む Then chrome.storage.local の preset key である", () => {
    expect(SPEED_PRESET_STORAGE_KEY).toBe("sunoSpeedPreset");
  });

  it("Given SPEED_PRESETS When key を読む Then fast / balanced / safe の 3 preset を持つ", () => {
    expect(Object.keys(SPEED_PRESETS).sort()).toEqual(["balanced", "fast", "safe"]);
  });

  it("Given fast preset When 数値を読む Then 現状定数と一致する（現状と同等, jitter なし）", () => {
    // 受け入れ基準「Fast 選択時の所要時間が現状と同等」。既存定数を Fast から参照する設計を pin し、
    // 残置定数と preset 値の drift を回帰ガードする。
    expect(SPEED_PRESETS.fast.interCreateDelayMs).toBe(INTER_CREATE_DELAY_MS);
    expect(SPEED_PRESETS.fast.jitterMs).toBe(0);
    expect(SPEED_PRESETS.fast.maxInflightRequests).toBe(MAX_INFLIGHT_REQUESTS);
    expect(SPEED_PRESETS.fast.maxInjectRetry).toBe(MAX_INJECT_RETRY);
    expect(SPEED_PRESETS.fast.injectAckTimeoutMs).toBe(INJECT_ACK_TIMEOUT_MS);
  });

  it("Given balanced preset When 数値を読む Then 6s / ±3s / inflight 実上限 / retry 1 / ack 45s (#970)", () => {
    // #948 で in-flight が API status の正確な計数になったため、queue cap を Suno 実上限
    // （MAX_INFLIGHT_REQUESTS = 10、#816 実機検証）まで開放し、ジッター付き間隔だけで自然化する。
    expect(SPEED_PRESETS.balanced).toMatchObject({
      interCreateDelayMs: 6000,
      jitterMs: 3000,
      maxInflightRequests: MAX_INFLIGHT_REQUESTS,
      maxInjectRetry: 1,
      injectAckTimeoutMs: 45000,
    });
  });

  it("Given safe preset When 数値を読む Then 20s / ±5s / inflight 3 / retry 0 / ack 60s", () => {
    expect(SPEED_PRESETS.safe).toMatchObject({
      interCreateDelayMs: 20000,
      jitterMs: 5000,
      maxInflightRequests: 3,
      maxInjectRetry: 0,
      injectAckTimeoutMs: 60000,
    });
  });

  it.each(["fast", "balanced", "safe"] as const)(
    "Given %s preset When label / riskNote を読む Then 非空文字列を持つ（UI 表示用, 要件6）",
    (id) => {
      // label/riskNote が write-only な空フィールドへ退行しないことを担保（文言そのものは pin しない）。
      expect(typeof SPEED_PRESETS[id].label).toBe("string");
      expect(SPEED_PRESETS[id].label.length).toBeGreaterThan(0);
      expect(typeof SPEED_PRESETS[id].riskNote).toBe("string");
      expect(SPEED_PRESETS[id].riskNote.length).toBeGreaterThan(0);
    },
  );

  it("Given balanced preset When jitter 適用域を求める Then 3000〜9000ms（#970 増速後の 3-9s）", () => {
    // applyJitter の min/max は preset-state.test.ts で検証。ここでは preset 値が
    // 受け入れ基準の範囲を表現できることだけを確認する。
    const { interCreateDelayMs: base, jitterMs } = SPEED_PRESETS.balanced;
    expect(base - jitterMs).toBe(3000);
    expect(base + jitterMs).toBe(9000);
  });

  it("Given safe preset When jitter 適用域を求める Then 15000〜25000ms（受け入れ基準 15-25s）", () => {
    const { interCreateDelayMs: base, jitterMs } = SPEED_PRESETS.safe;
    expect(base - jitterMs).toBe(15000);
    expect(base + jitterMs).toBe(25000);
  });
});
