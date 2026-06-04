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
  // Suno の Song Title 欄に流す値 (#844)。optional・後方互換: 無ければ呼び出し側が name で代替する。
  title?: string;
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

/** collection id 末尾の接尾辞。剥がしてから日付・channel・theme を解釈する。 */
const COLLECTION_SUFFIX = "-collection";

/**
 * collection id から Suno playlist 名 `<channel> | <theme>` を導出する純パーサ。
 * theme は `/collections` レスポンスの `name` field (= channel 部分を除いたテーマ slug) を渡す。
 * 引数 2 つを取る理由: channel 部分自体がハイフン区切り (例: `soulful-grooves`) になる
 * チャンネルがあり、id だけからは channel と theme の境界を機械的に判定できないため、
 * server 側で抽出済みの theme を逆向きに使って境界を確定する。
 *   1. 末尾 `-collection` を剥がす（無ければそのまま）
 *   2. 末尾が `-<theme>` で終わることを検証（不整合は fail-loud）
 *   3. theme を剥がした残りを `-` で分割し、先頭が 8 桁日付 (^\d{8}$) かつ parts >= 2 を検証
 *   4. 検証 NG は throw（fail-loud。silent に空文字や undefined を返さない）
 *   5. OK なら日付を除いた `parts.slice(1).join("-")` を channel として `<channel> | <theme>` を返す
 * 例:
 *   - `("20260601-rjn-dawn-cloud-fold-collection", "dawn-cloud-fold")` -> `"rjn | dawn-cloud-fold"`
 *   - `("20260520-soulful-grooves-midnight-mood-collection", "midnight-mood")` -> `"soulful-grooves | midnight-mood"`
 */
export function extractPlaylistName(
  collectionId: string,
  theme: string,
): string {
  if (!theme) {
    throw new Error(`theme が空: id=${collectionId}`);
  }
  const stripped = collectionId.endsWith(COLLECTION_SUFFIX)
    ? collectionId.slice(0, -COLLECTION_SUFFIX.length)
    : collectionId;
  const themeSuffix = `-${theme}`;
  if (!stripped.endsWith(themeSuffix)) {
    throw new Error(
      `theme と collection id が不整合: id=${collectionId} theme=${theme}`,
    );
  }
  const datePlusChannel = stripped.slice(0, -themeSuffix.length);
  const parts = datePlusChannel.split("-");
  if (parts.length < 2 || !/^\d{8}$/.test(parts[0])) {
    throw new Error(`不正な collection id 形式: ${collectionId}`);
  }
  const channel = parts.slice(1).join("-");
  if (!channel) {
    throw new Error(`channel 部分が空: id=${collectionId}`);
  }
  return `${channel} | ${theme}`;
}
