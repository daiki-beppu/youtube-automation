// 動画アップロードサービス境界の入力 / 出力 schema（ADR-0003 §8: zod を source of truth）。
//
// 入力はチャンネル config / API レスポンス由来の JSON ではなく、呼び出し側（CLI / MCP）が
// 組み立てる in-process な値オブジェクトのため、snake_case → camelCase の `.transform()`
// は不要で camelCase のまま declare する（image/schema.ts と同形）。型は `z.infer` で導出し
// 並書の `interface` は持たない。`.strict()` で未知キーを reject（fail fast）。
//
// metadata→YouTube body のマッピングは Python `youtube_auto_uploader.py:144-198` を移植する。
// `categoryId` / `language` / `privacyStatus` / AI 開示フラグは現行プロダクションの既定値
// （music=10 / en / private / synthetic=true / made-for-kids=false、#603 / #605）を
// `.default()` で 1 箇所に解決し、各値を上書きしたい呼び出し元は明示的に渡せる経路を残す。

import { z } from "zod";

// YouTube が許容するサムネイルの最大バイト数（upload_policy.py:11）。超過分はこのサービスが
// compress し、未満はそのまま透過する。zod schema 外（service の圧縮判断）でも参照する契約値。
export const MAX_THUMBNAIL_BYTES = 2_097_152;

// YouTube のタイトル長上限。超過は truncate ではなく validation error にする
// （youtube_auto_uploader.py:146-147 の ValueError 相当）。
const MAX_TITLE_LENGTH = 100;

// 公開ステータスの許容値。enum 外の値（"semi-public" 等）は境界で validation error になる。
const PRIVACY_STATUSES = ["public", "private", "unlisted"] as const;

/**
 * 1 ロケール分のローカライズタイトル / 説明文。YouTube `localizations.<lang>` の形状。
 * `.strict()` で未知キーを弾き、`videos.insert` の body へそのまま載せる。
 */
const Localization = z
  .object({
    description: z.string(),
    title: z.string(),
  })
  .strict();

/**
 * 動画メタデータ。`title` のみ上限超過を reject し、`description` / `tags` は YouTube 上限で
 * truncate する（service 側のマッピングで実施、Python parity）。既定値を持つフィールドは
 * 省略可で、未指定時に現行プロダクションの振る舞いへ解決される。
 */
const VideoMetadataInput = z
  .object({
    // snippet.categoryId。既定は YouTube の Music カテゴリ "10"。
    categoryId: z.string().default("10"),
    // AI 開示（status.containsSyntheticMedia）。AI 生成音楽主軸のため既定 true（#603）。
    containsSyntheticMedia: z.boolean().default(true),
    description: z.string(),
    // snippet.defaultLanguage / defaultAudioLanguage の双方に使う言語コード。既定 "en"。
    language: z.string().default("en"),
    // YouTube `localizations`。指定時のみ body に載る。
    localizations: z.record(z.string(), Localization).optional(),
    privacyStatus: z.enum(PRIVACY_STATUSES).default("private"),
    // 予約公開時刻。指定時は privacyStatus が private に矯正され UTC(Z) へ正規化される（#647）。
    publishAt: z.string().optional(),
    // 子供向け申告（status.selfDeclaredMadeForKids）。既定 false（#605）。
    selfDeclaredMadeForKids: z.boolean().default(false),
    tags: z.array(z.string()),
    title: z.string().max(MAX_TITLE_LENGTH),
  })
  .strict();

/**
 * アップロード 1 件分のリクエスト。
 *
 * - `file`: アップロードする動画ファイルのパス（存在しなければ io エラー）
 * - `metadata`: snippet / status へマップされる動画メタデータ
 * - `thumbnail`: 省略可。指定時のみ insert 成功後に `thumbnails.set` を実行する
 * - `resumable`: 省略可（既定 true）。Python `MediaFileUpload(resumable=True)` 相当。
 *   true は stream を、false は buffer を `media.body` として `videos.insert` へ渡す
 */
export const UploadInput = z
  .object({
    file: z.string(),
    metadata: VideoMetadataInput,
    resumable: z.boolean().default(true),
    thumbnail: z.string().optional(),
  })
  .strict();
// 解決後（`.parse` 出力）の型。default 付きフィールドは確定値を持つ。service 内部で扱う。
export type UploadInput = z.infer<typeof UploadInput>;

/**
 * アップロード結果。
 *
 * - `videoId`: 作成された動画 ID（`videos.insert` レスポンス由来）
 * - `thumbnailSet`: サムネイルを設定したか（thumbnail 未指定なら false）
 */
export const UploadOutput = z
  .object({
    thumbnailSet: z.boolean(),
    videoId: z.string(),
  })
  .strict();
export type UploadOutput = z.infer<typeof UploadOutput>;
