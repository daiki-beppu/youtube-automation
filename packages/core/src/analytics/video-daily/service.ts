// video×day 日次メトリクス収集の service 境界（ADR-0003 §1）。launch curve /
// channel trend の基礎データを供給する。Python `utils/video_daily_analytics.py` の
// `VideoDailyAnalyticsMixin` を翻訳せず TS で新規記述したもの（ADR-0003）。
//
// 構築済みの YouTube Analytics クライアントを `deps` で受け取り（ADR-0003 §7 / DI
// seam）、`reports.query` の行列（[video, day, views]）を `{ date, videoId, views }`
// レコードへ map して `Result` で返す。core 内部（query / map）は throw OK。境界の
// try/catch で `toServiceError` 経由に集約し、CLI/MCP は `if (!r.ok)` で discriminate
// する。マッピング:
//   - schema 違反（未知キー / 非 YYYY-MM-DD）→ err(domain "validation")（zod ZodError）
//   - 429 quota                              → err(domain "quota" + retryAfterSeconds)
//   - その他の API エラー（403 等）          → err(domain "api")
//   - 成功                                   → ok({ metrics })
//
// retry / backoff は本 service が所有せず共通 `withRetry`（#959）に委譲する。quota は
// retry せず Result で caller へ返し（ADR-0003）、4xx は恒久エラーとして retry しない。
// 一時障害（5xx / ネットワーク断）のみ既定バックオフで再試行する。`sleep` 注入点は
// テストが実時間待機を回避するための DI seam（省略時は withRetry の実時間 sleep）。

import type { youtubeAnalytics_v2 } from "googleapis";

import { toServiceError } from "../../errors.ts";
import type { ServiceError } from "../../errors.ts";
import type { YouTubeAnalyticsClient } from "../../oauth/client.ts";
import { err, ok } from "../../result.ts";
import type { Result } from "../../result.ts";
import { withRetry } from "../../retry.ts";
import type { SleepMs } from "../../retry.ts";
import {
  shouldRetryAnalyticsQuery,
  toAnalyticsQueryError,
} from "../query-error.ts";
import {
  CollectVideoDailyAnalyticsInput,
  CollectVideoDailyAnalyticsOutput,
} from "./schema.ts";

// API 問い合わせの契約文字列（YouTube Analytics v2 の語彙、単一定義）。
const QUERY_CONTEXT = "video-daily analytics query";
const VIDEO_DAY_DIMENSIONS = "video,day";
const VIEWS_METRIC = "views";
const SORT_BY_DAY = "day";
const CHANNEL_ID_PREFIX = "channel==";
const VIDEO_FILTER_PREFIX = "video==";
const VIDEO_FILTER_SEPARATOR = ",";

// 行の列順は上の `dimensions=video,day` + `metrics=views` クエリ契約で固定されるため、
// columnHeaders に頼らず位置で引く（API はこの dimension/metric 組では常にこの順で返す）。
const VIDEO_COLUMN = 0;
const DAY_COLUMN = 1;
const VIEWS_COLUMN = 2;

type QueryParams = youtubeAnalytics_v2.Params$Resource$Reports$Query;
type QueryResponse = youtubeAnalytics_v2.Schema$QueryResponse;
type VideoDailyRecord = CollectVideoDailyAnalyticsOutput["metrics"][number];

const buildQueryParams = (
  input: CollectVideoDailyAnalyticsInput
): QueryParams => {
  const baseParams: QueryParams = {
    dimensions: VIDEO_DAY_DIMENSIONS,
    endDate: input.endDate,
    ids: `${CHANNEL_ID_PREFIX}${input.channelId}`,
    metrics: VIEWS_METRIC,
    sort: SORT_BY_DAY,
    startDate: input.startDate,
  };
  // 空配列は「絞り込みなし」と解釈する（`video==` で ids が空の filter は不正なため送らない）。
  if (input.videoIds && input.videoIds.length > 0) {
    return {
      ...baseParams,
      filters: `${VIDEO_FILTER_PREFIX}${input.videoIds.join(VIDEO_FILTER_SEPARATOR)}`,
    };
  }
  return baseParams;
};

const mapRows = (rows: QueryResponse["rows"]): VideoDailyRecord[] => {
  // データ無しの期間は API が `rows` を省く（v2.d.ts contract）→ 空配列で ok。
  if (!rows) {
    return [];
  }
  return rows.map((row) => ({
    date: String(row[DAY_COLUMN]),
    videoId: String(row[VIDEO_COLUMN]),
    // この dimension では views セルが欠落し得る（0 視聴の日）。null/undefined は
    // 0 視聴として正規化する（NaN を生まない）。
    views: Number(row[VIEWS_COLUMN] ?? 0),
  }));
};

/**
 * video×day の日次 views を収集してレコード配列で返す。
 *
 * 入力は `.strict()` schema で先に検証してから API を呼ぶため、不正入力（未知キー /
 * 非 YYYY-MM-DD）は API へ到達せず validation エラーになる。
 */
export const collectVideoDailyAnalyticsService = async (
  input: CollectVideoDailyAnalyticsInput,
  deps: { sleep?: SleepMs; ytAnalytics: YouTubeAnalyticsClient }
): Promise<Result<CollectVideoDailyAnalyticsOutput, ServiceError>> => {
  try {
    const request = CollectVideoDailyAnalyticsInput.parse(input);
    const params = buildQueryParams(request);
    const data = await withRetry(
      async () => {
        try {
          const response = await deps.ytAnalytics.reports.query(params);
          return response.data;
        } catch (error) {
          throw toAnalyticsQueryError(error, QUERY_CONTEXT);
        }
      },
      { shouldRetry: shouldRetryAnalyticsQuery, sleep: deps.sleep }
    );
    return ok(
      CollectVideoDailyAnalyticsOutput.parse({
        metrics: mapRows(data.rows),
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
