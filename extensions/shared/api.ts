// yt-collection-serve の `/suno/prompts.json` クライアント。
// 旧 `popup.js` の fetch ロジックを保持する:
//   - fetch 先は `${baseUrl}${PROMPTS_ROUTE}`
//   - HTTP 非 2xx で throw
//   - 配列でない / 空配列の JSON で throw (fail-loud、silent 続行しない)
import {
  collectionPromptsRoute,
  COLLECTIONS_ROUTE,
  DOWNLOADED_ROUTE,
  DISTROKID_COLLECTIONS_ROUTE,
  DISTROKID_RELEASES_ROUTE,
  PROMPTS_ROUTE,
  VERSION_ROUTE,
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
  /**
   * Voice section の Male / Female ボタン (Suno UI)。"male" / "female" のみ対応ボタンを click する。
   * "neutral" / "auto" / undefined は何もしない（既選択を解除しない、"Auto = Suno に任せる"解釈）。
   * Suno 側の解釈とサーバー契約を揃えるため空文字は許容せず Python 側で省略する。
   */
  vocal_gender?: "male" | "female" | "neutral" | "auto";
}

/** collection の状態 (#1216)。サーバーがファイルシステムから動的に判定する。
 * - `needs_prompts`: suno-prompts.json が未作成
 * - `ready`: prompts 存在・ダウンロード未完了
 * - `downloaded`: 02-Individual-music/ に期待数以上の音声ファイルがある */
export type CollectionStatus = "needs_prompts" | "ready" | "downloaded";

/** `/collections` が返す 1 collection のスキーマ (#816 dir mode サーバー契約)。
 * #1216 BREAKING: has_prompts / mapped を廃止し status / downloaded_count に置換。 */
export interface CollectionSummary {
  id: string;
  name: string;
  status: CollectionStatus;
  pattern_count: number | null;
  downloaded_count: number;
  expected_file_count?: number | null;
}

/** Suno `/me` から捕捉した 1 playlist。legacy scrape 互換の内部型。 */
export interface CapturedPlaylist {
  title: string;
  url: string;
}

/** GET /version の wire スキーマ（#1023）。 */
export interface ServerVersionInfo {
  version: string;
  min_extension_version: string;
}

export type CompatibilityResult =
  | {
      status: "compatible" | "incompatible";
      serverVersion: string;
      minExtensionVersion: string;
      extensionVersion: string;
    }
  | {
      status: "skipped";
      reason: "version-endpoint-unavailable";
    }
  | {
      status: "error";
      message: string;
    };

export function formatCompatibilityWarning(
  compatibility: CompatibilityResult,
): string {
  if (compatibility.status !== "incompatible") {
    return "";
  }
  return `拡張を更新してください（拡張 ${compatibility.extensionVersion} / 必要 ${compatibility.minExtensionVersion} / サーバー ${compatibility.serverVersion}）。`;
}

export async function resolveCompatibilityWarning(
  baseUrl: string,
  extensionVersion: string,
): Promise<string> {
  const compatibility = await checkServerCompatibility(
    baseUrl,
    extensionVersion,
  );
  return formatCompatibilityWarning(compatibility);
}

const SEMVER_PATTERN = /^\d+\.\d+\.\d+$/;

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

function assertSemver(value: unknown, field: string): string {
  if (typeof value !== "string" || !SEMVER_PATTERN.test(value)) {
    throw new Error(`${field} must be semver`);
  }
  return value;
}

function compareSemver(left: string, right: string): number {
  const leftParts = left.split(".").map(Number);
  const rightParts = right.split(".").map(Number);
  for (let i = 0; i < leftParts.length; i += 1) {
    const diff = leftParts[i] - rightParts[i];
    if (diff !== 0) {
      return diff;
    }
  }
  return 0;
}

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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

/** サーバー version envelope を取得する（#1023）。404 は caller が旧サーバー判定に使う。 */
export async function fetchServerVersion(
  baseUrl: string,
): Promise<ServerVersionInfo> {
  const resp = await fetch(`${normalizeBaseUrl(baseUrl)}${VERSION_ROUTE}`);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const data: unknown = await resp.json();
  if (typeof data !== "object" || data === null) {
    throw new Error("version response must be object");
  }
  const record = data as Record<string, unknown>;
  const minExtensionVersion = assertSemver(
    record.min_extension_version,
    "min_extension_version",
  );
  return {
    version: assertSemver(record.version, "version"),
    min_extension_version: minExtensionVersion,
  };
}

