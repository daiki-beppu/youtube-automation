// 動画別 analytics サービス境界（ADR-0003 §1）。YouTube Analytics の `reports.query` を
// Result でラップし、行データを long/tidy melt（1 レコード = 1 (video, metric)）に整形する。
//
// Python `utils/video_analytics.py` の Mixin を翻訳せず TS で新規記述（ADR-0003 #820）。
// リトライ・バックオフは service が所有し、共通 `withRetry`（#959）に委譲する。quota（429）は
// ADR-0003 の retry 規約に従い retry せず、`domain: "quota"` + `retryAfterSeconds` の Result で
// caller へ返す。入力 / 出力検証と `ServiceError` 変換は `createService` が担う。
//
// seam contract（テストの fake と一致させる契約）:
//   deps.youtubeAnalytics.reports.query(params) -> { data: { columnHeaders?, rows? } }
//   429 時は gaxios 形状 { response: { status: 429, headers: { "retry-after" } } } で reject。

import type { YouTubeAnalyticsClient } from "../../oauth/client.ts";
import { withRetry } from "../../retry.ts";
import type { SleepMs } from "../../retry.ts";
import { createService } from "../../service.ts";
import { resolveColumnIndex } from "../columns.ts";
import { executeQuery, shouldRetryAnalyticsQuery } from "../query.ts";
import {
  CollectVideoAnalyticsInput,
  CollectVideoAnalyticsOutput,
  METRIC_COLUMNS,
  VIDEO_DIMENSION,
} from "./schema.ts";

/**
 * collectVideoAnalyticsService の注入依存。
 *
 * - `youtubeAnalytics`: 構築済み Analytics クライアント（DI seam）
 * - `sleep`: `withRetry` のバックオフ待機注入点（省略時は `withRetry` 内の実時間待機。
 *   テストは no-op を注入して 5xx/4xx → `domain:"api"` の retry パスを deterministic に検証する。
 *   image/service.ts:40 と同形の seam）
 */
export interface VideoAnalyticsDeps {
  youtubeAnalytics: YouTubeAnalyticsClient;
  sleep?: SleepMs;
}

const QUERY_CONTEXT = "youtubeAnalytics.reports.query";
interface ColumnHeader {
  readonly name?: string | null;
}

// channelId を必須の ids フィルタにエンコードし、videoId 指定時のみ video== フィルタを足す。
const buildQueryParams = (request: CollectVideoAnalyticsInput) => ({
  dimensions: VIDEO_DIMENSION,
  endDate: request.endDate,
  ids: `channel==${request.channelId}`,
  metrics: METRIC_COLUMNS.map((column) => column.apiName).join(","),
  startDate: request.startDate,
  ...(request.videoId === undefined
    ? {}
    : { filters: `video==${request.videoId}` }),
});

// 行を long/tidy melt（1 レコード = 1 (video, metric)）へ展開する。列は columnHeaders[].name
// で解決するため位置非依存。行が無い場合は空配列（API が rows を返さない = データなし）。
const meltVideoRows = (
  columnHeaders: readonly ColumnHeader[],
  rows: readonly (readonly unknown[])[]
) => {
  if (rows.length === 0) {
    return [];
  }

  const videoIndex = resolveColumnIndex(
    columnHeaders,
    VIDEO_DIMENSION,
    QUERY_CONTEXT
  );
  const metricPlan = METRIC_COLUMNS.map((column) => ({
    index: resolveColumnIndex(columnHeaders, column.apiName, QUERY_CONTEXT),
    metric: column.outName,
  }));

  return rows.flatMap((row) =>
    metricPlan.map((plan) => ({
      metric: plan.metric,
      value: row[plan.index] as number,
      videoId: row[videoIndex] as string,
    }))
  );
};

/**
 * チャンネル（任意で単一動画）の per-video metrics を一括取得し、Result で返す。
 *
 * 入力は `.strict()` schema で先に検証してから query を呼ぶため、不正入力は API に到達せず
 * validation エラーになる。`deps.youtubeAnalytics` は構築済みクライアントを注入する seam
 * （ADR-0003 §7）。
 */
export const collectVideoAnalyticsService = createService(
  CollectVideoAnalyticsInput,
  CollectVideoAnalyticsOutput,
  async (request, deps: VideoAnalyticsDeps) => {
    const params = buildQueryParams(request);
    const data = await withRetry(
      () => executeQuery(deps.youtubeAnalytics, params, QUERY_CONTEXT),
      {
        shouldRetry: shouldRetryAnalyticsQuery,
        sleep: deps.sleep,
      }
    );
    return {
      metrics: meltVideoRows(data.columnHeaders ?? [], data.rows ?? []),
    };
  }
);
