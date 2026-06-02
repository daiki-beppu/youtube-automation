// yt-collection-serve の `/suno/prompts.json` クライアント。
// 旧 `popup.js` の fetch ロジックを保持する:
//   - fetch 先は `${baseUrl}${PROMPTS_ROUTE}`
//   - HTTP 非 2xx で throw
//   - 配列でない / 空配列の JSON で throw (fail-loud、silent 続行しない)
import { PROMPTS_ROUTE } from "./constants";

/** `/suno/prompts.json` が返す 1 パターンのスキーマ (#692 サーバー契約)。 */
export interface PromptEntry {
  name: string;
  style: string;
  lyrics: string;
}

/** prompts.json を取得して PromptEntry[] を返す。不正な応答は fail-loud で throw。 */
export async function fetchPrompts(baseUrl: string): Promise<PromptEntry[]> {
  const resp = await fetch(`${baseUrl}${PROMPTS_ROUTE}`);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const data: unknown = await resp.json();
  if (!Array.isArray(data) || data.length === 0) {
    throw new Error("空、または配列ではない JSON が返りました。");
  }
  return data as PromptEntry[];
}
