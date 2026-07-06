// overlay ⇄ content script ⇄ server 間の契約文字列を 1 箇所に集約する。
// これらは yt-collection-serve (#692/#698) との互換契約であり、変更すると
// サーバー側 (`/suno/prompts.json`) と整合しなくなる。
// SSOT: src/youtube_automation/scripts/suno_artifacts.py SUNO_PROMPTS_ROUTE
import type { PromptEntry } from "./api";

/** chrome.storage.local に保存するサーバー URL の key。 */
export const STORAGE_KEY = "sunoServerUrl";

/** ERROR 停止時の途中再開 state を保存する chrome.storage.local の key (#872)。
 * overlay と content が同一 key を参照するため、契約文字列としてここを SSOT とする。 */
export const RESUME_STATE_KEY = "sunoResumeState";

/** overlay の position/minimized/hidden を保存する chrome.storage.local の単一 key (#892)。
 * Suno は 1 タブ運用前提のため global 単一 key とする。lib/overlay-state.ts が SSOT として参照する。 */
export const OVERLAY_STATE_KEY = "sunoOverlayState";

/** run 一式完了時リロード (#1411) で失われる直近完了 run の snapshot を退避する chrome.storage.local の key。
 * content が FINISHED 到達時（リロード予約の直前）に書き、リロード後の queryProgress が復元ソースとして読む。
 * lib/finished-snapshot.ts が SSOT として参照する。 */
export const FINISHED_SNAPSHOT_KEY = "sunoFinishedSnapshot";

/** yt-collection-serve の download 完了通知サブパス (#1215、POST)。
 * SSOT: src/youtube_automation/scripts/suno_artifacts.py collection_downloaded_route。 */
export const DOWNLOADED_ROUTE = "/collections/:id/downloaded" as const;

/** Suno ダウンロード形式を保存する chrome.storage.local の key (#1215)。
 * popup（書込）と content（読込）が同一 key を参照するため、契約文字列としてここを SSOT とする。 */
export const DOWNLOAD_FORMAT_KEY = "sunoDownloadFormat" as const;

/** Suno ダウンロード形式のデフォルト値 (#1215)。 */
export const DOWNLOAD_FORMAT_DEFAULT = "mp3" as const;

/** yt-collection-serve が prompts を配信するサブパス (#698 で `/prompts.json` から分離)。 */
export const PROMPTS_ROUTE = "/suno/prompts.json";

/** yt-collection-serve dir mode の collection 列挙サブパス (#816)。
 * SSOT: src/youtube_automation/scripts/suno_artifacts.py COLLECTIONS_ROUTE。 */
export const COLLECTIONS_ROUTE = "/collections";

/** yt-collection-serve の互換確認サブパス（#1023）。
 * SSOT: src/youtube_automation/scripts/collection_serve.py VERSION_ROUTE。 */
export const VERSION_ROUTE = "/version";

/** 個別 collection の prompts 配信サブパス `/collections/<id>/suno/prompts.json` を組み立てる (#816)。 */
export function collectionPromptsRoute(id: string): string {
  if (id.length === 0) {
    throw new Error("collectionId must be non-empty string");
  }
  return `${COLLECTIONS_ROUTE}/${encodeURIComponent(id)}${PROMPTS_ROUTE}`;
}

/** 個別 collection の download 完了通知 POST サブパス `/collections/<id>/downloaded` を組み立てる。 */
export function collectionDownloadedRoute(id: string): string {
  return DOWNLOADED_ROUTE.replace(":id", encodeURIComponent(id));
}

/** Suno 同時生成キューの上限リクエスト数 (#816、実 DOM 検証: 同時 10 リクエスト)。 */
export const MAX_INFLIGHT_REQUESTS = 10;

/** 1 Create クリックで出現する clip 数 (#816、実 DOM 検証: variation A/B = 2 clip)。 */
export const CLIPS_PER_REQUEST = 2;

