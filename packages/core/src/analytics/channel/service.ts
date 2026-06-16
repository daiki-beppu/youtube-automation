// channel-level 日次メトリクス収集の service 境界（ADR-0003 §1）。Python
// `utils/channel_analytics.py` の `get_channel_analytics` / `_process_daily_data` を
// 翻訳せず TS で新規記述したもの（ADR-0003）。
//
// 構築済みの YouTube Analytics クライアントを `deps` で受け取り（ADR-0003 §7 / DI
// seam）、`reports.query` の wide な行列を `{ date, metric, value }` の LONG レコードへ
// reshape して `Result` で返す。core 内部（query / reshape）は throw OK。境界の
// try/catch で `toServiceError` 経由に集約し、CLI/MCP は `if (!r.ok)` で discriminate
// する。マッピング:
//   - schema 違反（未知キー / 非 YYYY-MM-DD）→ err(domain "validation")（zod ZodError）
//   - 429 quota                              → err(domain "quota" + retryAfterSeconds)
//   - その他の API エラー（403 等）          → err(domain "api")
//   - 成功                                   → ok({ metrics })
//
// retry / backoff は本 service が所有せず共通 `withRetry`（#959）に委譲する。quota は
// retry せず Result で caller へ返し（ADR-0003）、4xx は恒久エラーとして retry しない。

import type { youtubeAnalytics_v2 } from "googleapis";

import { isRecord } from "../../../internal/guards.ts";
import {
  QuotaExhaustedError,
  toServiceError,
  YouTubeAPIError,
} from "../../errors.ts";
import type { ServiceError } from "../../errors.ts";
import { err, ok } from "../../result.ts";
import type { Result } from "../../result.ts";
import { defaultShouldRetry, withRetry } from "../../retry.ts";
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
const HTTP_SERVER_ERROR_MIN = 500;

type ChannelMetricRecord = ChannelAnalyticsOutput["metrics"][number];
type QueryParams = youtubeAnalytics_v2.Params$Resource$Reports$Query;
type QueryResponse = youtubeAnalytics_v2.Schema$QueryResponse;
type ColumnHeaders = NonNullable<QueryResponse["columnHeaders"]>;

// gaxios エラーの `response.headers["retry-after"]` を秒数として取り出す。header 不在
// （quota が日次リセットで Retry-After を返さないケース）では undefined（contract 通り）。
const parseRetryAfterSeconds = (error: unknown): number | undefined => {
  if (
    !(
      isRecord(error) &&
      isRecord(error.response) &&
      isRecord(error.response.headers)
    )
  ) {
    return undefined;
  }
  const seconds = Number(error.response.headers["retry-after"]);
  return Number.isFinite(seconds) ? seconds : undefined;
};

// gaxios 形状の API エラーを payload 付き throw 型へ変換する。429 のみ
// `QuotaExhaustedError` へ昇格し（`fromGaxiosError` は昇格しない契約のため caller 判断）、
// それ以外は `YouTubeAPIError` のまま返す。
const toQueryError = (error: unknown): YouTubeAPIError => {
  const apiError = YouTubeAPIError.fromGaxiosError(error, QUERY_CONTEXT);
  if (apiError.statusCode === 429) {
    return new QuotaExhaustedError(
      apiError.message,
      parseRetryAfterSeconds(error)
    );
  }
  return apiError;
};

// `queryDailyReport` が全エラーを `YouTubeAPIError`（429 は `QuotaExhaustedError`）へ
// 正規化してから throw するため、ここへ渡るのは常に `YouTubeAPIError`。
//   - quota(429): `defaultShouldRetry` が false（ADR-0003: quota は Result で caller へ）
//   - その他の 4xx 恒久エラー: retry しない
//   - 5xx / status 不明（ネットワーク断などが status なしで正規化される）: 一時障害として retry
//
// retry-許可分岐（5xx / status 不明 → true）の回帰を unit test で pin できるよう export
// する。`index.ts` は意図的に再エクスポートしない（ADR-0003 canonical template: feature の
// 公開面は schema + service のみ）ため公開 API は不変。
export const shouldRetryQuery = (error: unknown): boolean => {
  if (!defaultShouldRetry(error)) {
    return false;
  }
  if (!(error instanceof YouTubeAPIError)) {
    // 上記の正規化により到達しない。網羅性のための保守的 fallback（retry しない）。
    return false;
  }
  return (
    error.statusCode === undefined || error.statusCode >= HTTP_SERVER_ERROR_MIN
  );
};

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

// query を 1 回実行し、gaxios エラーを payload 付き throw 型へ翻訳して返す。withRetry の
// `shouldRetry` と境界の `toServiceError` の双方が statusCode で分類できるよう、生の
// gaxios エラーを内側で domain エラーへ変換してから rethrow する。
const queryDailyReport = async (
  client: youtubeAnalytics_v2.Youtubeanalytics,
  params: QueryParams
): Promise<QueryResponse> => {
  try {
    const response = await client.reports.query(params);
    return response.data;
  } catch (error) {
    throw toQueryError(error);
  }
};

// 列名で位置を引く（位置 index 決め打ちを避ける）。要求した列が欠けていれば値が
// 黙って NaN になる前に fail fast する。
const resolveColumnIndex = (headers: ColumnHeaders, name: string): number => {
  const index = headers.findIndex((header) => header.name === name);
  if (index === -1) {
    throw new Error(
      `${QUERY_CONTEXT}: response is missing the "${name}" column`
    );
  }
  return index;
};

const reshapeToLongFormat = (data: QueryResponse): ChannelMetricRecord[] => {
  // データ無しの期間は API が `rows` を省く（v2.d.ts contract）→ 空配列で ok。
  const { rows } = data;
  if (!rows) {
    return [];
  }
  const headers = data.columnHeaders;
  if (!headers) {
    throw new Error(`${QUERY_CONTEXT}: response has rows but no columnHeaders`);
  }
  const dayIndex = resolveColumnIndex(headers, DAY_DIMENSION);
  const metricColumns = CHANNEL_METRICS.map((metric) => ({
    index: resolveColumnIndex(headers, metric),
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
export const collectChannelAnalyticsService = async (
  input: ChannelAnalyticsInput,
  deps: { youtubeAnalytics: youtubeAnalytics_v2.Youtubeanalytics }
): Promise<Result<ChannelAnalyticsOutput, ServiceError>> => {
  try {
    const request = ChannelAnalyticsInput.parse(input);
    const params = buildQueryParams(request);
    const data = await withRetry(
      () => queryDailyReport(deps.youtubeAnalytics, params),
      { shouldRetry: shouldRetryQuery }
    );
    return ok(
      ChannelAnalyticsOutput.parse({ metrics: reshapeToLongFormat(data) })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
