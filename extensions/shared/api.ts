// yt-collection-serve の `/suno/prompts.json` クライアント。
// 旧 `popup.js` の fetch ロジックを保持する:
//   - fetch 先は `${baseUrl}${PROMPTS_ROUTE}`
//   - HTTP 非 2xx で throw
//   - 配列でない / 空配列の JSON で throw (fail-loud、silent 続行しない)
import {
  collectionPromptsRoute,
  COLLECTIONS_ROUTE,
  PLAYLISTS_CAPTURE_ROUTE,
  PROMPTS_ROUTE,
} from "./constants";

/** `/suno/prompts.json` が返す 1 パターンのスキーマ (#692 サーバー契約)。 */
export interface PromptEntry {
  name: string;
  // Suno の Song Title 欄に流す値 (#844)。optional・後方互換: 無ければ呼び出し側が name で代替する。
  title?: string;
  style: string;
  lyrics: string;
  // --- Custom Mode > More Options の 3 フィールド (#900) ---
  // いずれも optional・後方互換。命名は wire 形 snake_case で TS/Python/サーバー契約を統一する。
  // 値が無い (undefined) entry は拡張側で fail-soft に skip される（既存 collection の後方互換）。
  /** Style Influence slider (0-100 整数)。Suno の Style Influence 欄へ注入。 */
  style_influence?: number;
  /** Weirdness slider (0-100 整数)。Suno の Weirdness 欄へ注入。 */
  weirdness?: number;
  /** Exclude styles free text。Suno の Exclude styles 欄へ注入。 */
  exclude_styles?: string;
}

/** `/collections` が返す 1 collection のスキーマ (#816 dir mode サーバー契約)。 */
export interface CollectionSummary {
  id: string;
  name: string;
  has_prompts: boolean;
  pattern_count: number | null;
  // 既に config/suno-playlists.json にマッピング済みか (#893 追加要件 B)。
  // optional・後方互換: prefix 未設定の旧サーバーは返さず undefined（全件表示の従来挙動）。
  mapped?: boolean;
}

/** Suno `/me` から捕捉した 1 playlist (#893)。POST /suno/playlists の body 要素。 */
export interface CapturedPlaylist {
  title: string;
  url: string;
}

/** POST /suno/playlists の 200 レスポンス (#893)。書き込み件数と出力先パス。 */
export interface CapturedPlaylistsResult {
  written: number;
  path: string;
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

/**
 * 捕捉した playlist 一覧を POST /suno/playlists へ送る (#893)。
 * body は配列のまま（envelope 包みしない）。非 2xx はステータスを含めて throw する fail-loud 契約。
 * prefix によるフィルタはサーバー側 normalize_suno_title に閉じるため、ここでは全件そのまま送る。
 */
export async function postCapturedPlaylists(
  baseUrl: string,
  items: CapturedPlaylist[],
): Promise<CapturedPlaylistsResult> {
  const resp = await fetch(`${baseUrl}${PLAYLISTS_CAPTURE_ROUTE}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return (await resp.json()) as CapturedPlaylistsResult;
}

/**
 * 既にマッピング済み (mapped===true) の collection を除外する純関数 (#893 追加要件 B)。
 * mapped 未設定（prefix 未指定の旧運用）は除外対象にしないため全件残す（後方互換）。
 */
export function excludeMappedCollections(
  collections: CollectionSummary[],
): CollectionSummary[] {
  return collections.filter((c) => c.mapped !== true);
}