/** Create 投入間の待機 (#847, #864 で 1s→3s)。Create→clip-row DOM 反映ラグによる過剰投入 (race condition) を吸収する。
 * 1 秒では反映ラグの間に次 inject が走り silent drop されるため 3 秒へ延長 (#864 root cause 2)。 */
export const INTER_CREATE_DELAY_MS = 3000;

/** queue 上限エラー toast 消失後の安全マージン待機 (#847)。toast が消えても直ちに再開せず buffer を取る。 */
export const QUEUE_ERROR_WAIT_MS = 30000;

/** queue 空きスロット待ち専用の timeout (#864 root cause 1)。single clip 完了待ち GENERATE_TIMEOUT_MS=3分 の
 * 流用は、20 clip 積んだ最初の空き待ちで焼き切れる。queue 空き待ちは別系統の 5 分として独立させる。
 * #948 以降は stall ベース判定（INFLIGHT_STALL_TIMEOUT_MS）が主経路で、本定数は
 * getLastChangeAt を注入しない呼び出し（固定 deadline 経路）専用。 */
export const QUEUE_SLOT_WAIT_TIMEOUT_MS = 300000;

/** queue 空き待ちの stall 判定閾値 (#948)。正確な in-flight カウントの下では「上限で長く待つ」のは
 * 正常状態であり、固定 deadline での fail-loud は誤停止になる。in-flight 集合（観測 clip の status）が
 * この時間まったく変化しないときのみ「Suno 側が固まった」とみなして throw する。 */
export const INFLIGHT_STALL_TIMEOUT_MS = 600000;

/** inject 後に in-flight が CLIPS_PER_REQUEST 増えるまで poll wait する上限 (#864 root cause 3)。 */
export const INJECT_ACK_TIMEOUT_MS = 30000;

/** inject が ack されなかったときに同じ entry を再投入する最大 retry 回数 (#864 root cause 3)。
 * これを超えても in-flight が増えなければ fail-loud で ERROR phase に落とす。 */
export const MAX_INJECT_RETRY = 2;

/** duration 歩留まり NG 時に同じ entry を再生成する最大 retry 回数 (#1266)。 */
export const MAX_YIELD_RETRY = 2;

/** 速度プリセットの選択値を保存する chrome.storage.local の key (#875)。
 * popup（書込）と content（読込）が同一 key を参照するため、契約文字列としてここを SSOT とする。 */
export const SPEED_PRESET_STORAGE_KEY = "sunoSpeedPreset";

/** 速度プリセットの識別子 (#875)。SPEED_PRESETS の key と 1:1 で対応する。 */
export type SpeedPresetId = "fast" | "balanced" | "safe";

/**
 * 連続実行のペーシング 1 段分の設定 (#875)。Cloudflare bot management + hCaptcha 連動による
 * silent drop / ban リスクを、間隔・並列数・retry 回数の保守度で調整する。
 *   - interCreateDelayMs: Create 投入間の基準待機。jitterMs で散らして bot 判定の固定間隔シグナルを消す
 *   - jitterMs: 待機の振れ幅 (±)。0 なら固定間隔（Fast）
 *   - maxInflightRequests: 同時に積む生成リクエスト上限。低いほど人間らしい
 *   - maxInjectRetry: silent drop 時の同一 entry 再投入上限。0 なら即諦めて分割実行へ委ねる
 *   - injectAckTimeoutMs: inject 受理（in-flight 増分）待ちの上限
 *   - label / riskNote: popup の実行モード選択 UI 表示用（要件6: 選択時のリスク認識を促す）
 */
export interface SpeedPreset {
  interCreateDelayMs: number;
  jitterMs: number;
  maxInflightRequests: number;
  maxInjectRetry: number;
  injectAckTimeoutMs: number;
  /** entry 単位の失敗（非 fatal）を同一 entry で再試行する最大回数 (#948)。超過でスキップして次 entry へ。 */
  maxEntryRetry: number;
  label: string;
  riskNote: string;
}

