// MAIN world fetch bridge の純関数群 (#948)。
//
// 「Remix ボタン disabled = 生成中」の DOM プロキシは、現在の Suno UI では生成完了後も
// disabled が残るため in-flight を大幅に過大カウントし（実測: disabled 20 clips 中 16 が
// API status "complete"）、queue 空き待ちの常態化 → 300 秒 timeout → ERROR 停止を招いていた。
// 正確な一次情報は Suno API の clip status であり、本モジュールはその観測に使う
// URL 判定・ヘッダ抽出・レスポンス解析を純関数として提供する（bridge 本体は
// entrypoints/suno-bridge.content.ts、集計は lib/clip-tracker.ts）。
//
// レスポンス解析は fail-soft（形が崩れていたら null）。観測の失敗で生成フローを
// 止めないため、throw しない。
import { FEED_ENDPOINT_PATH, GENERATE_ENDPOINT_PATH, type ObservedClip, SUNO_API_ORIGIN } from "../../shared/constants";

/** fetch の第 1 引数から URL 文字列を解決する。Request / URL / string を受ける。 */
export function resolveRequestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

/** Suno studio API へのリクエストか。Authorization 捕捉の対象判定に使う。 */
export function isSunoApiUrl(url: string): boolean {
  return url.startsWith(SUNO_API_ORIGIN);
}

/** 生成投入 endpoint へのリクエストか。 */
export function isGenerateRequest(url: string): boolean {
  return isSunoApiUrl(url) && url.includes(GENERATE_ENDPOINT_PATH);
}

/** clip status 照会（feed）endpoint へのリクエストか。`/api/feed/v2` 等の version 違いも prefix で拾う。 */
export function isFeedRequest(url: string): boolean {
  return isSunoApiUrl(url) && url.includes(FEED_ENDPOINT_PATH);
}

/**
 * fetch 引数から Authorization ヘッダ値を抽出する。Headers / 配列 / record / Request の
 * いずれの形でも拾う（Suno は record 形式だが、ライブラリ経由の将来変化に耐える）。
 * 見つからなければ null。
 */
export function extractAuthHeader(input: RequestInfo | URL, init?: RequestInit): string | null {
  const fromHeaders = (headers: HeadersInit | undefined): string | null => {
    if (!headers) {
      return null;
    }
    if (headers instanceof Headers) {
      return headers.get("authorization");
    }
    if (Array.isArray(headers)) {
      const hit = headers.find(([name]) => name.toLowerCase() === "authorization");
      return hit ? hit[1] : null;
    }
    const record = headers as Record<string, string>;
    const key = Object.keys(record).find((name) => name.toLowerCase() === "authorization");
    return key ? record[key] : null;
  };
  const fromInit = fromHeaders(init?.headers);
  if (fromInit) {
    return fromInit;
  }
  if (typeof Request !== "undefined" && input instanceof Request) {
    return input.headers.get("authorization");
  }
  return null;
}

/** unknown JSON から `{id, status}` を持つ clip 配列を fail-soft で取り出す共通処理。 */
function parseClipArray(value: unknown): ObservedClip[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const clips: ObservedClip[] = [];
  for (const item of value) {
    if (
      typeof item === "object" &&
      item !== null &&
      typeof (item as { id?: unknown }).id === "string" &&
      typeof (item as { status?: unknown }).status === "string"
    ) {
      clips.push({
        id: (item as { id: string }).id,
        status: (item as { status: string }).status,
      });
    }
  }
  return clips.length > 0 ? clips : null;
}

/** feed レスポンス専用: metadata.duration が finite number の場合だけ ObservedClip に含める。 */
function parseFeedClipArray(value: unknown): ObservedClip[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const clips: ObservedClip[] = [];
  for (const item of value) {
    if (
      typeof item === "object" &&
      item !== null &&
      typeof (item as { id?: unknown }).id === "string" &&
      typeof (item as { status?: unknown }).status === "string"
    ) {
      const duration = (item as { metadata?: { duration?: unknown } }).metadata?.duration;
      clips.push({
        id: (item as { id: string }).id,
        status: (item as { status: string }).status,
        ...(typeof duration === "number" && Number.isFinite(duration) ? { duration } : {}),
      });
    }
  }
  return clips.length > 0 ? clips : null;
}

/**
 * 生成投入レスポンス（POST /api/generate/v2-web/）から投入 clip を取り出す。
 * 形: `{ id: <batch>, clips: [{id, status: "submitted", ...}, ...] }`（chrome-devtools 実機観測）。
 * 形が崩れていたら null（fail-soft）。
 */
export function parseClipsFromGenerateResponse(json: unknown): ObservedClip[] | null {
  if (typeof json !== "object" || json === null) {
    return null;
  }
  return parseClipArray((json as { clips?: unknown }).clips);
}

/**
 * feed レスポンス（GET /api/feed/v2?ids=... / POST /api/feed/v3）から clip status を取り出す。
 * 形は `{ clips: [...] }` と素の配列の両方を観測しているため両対応する。
 * 形が崩れていたら null（fail-soft）。
 */
export function parseClipsFromFeedResponse(json: unknown): ObservedClip[] | null {
  if (Array.isArray(json)) {
    return parseFeedClipArray(json);
  }
  if (typeof json !== "object" || json === null) {
    return null;
  }
  return parseFeedClipArray((json as { clips?: unknown }).clips);
}
