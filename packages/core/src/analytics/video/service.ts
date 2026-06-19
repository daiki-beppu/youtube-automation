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

import { classifyGaxiosError, shouldRetryApiQuery } from "../../errors.ts";
import type { YouTubeAnalyticsClient } from "../../oauth/client.ts";
import { withRetry } from "../../retry.ts";
import type { SleepMs } from "../../retry.ts";
import { createService } from "../../service-frame.ts";
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

// classifyGaxiosError / QuotaExhaustedError の message に載せる操作名。
const QUERY_CONTEXT = "youtubeAnalytics.reports.query";

/** Analytics クエリで参照する最小の列ヘッダ形状。 */
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

// reports.query を 1 回実行し、失敗を domain エラーへ分類して投げ直す（withRetry に渡す
// 1-attempt 単位）。分類だけを担い、retry 可否は withRetry / defaultShouldRetry に委ねる。
const runVideoQuery = async (
  deps: VideoAnalyticsDeps,
  request: CollectVideoAnalyticsInput
) => {
  try {
    return await deps.youtubeAnalytics.reports.query(buildQueryParams(request));
  } catch (error) {
    throw classifyGaxiosError(error, QUERY_CONTEXT);
  }
};

// 行を long/tidy melt（1 レコード = 1 (video, metric)）へ展開する。列は columnHeaders[].name
// で解決するため位置非依存。行が無い場合は空配列（API が rows を返さない = データなし）。
const meltVideoRows = (
  columnHeaders: readonly ColumnHeader[],
  rows: readonly (readonly unknown[])[]
) => {
  if (rows.length === 0) {
    return [];
  }

  const indexByName = new Map<string, number>();
  for (const [index, header] of columnHeaders.entries()) {
    if (typeof header.name === "string") {
      indexByName.set(header.name, index);
    }
  }

  const columnIndex = (name: string): number => {
    const index = indexByName.get(name);
    if (index === undefined) {
      throw new Error(
        `${QUERY_CONTEXT}: response is missing the "${name}" column`
      );
    }
    return index;
  };

  const videoIndex = columnIndex(VIDEO_DIMENSION);
  const metricPlan = METRIC_COLUMNS.map((column) => ({
    index: columnIndex(column.apiName),
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
    const response = await withRetry(() => runVideoQuery(deps, request), {
      shouldRetry: shouldRetryApiQuery,
      sleep: deps.sleep,
    });
    const metrics = meltVideoRows(
      response.data.columnHeaders ?? [],
      response.data.rows ?? []
    );
    return { metrics };
  }
);