/**
 * 速度プリセット 3 段 (#875)。値の SSOT は order.md の表。
 * Fast は現状定数 (INTER_CREATE_DELAY_MS / MAX_INFLIGHT_REQUESTS / MAX_INJECT_RETRY / INJECT_ACK_TIMEOUT_MS)
 * を参照し「現状と同等の所要時間」を担保する（残置定数と preset 値の drift を回避）。
 */
export const SPEED_PRESETS: Record<SpeedPresetId, SpeedPreset> = {
  fast: {
    interCreateDelayMs: INTER_CREATE_DELAY_MS,
    jitterMs: 0,
    maxInflightRequests: MAX_INFLIGHT_REQUESTS,
    maxInjectRetry: MAX_INJECT_RETRY,
    injectAckTimeoutMs: INJECT_ACK_TIMEOUT_MS,
    maxEntryRetry: 1,
    label: "⚡ Fast",
    riskNote:
      "〜10 entries の小 collection 向け。現状値。連続実行が長引くと bot 判定で silent drop しやすい。",
  },
  balanced: {
    interCreateDelayMs: 6000,
    jitterMs: 3000,
    maxInflightRequests: MAX_INFLIGHT_REQUESTS,
    maxInjectRetry: 1,
    injectAckTimeoutMs: 45000,
    maxEntryRetry: 2,
    label: "⚖️ Balanced",
    riskNote:
      "20-55 entries の標準 collection 向け。6s ±3s 間隔で自然化したデフォルト。queue は Suno 実上限まで使う（#970、in-flight が API status 計数になった #948 以降は上限張り付きが正常状態）。",
  },
  safe: {
    interCreateDelayMs: 20000,
    jitterMs: 5000,
    maxInflightRequests: 3,
    maxInjectRetry: 0,
    injectAckTimeoutMs: 60000,
    maxEntryRetry: 3,
    label: "🐢 Safe",
    riskNote:
      "30+ entries / 過去に hCaptcha challenge を踏んだ場合向け。20s ±5s と保守的で時間はかかる。",
  },
};

/** Suno studio API のオリジン（#948、chrome-devtools 実機観測で確定）。
 * MAIN world bridge が生成投入 / clip status を観測・照会する対象。 */
export const SUNO_API_ORIGIN = "https://studio-api-prod.suno.com";

/** 生成投入 endpoint のパス（#948）。レスポンス JSON の `clips[].id` / `clips[].status` を観測する。 */
export const GENERATE_ENDPOINT_PATH = "/api/generate/v2-web/";

/** active feed poll に使う具体 endpoint（#948）。 */
export const FEED_V2_PATH = "/api/feed/v2";

/** passive fetch 観測 / duration 取得に使う feed v3 endpoint（#1258, #1265）。 */
export const FEED_V3_PATH = "/api/feed/v3";

/** feed v3 の request method（#1258, #1265）。v2 の GET poll と区別するため契約値として固定する。 */
export const FEED_V3_METHOD = "POST";

/** MAIN world bridge ⇄ ISOLATED content script の window.postMessage 識別マーカー（#948）。 */
export const BRIDGE_SOURCE = "suno-helper-bridge";

/** bridge メッセージ種別（#948）。window.postMessage の `type` フィールドに載せる。 */
export const BRIDGE_MSG = {
  /** bridge → content: generate レスポンスで観測した投入 clip 一覧。 */
  GENERATE_CLIPS: "generate-clips",
  /** bridge → content: feed レスポンスで観測した clip status 一覧。 */
  FEED_CLIPS: "feed-clips",
  /** content → bridge: feed/v2 の active poll 要求（requestId + ids）。 */
  FEED_POLL_REQUEST: "feed-poll-request",
  /** bridge → content: active poll の応答（requestId + clips | null）。 */
  FEED_POLL_RESPONSE: "feed-poll-response",
  /** content → bridge: feed/v3 の active poll 要求（requestId + ids）。 */
  FEED_V3_POLL_REQUEST: "feed-v3-poll-request",
  /** bridge → content: feed/v3 active poll の応答（requestId + clips | null）。 */
  FEED_V3_POLL_RESPONSE: "feed-v3-poll-response",
  /** content → bridge: slider 値注入要求（requestId + ariaLabel + target）（#973）。 */
  SLIDER_SET_REQUEST: "slider-set-request",
  /** bridge → content: slider 値注入の応答（requestId + ok + actual | null）（#973）。 */
  SLIDER_SET_RESPONSE: "slider-set-response",
} as const;

