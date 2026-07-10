// overlay ⇄ content script ⇄ server 間の契約文字列を固定する回帰テスト。
// 旧実装 `extensions/suno-helper/constants.js` の値を WXT 移行後も不変に保つ。
// これらは yt-collection-serve (#692/#698) との互換契約であり、変更すると
// サーバー側 (`/suno/prompts.json`) と整合しなくなる。
import { describe, expect, it } from "vitest";

import {
  BALANCED_RUN_PACING,
  BRIDGE_MSG,
  CLIPS_PER_REQUEST,
  COLLECTIONS_ROUTE,
  collectionPromptsRoute,
  DEFAULT_SERVER_SOURCES,
  DEFAULT_URL,
  FEED_V3_METHOD,
  FEED_V3_PATH,
  formatServerSourceLabel,
  INJECT_ACK_TIMEOUT_MS,
  INTER_CREATE_DELAY_MS,
  MAX_INJECT_RETRY,
  MAX_INFLIGHT_REQUESTS,
  MAX_YIELD_RETRY,
  OVERLAY_STATE_KEY,
  PHASE,
  PROMPTS_ROUTE,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
  RUN_MODE_STORAGE_KEY,
  RUN_MODES,
  SERVER_HOST_PERMISSIONS,
  STORAGE_KEY,
  type ObservedClip,
  type RunModeId,
} from "../../shared/constants";

describe("shared/constants: サーバー互換の契約値", () => {
  it("Given 移行後の定数 When STORAGE_KEY を読む Then 旧実装と同じ key 名である", () => {
    expect(STORAGE_KEY).toBe("sunoServerUrl");
  });

  it("Given 移行後の定数 When PROMPTS_ROUTE を読む Then #698 のサブパス分離後ルートである", () => {
    // SSOT: src/youtube_automation/scripts/suno_artifacts.py SUNO_PROMPTS_ROUTE
    expect(PROMPTS_ROUTE).toBe("/suno/prompts.json");
  });

  it("Given server selector When DEFAULT_URL を読む Then チャンネル識別可能な既定 hostname である", () => {
    expect(DEFAULT_URL).toBe("http://youtube-automation.localhost:7873");
  });

  it("Given server selector When 既定候補を読む Then チャンネル別 hostname と localhost fallback を持つ", () => {
    expect(DEFAULT_SERVER_SOURCES.map((source) => source.url)).toEqual([
      "http://youtube-automation.localhost:7873",
      "http://localhost:7873",
      "http://localhost:7874",
      "http://localhost:7875",
      "http://localhost:7876",
      "http://localhost:7877",
    ]);
  });

  it("Given server selector When helper ごとの option 表示名を組み立てる Then URL を含めずプロセスを識別できる", () => {
    expect(
      formatServerSourceLabel(
        { id: "abyss-mi", label: "ABYSS MI", url: "http://abyss-mi.localhost:7873" },
        "distrokid-helper",
      ),
    ).toBe("ABYSS MI | distrokid-helper");
    expect(formatServerSourceLabel(DEFAULT_SERVER_SOURCES.at(-1)!, "suno-helper")).toBe(
      "localhost fallback 7877 | suno-helper",
    );
  });

  it("Given server selector When host permissions を読む Then *.localhost を許可する", () => {
    expect(SERVER_HOST_PERMISSIONS).toContain("http://*.localhost/*");
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
  it("Given PHASE When 全フェーズを読む Then queue submitted を含む進捗 phase を保持する (#816, #854, #948, #1215, #1586)", () => {
    expect(PHASE).toEqual({
      INJECTING: "injecting",
      GENERATING: "generating",
      WAITING_SLOT: "waiting-slot",
      WAITING_CAPTCHA: "waiting-captcha",
      SUBMITTED: "submitted",
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

describe("shared/constants: Suno feed v3 endpoint (#1265)", () => {
  it("Given FEED_V3_PATH / FEED_V3_METHOD When 読む Then passive 観測対象の endpoint 契約である", () => {
    expect(FEED_V3_PATH).toBe("/api/feed/v3");
    expect(FEED_V3_METHOD).toBe("POST");
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
  it("Given feed endpoint constants When 読む Then v3 POST 用 path/method を固定する", () => {
    expect(FEED_V3_PATH).toBe("/api/feed/v3");
    expect(FEED_V3_METHOD).toBe("POST");
  });

  it("Given BRIDGE_MSG When feed v3 poll の message type を読む Then 契約値が固定されている", () => {
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

describe("shared/constants: Balanced 固定ペーシング (#1573)", () => {
  it("Given BALANCED_RUN_PACING When 数値を読む Then 6s / ±3s / inflight 実上限 / retry 1 / ack 45s (#970)", () => {
    // #948 で in-flight が API status の正確な計数になったため、queue cap を Suno 実上限
    // （MAX_INFLIGHT_REQUESTS = 10、#816 実機検証）まで開放し、ジッター付き間隔だけで自然化する。
    expect(BALANCED_RUN_PACING).toMatchObject({
      interCreateDelayMs: 6000,
      jitterMs: 3000,
      maxInflightRequests: MAX_INFLIGHT_REQUESTS,
      maxInjectRetry: 1,
      injectAckTimeoutMs: 45000,
      maxEntryRetry: 2,
    });
  });

  it("Given BALANCED_RUN_PACING When jitter 適用域を求める Then 3000〜9000ms（#970 増速後の 3-9s）", () => {
    // applyJitter の min/max は preset-state.test.ts で検証。ここでは pacing 値が
    // 受け入れ基準の範囲を表現できることだけを確認する。
    const { interCreateDelayMs: base, jitterMs } = BALANCED_RUN_PACING;
    expect(base - jitterMs).toBe(3000);
    expect(base + jitterMs).toBe(9000);
  });

  it("Given BALANCED_RUN_PACING When INTER_CREATE_DELAY_MS と比較 Then 旧 Fast 固定値ではない", () => {
    expect(BALANCED_RUN_PACING.interCreateDelayMs).not.toBe(INTER_CREATE_DELAY_MS);
  });
});

describe("shared/constants: 投入方式 run mode (#1586)", () => {
  it("Given RUN_MODE_STORAGE_KEY When 読む Then chrome.storage.local の run mode key である", () => {
    expect(RUN_MODE_STORAGE_KEY).toBe("sunoRunMode");
  });

  it("Given RUN_MODES When key を読む Then serial / queue の 2 mode を持つ", () => {
    expect(Object.keys(RUN_MODES).sort()).toEqual(["queue", "serial"]);
  });

  it.each(["serial", "queue"] as const)(
    "Given %s mode When label / riskNote を読む Then UI 表示用の非空文字列を持つ",
    (id: RunModeId) => {
      expect(typeof RUN_MODES[id].label).toBe("string");
      expect(RUN_MODES[id].label.length).toBeGreaterThan(0);
      expect(typeof RUN_MODES[id].riskNote).toBe("string");
      expect(RUN_MODES[id].riskNote.length).toBeGreaterThan(0);
    },
  );

  it("Given queue mode When riskNote を読む Then duration 範囲外 entry の失敗検知と再実行導線を説明する", () => {
    expect(RUN_MODES.queue.riskNote).toEqual(expect.stringContaining("範囲外"));
    expect(RUN_MODES.queue.riskNote).toEqual(expect.stringContaining("失敗"));
    expect(RUN_MODES.queue.riskNote).toEqual(expect.stringContaining("失敗分のみ再実行"));
  });
});
