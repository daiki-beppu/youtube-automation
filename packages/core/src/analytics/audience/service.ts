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
import type { SleepMs } from "../../retry.ts";
import {
  AUDIENCE_COUNTRY_METRICS,
  AUDIENCE_DEMOGRAPHIC_METRICS,
  AUDIENCE_SUBSCRIBED_STATUS_METRICS,
  AudienceAnalyticsInput,
  AudienceAnalyticsOutput,
} from "./schema.ts";

const QUERY_CONTEXT = "audience analytics query";
const CHANNEL_ID_PREFIX = "channel==";
const VIDEO_FILTER_PREFIX = "video==";
const AGE_GENDER_DIMENSIONS = "ageGroup,gender";
const COUNTRY_DIMENSION = "country";
const SUBSCRIBED_STATUS_DIMENSION = "subscribedStatus";
const VIEWER_PERCENTAGE_METRIC = "viewerPercentage";
const VIEWS_METRIC = "views";
const VIEW_SHARE_PERCENT_METRIC = "viewSharePercent";
const HTTP_SERVER_ERROR_MIN = 500;

type QueryParams = youtubeAnalytics_v2.Params$Resource$Reports$Query;
type QueryResponse = youtubeAnalytics_v2.Schema$QueryResponse;
type ColumnHeaders = NonNullable<QueryResponse["columnHeaders"]>;
type AudienceQueryParams = readonly [QueryParams, QueryParams, QueryParams];
interface AudienceAnalyticsDeps {
  readonly sleep?: SleepMs;
  readonly youtubeAnalytics: youtubeAnalytics_v2.Youtubeanalytics;
}
type DemographicMetricRecord =
  | {
      readonly ageGroup: string;
      readonly metric: typeof VIEWER_PERCENTAGE_METRIC;
      readonly segment: "ageGroup";
      readonly value: number;
    }
  | {
      readonly gender: string;
      readonly metric: typeof VIEWER_PERCENTAGE_METRIC;
      readonly segment: "gender";
      readonly value: number;
    };
interface CountryMetricRecord {
  readonly country: string;
  readonly metric: (typeof AUDIENCE_COUNTRY_METRICS)[number];
  readonly segment: typeof COUNTRY_DIMENSION;
  readonly value: number;
}
interface SubscribedStatusMetricRecord {
  readonly metric: (typeof AUDIENCE_SUBSCRIBED_STATUS_METRICS)[number];
  readonly segment: typeof SUBSCRIBED_STATUS_DIMENSION;
  readonly subscribedStatus: string;
  readonly value: number;
}
type AudienceMetricRecord =
  | DemographicMetricRecord
  | CountryMetricRecord
  | SubscribedStatusMetricRecord;

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
  const raw = error.response.headers["retry-after"];
  if (typeof raw !== "string" || raw.trim() === "") {
    return undefined;
  }
  if (!/^\d+$/u.test(raw)) {
    return undefined;
  }
  const seconds = Number(raw);
  return Number.isFinite(seconds) ? seconds : undefined;
};

const toQueryError = (error: unknown): YouTubeAPIError => {
  if (error instanceof YouTubeAPIError) {
    return error;
  }
  const apiError = YouTubeAPIError.fromGaxiosError(error, QUERY_CONTEXT);
  if (apiError.statusCode === 429) {
    return new QuotaExhaustedError(
      apiError.message,
      parseRetryAfterSeconds(error)
    );
  }
  return apiError;
};

const shouldRetryQuery = (error: unknown): boolean => {
  if (!defaultShouldRetry(error)) {
    return false;
  }
  if (error instanceof YouTubeAPIError) {
    return (
      error.statusCode === undefined ||
      error.statusCode >= HTTP_SERVER_ERROR_MIN
    );
  }
  return true;
};