/** slider 注入 RPC の応答待ち上限 (ms)（#973）。step 数が多い slider（0→100 等）でも
 * 1 step あたり数十 ms の readback 待ちで完了する想定だが、余裕を持たせる。 */
export const SLIDER_SET_RESPONSE_TIMEOUT_MS = 15000;

/** 生成が終端に達した clip status（#948）。これら以外はキュー slot を占有する in-flight とみなす。 */
export const TERMINAL_CLIP_STATUSES = ["complete", "error"] as const;

/** passive 観測がこの時間途絶え、かつ未終端 clip が残っているとき active feed poll に切り替える閾値 (ms)。 */
export const FEED_STALE_MS = 15000;

/** active feed poll の実行間隔 (ms)。ページ自身のポーリング頻度（数秒間隔）と同程度に抑える。 */
export const FEED_POLL_INTERVAL_MS = 5000;

/** active feed poll の応答待ち上限 (ms)。bridge 不在・token 未捕捉時に listener 側が諦める時間。 */
export const FEED_POLL_RESPONSE_TIMEOUT_MS = 10000;

/** bridge が観測した clip の最小表現（#948）。status は Suno API の生値（submitted/queued/streaming/complete/error 等）。 */
export interface ObservedClip {
  id: string;
  status: string;
  /** Suno feed metadata.duration 由来の秒数。generate response では未観測のため optional。 */
  duration?: number;
}

/** yt-collection-serve の DistroKid collection 列挙サブパス（#934、dir mode のみ。単一 mode では 404）。
 * SSOT: src/youtube_automation/scripts/collection_serve.py _DISTROKID_COLLECTIONS_ROUTE。 */
export const DISTROKID_COLLECTIONS_ROUTE = "/distrokid/collections";

/** yt-collection-serve の DistroKid 配信済み記録 POST サブパス（#934）。
 * SSOT: src/youtube_automation/scripts/collection_serve.py _DISTROKID_RELEASES_ROUTE。 */
export const DISTROKID_RELEASES_ROUTE = "/distrokid/releases";

/** 個別 collection の release.json 配信サブパスを組み立てる（#934）。
 * 例: distrokidReleaseRoute("20260526-soulful-grooves-coding-focus-collection", "disc1-coding-focus-vol1")
 *   -> "/collections/20260526-soulful-grooves-coding-focus-collection/distrokid/disc1-coding-focus-vol1/release.json"
 * asset_path は `/collections/<id>/distrokid/assets/<rel>` 形式のため baseUrl 連結で取得できる。 */
export function distrokidReleaseRoute(
  collectionId: string,
  disc: string,
): string {
  return `/collections/${encodeURIComponent(collectionId)}/distrokid/${disc}/release.json`;
}

/** ローカル配信元の既定 URL。 */
export const DEFAULT_URL = "http://localhost:7873";

/** content script を注入する Suno のオリジン（manifest の matches / host_permissions と対）。 */
export const SUNO_MATCHES = [
  "https://suno.com/*",
  "https://www.suno.com/*",
] as const;

/** prompts 配信元（ローカルサーバー）への fetch を許可する host_permissions。 */
export const SERVER_HOST_PERMISSIONS = [
  "http://localhost/*",
  "http://127.0.0.1/*",
] as const;

