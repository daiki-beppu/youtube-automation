// channel-level 日次メトリクス収集の service 境界（ADR-0003 §1）。Python
// `utils/channel_analytics.py` の `get_channel_analytics` / `_process_daily_data` を
// 翻訳せず TS で新規記述したもの（ADR-0003）。
//
// 構築済みの YouTube Analytics クライアントを `deps` で受け取り（ADR-0003 §7 / DI
// seam）、`reports.query` の wide な行列を `{ date, metric, value }` の LONG レコードへ
// reshape して `Result` で返す。core 内部（query / reshape）は throw OK。境界の
// `createService` で `toServiceError` 経由に集約し、CLI/MCP は `if (!r.ok)` で discriminate
// する。マッピング:
//   - schema 違反（未知キー / 非 YYYY-MM-DD）→ err(domain "validation")（zod ZodError）
//   - 429 quota                              → err(domain "quota" + retryAfterSeconds)
//   - その他の API エラー（403 等）          → err(domain "api")
//   - 成功                                   → ok({ metrics })
//
// retry / backoff は本 service が所有せず共通 `withRetry`（#959）に委譲する。quota は
// retry せず Result で caller へ返し（ADR-0003）、4xx は恒久エラーとして retry しない。

import type { youtubeAnalytics_v2 } from "googleapis";

import { withRetry } from "../../retry.ts";
import type { SleepMs } from "../../retry.ts";
import { createService } from "../../service.ts";
import { requireHeaders, resolveColumnIndex } from "../columns.ts";
import { executeQuery, shouldRetryAnalyticsQuery } from "../query.ts";
import {
  CHANNEL_METRICS,
  ChannelAnalyticsInput,
  ChannelAnalyticsOutput,
} from "./schema.ts";

// API 問い合わせの契約文字列（YouTube Analytics v2 の語彙、単一定義）。
const QUERY_CONTEXT = "channel analytics query";
const DAY_DIMENSION = "day";
const CHANNEL_ID_PREFIX = "channel==";
const VIDEO_FILTER_PREFIX = "video==";

type ChannelMetricRecord = ChannelAnalyticsOutput["metrics"][number];
type QueryParams = youtubeAnalytics_v2.Params$Resource$Reports$Query;
type QueryResponse = youtubeAnalytics_v2.Schema$QueryResponse;
interface ChannelAnalyticsDeps {
  readonly sleep?: SleepMs;
  readonly youtubeAnalytics: youtubeAnalytics_v2.Youtubeanalytics;
}

const buildQueryParams = (input: ChannelAnalyticsInput): QueryParams => ({
  dimensions: DAY_DIMENSION,
  endDate: input.endDate,
  // videoId 指定時のみ単一動画へ絞る（ids は channel のまま）。
  ...(input.videoId
    ? { filters: `${VIDEO_FILTER_PREFIX}${input.videoId}` }
    : {}),
  ids: `${CHANNEL_ID_PREFIX}${input.channelId}`,
  metrics: CHANNEL_METRICS.join(","),
  startDate: input.startDate,
});

const reshapeToLongFormat = (data: QueryResponse): ChannelMetricRecord[] => {
  // データ無しの期間は API が `rows` を省く（v2.d.ts contract）→ 空配列で ok。
  const { rows } = data;
  if (!rows) {
    return [];
  }
  const headers = requireHeaders(data, QUERY_CONTEXT);
  const dayIndex = resolveColumnIndex(headers, DAY_DIMENSION, QUERY_CONTEXT);
  const metricColumns = CHANNEL_METRICS.map((metric) => ({
    index: resolveColumnIndex(headers, metric, QUERY_CONTEXT),
    metric,
  }));
  return rows.flatMap((row) => {
    const date = String(row[dayIndex]);
    return metricColumns.map((column) => ({
      date,
      metric: column.metric,
      value: Number(row[column.index]),
    }));
  });
};

/**
 * channel-level の日次メトリクスを収集して LONG フォーマットで返す。
 *
 * 入力は `.strict()` schema で先に検証してから API を呼ぶため、不正入力（未知キー /
 * 非 YYYY-MM-DD）は API へ到達せず validation エラーになる。
 */
export const collectChannelAnalyticsService = createService(
  ChannelAnalyticsInput,
  ChannelAnalyticsOutput,
  async (request, deps: ChannelAnalyticsDeps) => {
    const params = buildQueryParams(request);
    const data = await withRetry(
      () => executeQuery(deps.youtubeAnalytics, params, QUERY_CONTEXT),
      { shouldRetry: shouldRetryAnalyticsQuery, sleep: deps.sleep }
    );
    return { metrics: reshapeToLongFormat(data) };
  }
);
