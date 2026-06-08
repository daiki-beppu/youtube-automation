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
