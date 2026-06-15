// 動画別 analytics サービス境界の入力 / 出力 schema（ADR-0003 §8: zod を source of truth）。
//
// 入力はチャンネル config / API レスポンス由来の JSON ではなく、呼び出し側（CLI / MCP）が
// 組み立てる in-process な値オブジェクトのため、snake_case → camelCase の `.transform()`
// は不要で camelCase のまま declare する（image/schema.ts と同形）。型は `z.infer` で導出し
// 並書の `interface` は持たない。`.strict()` で未知キーを reject（fail fast）。

import { z } from "zod";

// YouTube Analytics の日付パラメータ書式（YYYY-MM-DD）。input 境界で先に弾く。
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/u;

/**
 * API メトリクス名 → 出力メトリクス名の対応表（contract、single source of truth）。
 *
 * `reports.query` の `metrics` パラメータ（apiName を join）と、melt 時のリネーム
 * （API の `comments` を出力では `commentCount` に正規化）の双方がここを参照する。
 * 列の解決は columnHeaders[].name 経由で位置非依存に行うため、順序は metrics 文字列の
 * 並びを決めるだけで melt の正しさには影響しない。
 */
export const METRIC_COLUMNS = [
  { apiName: "views", outName: "views" },
  { apiName: "likes", outName: "likes" },
  { apiName: "comments", outName: "commentCount" },
  { apiName: "averageViewDuration", outName: "averageViewDuration" },
] as const;

/** Analytics クエリで video dimension を表す列名。 */
export const VIDEO_DIMENSION = "video";

/**
 * 動画別 analytics の取得リクエスト。
 *
 * - `channelId`: 必須。`ids=channel==<channelId>` にエンコードされる（video 単体では
 *   Analytics クエリを scope できないため channelId は省略不可）
 * - `videoId`: 省略可。指定時のみ `filters=video==<videoId>` で 1 動画に絞り込む
 * - `startDate` / `endDate`: YYYY-MM-DD。書式違反は境界で validation エラーになる
 */
export const CollectVideoAnalyticsInput = z
  .object({
    channelId: z.string().min(1),
    endDate: z.string().regex(ISO_DATE),
    startDate: z.string().regex(ISO_DATE),
    videoId: z.string().min(1).optional(),
  })
  .strict();
export type CollectVideoAnalyticsInput = z.infer<
  typeof CollectVideoAnalyticsInput
>;

/**
 * 動画別 analytics の取得結果（long/tidy melt: 1 レコード = 1 (video, metric)）。
 *
 * - `videoId` / `value` は API レスポンス（行データ）由来のため schema で検証する
 * - `metric` は {@link METRIC_COLUMNS} の outName（内部定数）に限られ、API 由来ではない
 *   ため `z.string()` で受ける（自前定数の二重検証を避ける）
 */
export const CollectVideoAnalyticsOutput = z
  .object({
    metrics: z.array(
      z.object({
        metric: z.string(),
        value: z.number(),
        videoId: z.string(),
      })
    ),
  })
  .strict();
export type CollectVideoAnalyticsOutput = z.infer<
  typeof CollectVideoAnalyticsOutput
>;
