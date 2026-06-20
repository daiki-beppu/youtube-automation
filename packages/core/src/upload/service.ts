// 動画アップロードサービス境界（ADR-0003 §1）。Python の upload core
// （`utils/upload_core.py` + `agents/youtube_auto_uploader.py`）を 1 つの atomic service に
// 集約する。1 回の service call で resumable upload（`videos.insert`）→ thumbnail compress +
// set（`thumbnails.set`）→ metadata 反映までを順に行う。
//
// リトライ・バックオフは service が所有し、共通 `withRetry`（#959）に委譲する。quota（429）は
// ADR-0003 の retry 規約に従い retry せず、`domain: "quota"` + `retryAfterSeconds` の Result で
// caller へ返す。5xx 等の一時エラーは `withRetry` の既定予算（3 回）で再試行する。
// 入力 / 出力検証と `ServiceError` 変換は `createService` が担う。
//
// seam contract（テストの fake と一致させる契約）:
//   deps.youtube.videos.insert(params) -> { data: { id?: string } }
//     params: { part, requestBody: { snippet, status, localizations? }, media: { body } }
//   deps.youtube.thumbnails.set(params) -> { data: ... }
//     params: { videoId, media: { body } }
//   429 時は gaxios 形状 { response: { status: 429, headers: { "retry-after" } } } で reject。

import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";

import sharp from "sharp";

import { classifyGaxiosError } from "../errors.ts";
import type { YouTubeClient } from "../oauth/client.ts";
import { withRetry } from "../retry.ts";
import type { SleepMs } from "../retry.ts";
import { createService } from "../service-frame.ts";
import { MAX_THUMBNAIL_BYTES, UploadInput, UploadOutput } from "./schema.ts";

/**
 * uploadVideoService の注入依存。
 *
 * - `youtube`: 構築済み YouTube Data API クライアント（DI seam、ADR-0003 §7）
 * - `sleep`: `withRetry` のバックオフ待機注入点（省略時は実時間待機。テストは no-op を
 *   注入して 5xx → `domain:"api"` の retry パスを deterministic に検証する）
 */
export interface UploadDeps {
  youtube: YouTubeClient;
  sleep?: SleepMs;
}

// classifyGaxiosError / QuotaExhaustedError の message に載せる操作名。
const INSERT_CONTEXT = "videos.insert";

// 圧縮で試す JPEG 品質（高→低）。最初に上限以下になった結果を採用する。Python は ffmpeg の
// qscale を使うが scale が異なるため、sharp の品質値として独自に降順列を持つ。
const THUMBNAIL_JPEG_QUALITIES = [80, 60, 40, 20, 10] as const;

type ParsedMetadata = UploadInput["metadata"];