/** PROGRESS メッセージの phase 値。 */
export const PHASE = {
  INJECTING: "injecting",
  GENERATING: "generating",
  WAITING_SLOT: "waiting-slot",
  // captcha challenge の解消（自動 verify or 手動解決）待ち。即 fail-loud せず待機して自動続行する。非終了 phase。
  WAITING_CAPTCHA: "waiting-captcha",
  DONE: "done",
  // entry 単位の失敗 (#948)。リトライ上限まで失敗した entry をスキップして次へ進むときに emit する。
  // 非終了 phase（run 全体は継続する）。失敗 index は snapshot の failedIndices に蓄積される。
  ENTRY_FAILED: "entry-failed",
  // 全 entry の生成 DONE 後、playlist 追加完了後に Suno playlist を一括ダウンロードする phase (#1215)。非終了 phase。
  DOWNLOADING: "downloading",
  // 全 entry の生成 DONE 後の clip 一括 playlist 追加 phase (#854)。ADDING_TO_PLAYLIST → DOWNLOADING → FINISHED の順。非終了 phase。
  ADDING_TO_PLAYLIST: "adding-to-playlist",
  FINISHED: "finished",
  STOPPED: "stopped",
  ERROR: "error",
} as const;

export type Phase = (typeof PHASE)[keyof typeof PHASE];

/** runner content が overlay / popup に表示させる構造化ログ (#1270)。 */
export type ProgressLog =
  | {
      kind: "duration-check";
      entryName: string;
      durationSec: number;
      ok: boolean;
      minSec?: number;
      maxSec?: number;
    }
  | {
      kind: "retry";
      entryName: string;
      attempt: number;
      max: number;
    }
  | {
      kind: "skip";
      entryName: string;
    };

type ProgressPayloadBase = {
  phase: Phase;
  total: number;
  index?: number;
  message?: string;
};

type ProgressPayloadWithoutLog = ProgressPayloadBase & {
  log?: undefined;
};

type DurationCheckProgressPayload = ProgressPayloadBase & {
  phase: typeof PHASE.DONE;
  log: Extract<ProgressLog, { kind: "duration-check" }>;
};

type RetryProgressPayload = ProgressPayloadBase & {
  phase: typeof PHASE.WAITING_SLOT;
  log: Extract<ProgressLog, { kind: "retry" }>;
};

type SkipProgressPayload = ProgressPayloadBase & {
  phase: typeof PHASE.ENTRY_FAILED;
  log: Extract<ProgressLog, { kind: "skip" }>;
};

/** runner content → overlay の進捗ペイロード。log は phase/kind の許可組み合わせだけに載せる。 */
export type ProgressPayload =
  | ProgressPayloadWithoutLog
  | DurationCheckProgressPayload
  | RetryProgressPayload
  | SkipProgressPayload;

/** overlay の各パターン行の表示状態。failed はリトライ上限まで失敗しスキップされた entry (#948)。 */
export type ItemState = "idle" | "active" | "done" | "failed";

/** content script が SSOT として保持する進捗スナップショット (#852)。
 * overlay を閉じても content が保持し、再 open 時に `queryProgress` で返す。 */
export interface SnapshotPayload {
  // 実行元 collection。popup 再 open 復元時に別 collection の entries を現在選択へ誤適用しないため保持する。
  collectionId: string;
  entries: PromptEntry[];
  itemStates: ItemState[];
  isRunning: boolean;
  progress: ProgressPayload;
  // playlist 名 (#854)。再 open 復元時の display 用。download-only snapshot では undefined。
  playlistName?: string;
  // ERROR 停止した entry の index (#872)。chrome.storage の resume state と二重化し、
  // popup の進捗復元でも参照する。ERROR phase 到達時のみ確定し、それ以外は undefined。
  failedIndex?: number;
  // リトライ上限まで失敗しスキップされた entry の 0-based index 一覧 (#948)。
  // ENTRY_FAILED phase の受信ごとに蓄積され、popup の「失敗分のみ再実行」導線が消費する。
  failedIndices?: number[];
  // 明示 indices 実行が途中中断したとき、再開で実行すべき残りの 0-based index 列。
  remainingIndices?: number[];
  // playlist 追加対象として generate response から観測済みの clip ID 一覧。
  submittedClipIds?: string[];
  // true のとき submittedClipIds は resume 保存時点で OK clip IDs に正規化済み。
  submittedClipIdsAreDurationFiltered?: boolean;
  // playlist 追加時に揃っているべき clip ID 件数。
  playlistExpectedClipCount?: number;
}
