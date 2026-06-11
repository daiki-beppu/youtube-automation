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

/** yt-collection-serve が prompts を配信するサブパス (#698 で `/prompts.json` から分離)。 */
export const PROMPTS_ROUTE = "/suno/prompts.json";

/** yt-collection-serve dir mode の collection 列挙サブパス (#816)。
 * SSOT: src/youtube_automation/scripts/suno_artifacts.py COLLECTIONS_ROUTE。 */
export const COLLECTIONS_ROUTE = "/collections";

/** yt-collection-serve の Suno playlist capture サブパス (#893、POST)。
 * SSOT: src/youtube_automation/scripts/suno_artifacts.py SUNO_PLAYLISTS_ROUTE。 */
export const PLAYLISTS_CAPTURE_ROUTE = "/suno/playlists";

/** 個別 collection の prompts 配信サブパス `/collections/<id>/suno/prompts.json` を組み立てる (#816)。 */
export function collectionPromptsRoute(id: string): string {
  return `${COLLECTIONS_ROUTE}/${id}${PROMPTS_ROUTE}`;
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
 * 流用は、20 clip 積んだ最初の空き待ちで焼き切れる。queue 空き待ちは別系統の 5 分として独立させる。 */
export const QUEUE_SLOT_WAIT_TIMEOUT_MS = 300000;

/** inject 後に in-flight が CLIPS_PER_REQUEST 増えるまで poll wait する上限 (#864 root cause 3)。 */
export const INJECT_ACK_TIMEOUT_MS = 30000;

/** inject が ack されなかったときに同じ entry を再投入する最大 retry 回数 (#864 root cause 3)。
 * これを超えても in-flight が増えなければ fail-loud で ERROR phase に落とす。 */
export const MAX_INJECT_RETRY = 2;

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
    label: "⚡ Fast",
    riskNote:
      "〜10 entries の小 collection 向け。現状値。連続実行が長引くと bot 判定で silent drop しやすい。",
  },
  balanced: {
    interCreateDelayMs: 10000,
    jitterMs: 3000,
    maxInflightRequests: 5,
    maxInjectRetry: 1,
    injectAckTimeoutMs: 45000,
    label: "⚖️ Balanced",
    riskNote:
      "20-30 entries の標準 collection 向け。10s ±3s 間隔で自然化したデフォルト。",
  },
  safe: {
    interCreateDelayMs: 20000,
    jitterMs: 5000,
    maxInflightRequests: 3,
    maxInjectRetry: 0,
    injectAckTimeoutMs: 60000,
    label: "🐢 Safe",
    riskNote:
      "30+ entries / 過去に hCaptcha challenge を踏んだ場合向け。20s ±5s と保守的で時間はかかる。",
  },
};

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
  return `/collections/${collectionId}/distrokid/${disc}/release.json`;
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
  DONE: "done",
  // 全 entry の生成 DONE 後、FINISHED 直前に挟む clip 一括 playlist 追加 phase (#854)。非終了 phase。
  ADDING_TO_PLAYLIST: "adding-to-playlist",
  FINISHED: "finished",
  STOPPED: "stopped",
  ERROR: "error",
} as const;

export type Phase = (typeof PHASE)[keyof typeof PHASE];

/** runner content → overlay の進捗ペイロード。 */
export interface ProgressPayload {
  phase: Phase;
  total: number;
  index?: number;
  message?: string;
}

/** overlay の各パターン行の表示状態。 */
export type ItemState = "idle" | "active" | "done";

/** content script が SSOT として保持する進捗スナップショット (#852)。
 * overlay を閉じても content が保持し、再 open 時に `queryProgress` で返す。 */
export interface SnapshotPayload {
  entries: PromptEntry[];
  itemStates: ItemState[];
  isRunning: boolean;
  progress: ProgressPayload;
  // collection mode のときの playlist 名 (#854)。再 open 復元時の display 用。
  // 単一ファイル mode（collection 未選択）は playlist phase を実行しないため undefined。
  playlistName?: string;
  // ERROR 停止した entry の index (#872)。chrome.storage の resume state と二重化し、
  // popup の進捗復元でも参照する。ERROR phase 到達時のみ確定し、それ以外は undefined。
  failedIndex?: number;
}