// 予約公開時刻を YouTube Data API 向けに正規化する（youtube_auto_uploader.py:31-56 移植）。
// timezone offset 付き（Z / ±HH:MM）は UTC の Z 終端へ変換し、naive・解析不能はそのまま返す
// （呼び出し側の入力を尊重する）。
const normalizePublishAt = (value: string): string => {
  const hasTimezone = /(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/u.test(value);
  if (!hasTimezone) {
    return value;
  }
  const epochMs = Date.parse(value);
  if (Number.isNaN(epochMs)) {
    return value;
  }
  return new Date(epochMs).toISOString().replace(/\.\d{3}Z$/u, "Z");
};

// status body を組み立てる。publishAt 指定時は予約公開要件として privacyStatus を private に
// 矯正し、正規化済み publishAt を載せる（youtube_auto_uploader.py:160-167）。
const buildStatus = (metadata: ParsedMetadata) => {
  const base = {
    containsSyntheticMedia: metadata.containsSyntheticMedia,
    privacyStatus: metadata.privacyStatus,
    selfDeclaredMadeForKids: metadata.selfDeclaredMadeForKids,
  };
  if (metadata.publishAt === undefined) {
    return base;
  }
  return {
    ...base,
    privacyStatus: "private",
    publishAt: normalizePublishAt(metadata.publishAt),
  };
};

// metadata を videos.insert の requestBody（snippet / status / localizations）へマップする
// （youtube_auto_uploader.py:176-189）。description / tags は YouTube 上限で truncate する。
const buildRequestBody = (metadata: ParsedMetadata) => {
  const snippet = {
    categoryId: metadata.categoryId,
    defaultAudioLanguage: metadata.language,
    defaultLanguage: metadata.language,
    description: metadata.description.slice(0, 5000),
    tags: metadata.tags.slice(0, 50),
    title: metadata.title,
  };
  const status = buildStatus(metadata);
  if (metadata.localizations === undefined) {
    return { snippet, status };
  }
  return { localizations: metadata.localizations, snippet, status };
};

// 動画ファイルの存在を先に確認する。欠落は insert を呼ばず io エラーへ倒す（fail fast、
// upload_core.py:107-109 が None を返していた箇所を境界 throw に置き換え）。
const assertVideoExists = async (file: string): Promise<void> => {
  try {
    await stat(file);
  } catch {
    throw new Error(`${file}: video file not found`);
  }
};

// resumable=true は stream を、false は buffer を media.body に使う（Python の
// MediaFileUpload(resumable=...) に対応する、実際に渡す body の差）。
const buildMediaBody = async (
  file: string,
  resumable: boolean
): Promise<NodeJS.ReadableStream | Buffer> =>
  resumable ? createReadStream(file) : await readFile(file);

// 1 回分の insert を実行し、失敗を domain エラーへ分類して投げ直す（withRetry に渡す 1-attempt
// 単位）。retry 可否は withRetry / defaultShouldRetry に委ねる。
const insertVideo = async (
  deps: UploadDeps,
  requestBody: ReturnType<typeof buildRequestBody>,
  mediaBody: NodeJS.ReadableStream | Buffer
) => {
  try {
    return await deps.youtube.videos.insert({
      media: { body: mediaBody, mimeType: "video/*" },
      part: Object.keys(requestBody),
      requestBody,
    });
  } catch (error) {
    throw classifyGaxiosError(error, INSERT_CONTEXT);
  }
};

// insert レスポンスから video ID を取り出す。id 欠落は upload 失敗として throw する
// （upload_core.py:216-219 が None を返していた箇所を境界 throw に置き換え → io）。
const extractVideoId = (response: {
  data?: { id?: string | null };
}): string => {
  const id = response.data?.id;
  if (typeof id !== "string" || id.length === 0) {
    throw new Error(`${INSERT_CONTEXT}: response is missing the video id`);
  }
  return id;
};

// サムネイルを上限以下のバイト列にする。上限未満はそのまま透過し、超過分は JPEG 品質を
// 段階的に下げて圧縮する（upload_core.py:256-284）。どの品質でも収まらなければ fail fast。
const compressThumbnail = async (path: string): Promise<Buffer> => {
  const original = await readFile(path);
  if (original.byteLength <= MAX_THUMBNAIL_BYTES) {
    return original;
  }
  for (const quality of THUMBNAIL_JPEG_QUALITIES) {
    const compressed = await sharp(original).jpeg({ quality }).toBuffer();
    if (compressed.byteLength <= MAX_THUMBNAIL_BYTES) {
      return compressed;
    }
  }
  throw new Error(
    `${path}: thumbnail could not be compressed under ${MAX_THUMBNAIL_BYTES} bytes`
  );
};

// 圧縮済みサムネイルを作成済み動画に設定する。失敗（compress 不能・`thumbnails.set` reject）は
// そのまま伝播させ、唯一の呼び出し元 `trySetThumbnail` が best-effort で吸収する（gaxios 分類は
// `trySetThumbnail` の catch が結果を必ず破棄するため行わない）。retry はしない: thumbnail 設定は
// insert 成功後の付随処理。
const setThumbnail = async (
  deps: UploadDeps,
  videoId: string,
  thumbnail: string
): Promise<void> => {
  const body = await compressThumbnail(thumbnail);
  await deps.youtube.thumbnails.set({
    media: { body, mimeType: "image/*" },
    videoId,
  });
};

// thumbnail を best-effort で設定し、成否を boolean で返す。compress 不能・`thumbnails.set`
// reject（API エラー含む）はここで吸収し true/false に倒す（握りつぶしではなく、戻り値
// thumbnailSet で結果を明示する契約）。insert は既に成功＝動画は作成済みのため、thumbnail 失敗で
// upload 全体を失敗させると作成済み videoId を破棄し再実行で重複アップロードになる。
//
// ここは Python から意図的に divergence する。Python `set_thumbnail`（upload_core.py:222-254）は
// 圧縮失敗（OSError）でのみ False を返して video_id を保持するが、API エラー（HttpError 429/5xx）
// では `YouTubeAPIError` を raise する。`upload()`（upload_core.py:135-147）の `except HttpError` は
// この `YouTubeAPIError` を捕捉しないため、thumbnail の API エラー時は video_id を返さず例外が
// 伝播する。TS は重複アップロード再実行を避けるため API エラーを含む全 thumbnail 失敗で動画を
// 捨てず videoId を Result へ載せ、状態整合を厳格化する。caller は thumbnailSet=false を見て
// thumbnail だけ再試行できる。
const trySetThumbnail = async (
  deps: UploadDeps,
  videoId: string,
  thumbnail: string
): Promise<boolean> => {
  try {
    await setThumbnail(deps, videoId, thumbnail);
    return true;
  } catch {
    return false;
  }
};

/**
 * 動画を 1 本アップロードし、結果を Result で返す（ADR-0003 §1）。
 *
 * 入力は `.strict()` schema で先に検証し、次に動画ファイルの存在を確認してから upload する
 * ため、不正入力・欠落ファイルは API に到達しない。`videos.insert`（resumable）→
 * `thumbnails.set`（thumbnail 指定時のみ）を 1 service call で実行する。
 *
 * insert が成功した時点で動画は YouTube 上に作成済みになる。thumbnail は付随処理（best-effort）
 * で、API エラーを含め失敗しても作成済み動画を捨てずに `ok({ videoId, thumbnailSet: false })` を
 * 返す。これにより insert 成功後の失敗で videoId を破棄して再実行が重複アップロードを生む状態
 * 不整合を防ぐ（Python は thumbnail の API エラーで video_id を失う＝意図的 divergence。詳細は
 * `trySetThumbnail` のコメント参照）。insert 自体の失敗（quota / 5xx / id 欠落等）は従来どおり
 * err を返す。
 */
export const uploadVideoService = createService(
  UploadInput,
  UploadOutput,
  async (request, deps: UploadDeps) => {
    await assertVideoExists(request.file);

    const body = buildRequestBody(request.metadata);
    // media は attempt ごとに作り直す。resumable=true の body は一度しか消費できない
    // fs.ReadStream のため、retry 間で使い回すと 2 回目以降が消費済み（空）の body を再送する。
    const response = await withRetry(
      async () =>
        insertVideo(
          deps,
          body,
          await buildMediaBody(request.file, request.resumable)
        ),
      { sleep: deps.sleep }
    );
    const videoId = extractVideoId(response);

    const thumbnailSet =
      request.thumbnail === undefined
        ? false
        : await trySetThumbnail(deps, videoId, request.thumbnail);

    return { thumbnailSet, videoId };
  }
);