const queryAudienceReport = async (
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

const baseQueryParams = (input: AudienceAnalyticsInput): QueryParams => ({
  endDate: input.endDate,
  ...(input.videoId
    ? { filters: `${VIDEO_FILTER_PREFIX}${input.videoId}` }
    : {}),
  ids: `${CHANNEL_ID_PREFIX}${input.channelId}`,
  startDate: input.startDate,
});

const buildAudienceQueries = (
  input: AudienceAnalyticsInput
): AudienceQueryParams => {
  const base = baseQueryParams(input);
  return [
    {
      ...base,
      dimensions: AGE_GENDER_DIMENSIONS,
      metrics: AUDIENCE_DEMOGRAPHIC_METRICS.join(","),
    },
    {
      ...base,
      dimensions: COUNTRY_DIMENSION,
      metrics: AUDIENCE_COUNTRY_METRICS.filter(
        (metric) => metric !== VIEW_SHARE_PERCENT_METRIC
      ).join(","),
      sort: "-views",
    },
    {
      ...base,
      dimensions: SUBSCRIBED_STATUS_DIMENSION,
      metrics: AUDIENCE_SUBSCRIBED_STATUS_METRICS.filter(
        (metric) => metric !== VIEW_SHARE_PERCENT_METRIC
      ).join(","),
      sort: "-views",
    },
  ];
};

const resolveColumnIndex = (headers: ColumnHeaders, name: string): number => {
  const index = headers.findIndex((header) => header.name === name);
  if (index === -1) {
    throw new Error(
      `${QUERY_CONTEXT}: response is missing the "${name}" column`
    );
  }
  return index;
};

const requireHeadersForRows = (data: QueryResponse): ColumnHeaders => {
  if (!data.columnHeaders) {
    throw new Error(`${QUERY_CONTEXT}: response has rows but no columnHeaders`);
  }
  return data.columnHeaders;
};

const readStringCell = (row: readonly unknown[], index: number): string => {
  const value = row[index];
  if (typeof value !== "string") {
    throw new TypeError(`${QUERY_CONTEXT}: response cell is not a string`);
  }
  return value;
};

const readNumberCell = (row: readonly unknown[], index: number): number => {
  const value = Number(row[index]);
  if (!Number.isFinite(value)) {
    throw new TypeError(
      `${QUERY_CONTEXT}: response cell is not a finite number`
    );
  }
  return value;
};

const addToTotals = (
  totals: Map<string, number>,
  key: string,
  value: number
) => {
  const current = totals.get(key);
  totals.set(key, (current === undefined ? 0 : current) + value);
};

const toTotalRecords = (
  totals: ReadonlyMap<string, number>,
  segment: "ageGroup" | "gender"
): AudienceMetricRecord[] =>
  [...totals.entries()].map(([key, value]) =>
    segment === "ageGroup"
      ? {
          ageGroup: key,
          metric: VIEWER_PERCENTAGE_METRIC,
          segment,
          value,
        }
      : {
          gender: key,
          metric: VIEWER_PERCENTAGE_METRIC,
          segment,
          value,
        }
  );

const reshapeDemographics = (data: QueryResponse): AudienceMetricRecord[] => {
  if (!data.rows) {
    return [];
  }
  const headers = requireHeadersForRows(data);
  const ageGroupIndex = resolveColumnIndex(headers, "ageGroup");
  const genderIndex = resolveColumnIndex(headers, "gender");
  const valueIndex = resolveColumnIndex(headers, VIEWER_PERCENTAGE_METRIC);
  const ageGroupTotals = new Map<string, number>();
  const genderTotals = new Map<string, number>();
  for (const row of data.rows) {
    const value = readNumberCell(row, valueIndex);
    addToTotals(ageGroupTotals, readStringCell(row, ageGroupIndex), value);
    addToTotals(genderTotals, readStringCell(row, genderIndex), value);
  }
  return [
    ...toTotalRecords(ageGroupTotals, "ageGroup"),
    ...toTotalRecords(genderTotals, "gender"),
  ];
};

const totalViews = (records: readonly AudienceMetricRecord[]): number =>
  records
    .filter((record) => record.metric === VIEWS_METRIC)
    .reduce((total, record) => total + record.value, 0);

const viewSharePercent = (views: number, total: number): number => {
  if (total === 0) {
    return 0;
  }
  return Math.round((views / total) * 1000) / 10;
};

const reshapeCountry = (data: QueryResponse): AudienceMetricRecord[] => {
  if (!data.rows) {
    return [];
  }
  const headers = requireHeadersForRows(data);
  const countryIndex = resolveColumnIndex(headers, COUNTRY_DIMENSION);
  const metricColumns = AUDIENCE_COUNTRY_METRICS.filter(
    (metric) => metric !== VIEW_SHARE_PERCENT_METRIC
  ).map((metric) => ({ index: resolveColumnIndex(headers, metric), metric }));
  const records = data.rows.flatMap((row) => {
    const country = readStringCell(row, countryIndex);
    return metricColumns.map(
      (column): CountryMetricRecord => ({
        country,
        metric: column.metric,
        segment: COUNTRY_DIMENSION,
        value: readNumberCell(row, column.index),
      })
    );
  });
  const viewsTotal = totalViews(records);
  return [
    ...records,
    ...records
      .filter((record) => record.metric === VIEWS_METRIC)
      .map(
        (record): CountryMetricRecord => ({
          country: record.country,
          metric: VIEW_SHARE_PERCENT_METRIC,
          segment: COUNTRY_DIMENSION,
          value: viewSharePercent(record.value, viewsTotal),
        })
      ),
  ];
};

const reshapeSubscribedStatus = (
  data: QueryResponse
): AudienceMetricRecord[] => {
  if (!data.rows) {
    return [];
  }
  const headers = requireHeadersForRows(data);
  const statusIndex = resolveColumnIndex(headers, SUBSCRIBED_STATUS_DIMENSION);
  const metricColumns = AUDIENCE_SUBSCRIBED_STATUS_METRICS.filter(
    (metric) => metric !== VIEW_SHARE_PERCENT_METRIC
  ).map((metric) => ({ index: resolveColumnIndex(headers, metric), metric }));
  const records = data.rows.flatMap((row) => {
    const subscribedStatus = readStringCell(row, statusIndex);
    return metricColumns.map(
      (column): SubscribedStatusMetricRecord => ({
        metric: column.metric,
        segment: SUBSCRIBED_STATUS_DIMENSION,
        subscribedStatus,
        value: readNumberCell(row, column.index),
      })
    );
  });
  const viewsTotal = totalViews(records);
  return [
    ...records,
    ...records
      .filter((record) => record.metric === VIEWS_METRIC)
      .map(
        (record): SubscribedStatusMetricRecord => ({
          metric: VIEW_SHARE_PERCENT_METRIC,
          segment: SUBSCRIBED_STATUS_DIMENSION,
          subscribedStatus: record.subscribedStatus,
          value: viewSharePercent(record.value, viewsTotal),
        })
      ),
  ];
};

const unwrapSettledQuery = (
  result: PromiseSettledResult<QueryResponse>
): QueryResponse => {
  if (result.status === "rejected") {
    throw result.reason;
  }
  return result.value;
};

const runAudienceQueries = async (
  client: youtubeAnalytics_v2.Youtubeanalytics,
  paramsList: AudienceQueryParams,
  sleep: SleepMs | undefined
): Promise<readonly [QueryResponse, QueryResponse, QueryResponse]> => {
  const retryOpts = { shouldRetry: shouldRetryQuery, sleep };
  const [demographics, country, subscribedStatus] = await Promise.allSettled([
    withRetry(() => queryAudienceReport(client, paramsList[0]), retryOpts),
    withRetry(() => queryAudienceReport(client, paramsList[1]), retryOpts),
    withRetry(() => queryAudienceReport(client, paramsList[2]), retryOpts),
  ]);
  return [
    unwrapSettledQuery(demographics),
    unwrapSettledQuery(country),
    unwrapSettledQuery(subscribedStatus),
  ];
};

export const collectAudienceService = async (
  input: AudienceAnalyticsInput,
  deps: AudienceAnalyticsDeps
): Promise<Result<AudienceAnalyticsOutput, ServiceError>> => {
  try {
    const request = AudienceAnalyticsInput.parse(input);
    const [demographics, country, subscribedStatus] = await runAudienceQueries(
      deps.youtubeAnalytics,
      buildAudienceQueries(request),
      deps.sleep
    );
    return ok(
      AudienceAnalyticsOutput.parse({
        metrics: [
          ...reshapeDemographics(demographics),
          ...reshapeCountry(country),
          ...reshapeSubscribedStatus(subscribedStatus),
        ],
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
