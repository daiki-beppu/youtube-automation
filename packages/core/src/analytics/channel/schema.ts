// channel-level 日次メトリクス service の入力 / 出力 schema（ADR-0003 §8: zod を
// source of truth）。
//
// 入力はチャンネル config / API レスポンス由来の JSON ではなく、呼び出し側
// （CLI / MCP）が組み立てる in-process な値オブジェクトのため、snake_case →
// camelCase の `.transform()` は不要で camelCase のまま declare する。型は `z.infer`
// で導出し並書の `interface` は持たない。`.strict()` で未知キーを reject（fail fast）。

import { z } from "zod";

// service が収集する channel-level メトリクス（契約文字列の単一定義）。出力 record の
// メトリクス検証と API 問い合わせ（`metrics` パラメータ・列名解決）の双方がこの 1 配列を
// 参照する。
export const CHANNEL_METRICS = [
  "views",
  "estimatedMinutesWatched",
  "subscribersGained",
] as const;

// 出力 record の `metric` は実行時に許可集合へ制約しつつ、infer 型は `string` のまま据え置く
// （narrowing する type-guard ではなく boolean 述語を渡す）。型を literal union に絞ると
// caller 側の LONG レコード組み立てが過度に硬くなるため、検証は実行時に閉じる。
const isChannelMetric = (value: string): boolean =>
  CHANNEL_METRICS.some((metric) => metric === value);

// YouTube Analytics の日付は YYYY-MM-DD（API の startDate / endDate / `day` 次元の形式）。
const isoDate = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/u, "must be a YYYY-MM-DD date");

/**
 * 1 回分の channel-analytics 収集リクエスト。
 *
 * - `channelId`: 対象チャンネル（`ids=channel==<id>` に載る）
 * - `startDate` / `endDate`: 収集期間（YYYY-MM-DD、両端含む）
 * - `videoId`: 指定時は `filters=video==<id>` で単一動画に絞る（`ids` は channel のまま）
 */
export const ChannelAnalyticsInput = z
  .object({
    channelId: z.string(),
    endDate: isoDate,
    startDate: isoDate,
    videoId: z.string().optional(),
  })
  .strict();
export type ChannelAnalyticsInput = z.infer<typeof ChannelAnalyticsInput>;

/**
 * 集計結果（LONG フォーマット）。1 メトリクス × 1 日 = 1 レコード。
 *
 * caller（CLI / MCP / 分析層）が `metric` でフィルタして期間合計を出せるよう、wide な
 * 行ではなく `{ date, metric, value }` のセル単位で返す（ADR-0003 §8 / 計画 §4-1）。
 */
export const ChannelAnalyticsOutput = z
  .object({
    metrics: z.array(
      z
        .object({
          date: z.string(),
          metric: z
            .string()
            .refine(isChannelMetric, "unsupported channel metric"),
          value: z.number(),
        })
        .strict()
    ),
  })
  .strict();
export type ChannelAnalyticsOutput = z.infer<typeof ChannelAnalyticsOutput>;