/** 拡張 version がサーバーの最低要求を満たすか確認する（#1023）。 */
export async function checkServerCompatibility(
  baseUrl: string,
  extensionVersion: string,
): Promise<CompatibilityResult> {
  try {
    const info = await fetchServerVersion(baseUrl);
    const result = {
      serverVersion: info.version,
      minExtensionVersion: info.min_extension_version,
      extensionVersion,
    };
    if (compareSemver(extensionVersion, info.min_extension_version) < 0) {
      return { status: "incompatible", ...result };
    }
    return { status: "compatible", ...result };
  } catch (error) {
    const message = messageFromError(error);
    if (message === "HTTP 404") {
      return { status: "skipped", reason: "version-endpoint-unavailable" };
    }
    return { status: "error", message };
  }
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

/** popup の実行対象一覧に出す collection。完了済みは次の作業対象ではないため非表示にする。 */
export function visiblePromptCollections(
  collections: CollectionSummary[],
  includeDownloadedIds: string[] = [],
): CollectionSummary[] {
  const include = new Set(includeDownloadedIds);
  return collections.filter(
    (c) => c.status !== "downloaded" || include.has(c.id),
  );
}

/**
 * ドロップダウンの初期選択 id を決める (#816)。
 * 最初の `ready` な entry の id。実行可能な選択肢が無ければ null。
 * #1216: has_prompts → status ベースに移行。
 */
export function pickInitialCollectionId(
  collections: CollectionSummary[],
): string | null {
  return collections.find((c) => c.status === "ready")?.id ?? null;
}

export function resolvePromptCollectionId(
  collections: CollectionSummary[],
  selectedId: string,
  allowDownloadedSelected = false,
): string | null {
  const selected = collections.find((c) => c.id === selectedId);
  if (
    selected &&
    (selected.status === "ready" ||
      (allowDownloadedSelected && selected.status === "downloaded"))
  ) {
    return selected.id;
  }
  return pickInitialCollectionId(collections);
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

/** DistroKid `/distrokid/collections` が返す 1 disc のスキーマ (#934 dir mode サーバー契約)。 */
export interface DistrokidCollectionSummary {
  collection_id: string;
  name: string;
  disc: string;
  album_title: string;
  track_count: number;
  released: boolean;
}

/** POST /distrokid/releases の body (#934)。配信済みとして記録する disc の識別情報。 */
export interface DistrokidReleaseRecord {
  collection_id: string;
  disc: string;
  album_title: string;
}

/**
 * DistroKid dir mode サーバーの disc 一覧を取得する (#934)。
 * 非 2xx は fail-loud で throw（単一 mode サーバーの 404 は popup の fallback トリガー）。
 * 空配列は throw せず返す（0 件 = 未配信 disc なしの正常ケース）。
 */
export async function fetchDistrokidCollections(
  baseUrl: string,
): Promise<DistrokidCollectionSummary[]> {
  const resp = await fetch(`${baseUrl}${DISTROKID_COLLECTIONS_ROUTE}`);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const data: unknown = await resp.json();
  if (!Array.isArray(data)) {
    throw new Error("配列ではない JSON が返りました。");
  }
  return data as DistrokidCollectionSummary[];
}

/**
 * 配信済み (released===true) の disc を除外する純関数 (#934)。
 * fetchDistrokidCollections の結果から popup のドロップダウンに出す候補を絞る。
 */
export function excludeReleasedDiscs(
  list: DistrokidCollectionSummary[],
): DistrokidCollectionSummary[] {
  return list.filter((item) => item.released !== true);
}

/**
 * フィル完了後に配信済みとして記録する (#934)。POST /distrokid/releases。
 * 失敗は caller が warn 表示するだけで、フィル成功を覆さない補助機能として扱う。
 * 非 2xx は fail-loud で throw する（caller が warn 処理する）。
 */
export async function recordDistrokidRelease(
  baseUrl: string,
  record: DistrokidReleaseRecord,
): Promise<void> {
  const resp = await fetch(`${baseUrl}${DISTROKID_RELEASES_ROUTE}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(record),
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
}

/** POST /collections/:id/downloaded の body (#1215)。ダウンロード完了通知ペイロード。 */
export interface DownloadedPayload {
  file_count: number;
  expected_file_count?: number;
  format: "mp3" | "m4a" | "wav";
  suno_playlist_url?: string;
  download_path?: string;
}

/**
 * ダウンロード完了をサーバーに通知する (#1215)。POST /collections/:id/downloaded。
 * 非 2xx は fail-loud で throw する。
 */
async function fetchServeToken(baseUrl: string): Promise<string> {
  const res = await fetch(`${baseUrl}/auth/token`);
  if (!res.ok) throw new Error(`GET /auth/token failed: ${res.status}`);
  const data: unknown = await res.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("token" in data) ||
    typeof (data as Record<string, unknown>).token !== "string" ||
    !(data as Record<string, unknown>).token
  ) {
    throw new Error("/auth/token returned invalid response");
  }
  const token = (data as Record<string, string>).token;
  return token;
}

export async function postDownloaded(
  baseUrl: string,
  collectionId: string,
  payload: DownloadedPayload,
): Promise<void> {
  if (payload.download_path && !payload.suno_playlist_url) {
    throw new Error("download_path を送る場合は suno_playlist_url が必要です");
  }
  const token = await fetchServeToken(baseUrl);
  const url = `${baseUrl}${DOWNLOADED_ROUTE.replace(":id", encodeURIComponent(collectionId))}`;
  let res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Serve-Token": token },
    body: JSON.stringify(payload),
  });
  // 403 retry: token may be stale after server restart
  if (res.status === 403) {
    const freshToken = await fetchServeToken(baseUrl);
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Serve-Token": freshToken,
      },
      body: JSON.stringify(payload),
    });
  }
  if (!res.ok) {
    throw new Error(`POST downloaded failed: ${res.status} ${res.statusText}`);
  }
}
