// yt-collection-serve の `/suno/prompts.json` クライアント。
// 旧 `popup.js` の fetch ロジックを保持する:
//   - fetch 先は `${baseUrl}${PROMPTS_ROUTE}`
//   - HTTP 非 2xx で throw
//   - 配列でない / 空配列の JSON で throw (fail-loud、silent 続行しない)
import {
  collectionPromptsRoute,
  COLLECTIONS_ROUTE,
  PROMPTS_ROUTE,
} from "./constants";

/** `/suno/prompts.json` が返す 1 パターンのスキーマ (#692 サーバー契約)。 */
export interface PromptEntry {
  name: string;
  style: string;
  lyrics: string;
}

/** `/collections` が返す 1 collection のスキーマ (#816 dir mode サーバー契約)。 */
export interface CollectionSummary {
  id: string;
  name: string;
  has_prompts: boolean;
  pattern_count: number | null;
}

/**
 * prompts.json 系エンドポイントの共通 fetch 本体 (#816)。
 * 非 2xx / 空配列 / 非配列で throw する fail-loud 契約。
 */
async function fetchPromptArray(url: string): Promise<PromptEntry[]> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const data: unknown = await resp.json();
  if (!Array.isArray(data) || data.length === 0) {
    throw new Error("空、または配列ではない JSON が返りました。");
  }
  return data as PromptEntry[];
}

/** prompts.json を取得して PromptEntry[] を返す。不正な応答は fail-loud で throw。 */
export async function fetchPrompts(baseUrl: string): Promise<PromptEntry[]> {
  return fetchPromptArray(`${baseUrl}${PROMPTS_ROUTE}`);
}

/**
 * dir mode サーバーの collection 一覧を取得する (#816)。
 * 非 2xx は fail-loud で throw（単一 mode サーバーの 404 は popup の fallback トリガー）。
 * 空配列は throw せず返す（fallback 判断は呼び出し側）。
 */
export async function fetchCollections(
  baseUrl: string,
): Promise<CollectionSummary[]> {
  const resp = await fetch(`${baseUrl}${COLLECTIONS_ROUTE}`);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const data: unknown = await resp.json();
  if (!Array.isArray(data)) {
    throw new Error("配列ではない JSON が返りました。");
  }
  return data as CollectionSummary[];
}

/**
 * 指定 collection の prompts.json を取得する (#816)。
 * fetchPrompts と同じ fail-loud 契約（非 2xx / 空配列 / 非配列で throw）。
 */
export async function fetchCollectionPrompts(
  baseUrl: string,
  id: string,
): Promise<PromptEntry[]> {
  return fetchPromptArray(`${baseUrl}${collectionPromptsRoute(id)}`);
}

/**
 * ドロップダウンの初期選択 id を決める (#816)。
 * 最初の `has_prompts===true` な entry の id。実行可能な選択肢が無ければ null。
 */
export function pickInitialCollectionId(
  collections: CollectionSummary[],
): string | null {
  return collections.find((c) => c.has_prompts)?.id ?? null;
}
