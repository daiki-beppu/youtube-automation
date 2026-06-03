// popup ⇄ content script ⇄ server 間の契約文字列を 1 箇所に集約する。
// これらは yt-collection-serve (#692/#698) との互換契約であり、変更すると
// サーバー側 (`/suno/prompts.json`) と整合しなくなる。
// SSOT: src/youtube_automation/scripts/suno_artifacts.py SUNO_PROMPTS_ROUTE

/** chrome.storage.local に保存するサーバー URL の key。 */
export const STORAGE_KEY = "sunoServerUrl";

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

/** Create 投入間の待機 (#847)。Create→clip-row DOM 反映ラグによる過剰投入 (race condition) を吸収する。 */
export const INTER_CREATE_DELAY_MS = 1000;

/** queue 上限エラー toast 消失後の安全マージン待機 (#847)。toast が消えても直ちに再開せず buffer を取る。 */
export const QUEUE_ERROR_WAIT_MS = 30000;

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
  FINISHED: "finished",
  STOPPED: "stopped",
  ERROR: "error",
} as const;

export type Phase = (typeof PHASE)[keyof typeof PHASE];

/** content → popup の進捗ペイロード。 */
export interface ProgressPayload {
  phase: Phase;
  total: number;
  index?: number;
  message?: string;
}
