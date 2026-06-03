// popup ⇄ content script ⇄ server 間の契約文字列を 1 箇所に集約する。
// これらは yt-collection-serve (#692/#698) との互換契約であり、変更すると
// サーバー側 (`/suno/prompts.json`) と整合しなくなる。
// SSOT: src/youtube_automation/scripts/suno_artifacts.py SUNO_PROMPTS_ROUTE

/** chrome.storage.local に保存するサーバー URL の key。 */
export const STORAGE_KEY = "sunoServerUrl";

/** yt-collection-serve が prompts を配信するサブパス (#698 で `/prompts.json` から分離)。 */
export const PROMPTS_ROUTE = "/suno/prompts.json";

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
