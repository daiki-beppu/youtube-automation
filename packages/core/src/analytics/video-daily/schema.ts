// video × day 日次メトリクス service の入力 / 出力 schema（ADR-0003 §8: zod を
// source of truth）。
//
// 入力はチャンネル config / API レスポンス由来の JSON ではなく、呼び出し側
// （CLI / MCP）が組み立てる in-process な値オブジェクトのため、snake_case →
// camelCase の `.transform()` は不要で camelCase のまま declare する。型は `z.infer`
// で導出し並書の `interface` は持たない。`.strict()` で未知キーを reject（fail fast）。

import { z } from "zod";

// YouTube Analytics の日付は YYYY-MM-DD（API の startDate / endDate / `day` 次元の形式）。
const isoDate = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/u, "must be a YYYY-MM-DD date");

/**
 * 1 回分の video×day analytics 収集リクエスト。
 *
 * - `channelId`: 対象チャンネル（`ids=channel==<id>` に載る）
 * - `startDate` / `endDate`: 収集期間（YYYY-MM-DD、両端含む）
 * - `videoIds`: 指定時は `filters=video==<id>,<id>` で対象動画に絞る（`ids` は channel
 *   のまま）。省略・空配列なら絞り込みなし（channel 全体）。
 */
export const CollectVideoDailyAnalyticsInput = z
  .object({
    channelId: z.string(),
    endDate: isoDate,
    startDate: isoDate,
    videoIds: z.array(z.string()).optional(),
  })
  .strict();
export type CollectVideoDailyAnalyticsInput = z.infer<
  typeof CollectVideoDailyAnalyticsInput
>;

/**
 * 集計結果（ADR-0003 canonical template の output 形状: `{ metrics: [...] }`）。
 * video×day の 1 行 = `metrics` 配列の 1 レコード（`views` のみ。impressions / CTR は
 * この dimension では Analytics API 非公開）。
 */
export const CollectVideoDailyAnalyticsOutput = z
  .object({
    metrics: z.array(
      z
        .object({
          date: z.string(),
          videoId: z.string(),
          views: z.number(),
        })
        .strict()
    ),
  })
  .strict();
export type CollectVideoDailyAnalyticsOutput = z.infer<
  typeof CollectVideoDailyAnalyticsOutput
>;
