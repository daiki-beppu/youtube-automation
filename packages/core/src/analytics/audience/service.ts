import type { youtubeAnalytics_v2 } from "googleapis";

import {
  classifyGaxiosError,
  shouldRetryApiQuery,
} from "../../errors.ts";
import { withRetry } from "../../retry.ts";
import type { SleepMs } from "../../retry.ts";
import { createService } from "../../service-frame.ts";
import {
  readCoercedNumberCell,
  readStringCell,
  requireHeaders,
  resolveColumnIndex,
} from "../column-helpers.ts";
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

type QueryParams = youtubeAnalytics_v2.Params$Resource$Reports$Query;
type QueryResponse = youtubeAnalytics_v2.Schema$QueryResponse;
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

const queryAudienceReport = async (
  client: youtubeAnalytics_v2.Youtubeanalytics,
  params: QueryParams
): Promise<QueryResponse> => {
  try {
    const response = await client.reports.query(params);
    return response.data;
  } catch (error) {
    throw classifyGaxiosError(error, QUERY_CONTEXT);
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
  const headers = requireHeaders(data, QUERY_CONTEXT);
  const ageGroupIndex = resolveColumnIndex(headers, "ageGroup", QUERY_CONTEXT);
  const genderIndex = resolveColumnIndex(headers, "gender", QUERY_CONTEXT);
  const valueIndex = resolveColumnIndex(
    headers,
    VIEWER_PERCENTAGE_METRIC,
    QUERY_CONTEXT
  );
  const ageGroupTotals = new Map<string, number>();
  const genderTotals = new Map<string, number>();
  for (const row of data.rows) {
    const value = readCoercedNumberCell(
      row,
      valueIndex,
      VIEWER_PERCENTAGE_METRIC,
      QUERY_CONTEXT
    );
    addToTotals(
      ageGroupTotals,
      readStringCell(row, ageGroupIndex, "ageGroup", QUERY_CONTEXT),
      value
    );
    addToTotals(
      genderTotals,
      readStringCell(row, genderIndex, "gender", QUERY_CONTEXT),
      value
    );
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
  const headers = requireHeaders(data, QUERY_CONTEXT);
  const countryIndex = resolveColumnIndex(
    headers,
    COUNTRY_DIMENSION,
    QUERY_CONTEXT
  );
  const metricColumns = AUDIENCE_COUNTRY_METRICS.filter(
    (metric) => metric !== VIEW_SHARE_PERCENT_METRIC
  ).map((metric) => ({
    index: resolveColumnIndex(headers, metric, QUERY_CONTEXT),
    metric,
  }));
  const records = data.rows.flatMap((row) => {
    const country = readStringCell(
      row,
      countryIndex,
      COUNTRY_DIMENSION,
      QUERY_CONTEXT
    );
    return metricColumns.map(
      (column): CountryMetricRecord => ({
        country,
        metric: column.metric,
        segment: COUNTRY_DIMENSION,
        value: readCoercedNumberCell(
          row,
          column.index,
          column.metric,
          QUERY_CONTEXT
        ),
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
  const headers = requireHeaders(data, QUERY_CONTEXT);
  const statusIndex = resolveColumnIndex(
    headers,
    SUBSCRIBED_STATUS_DIMENSION,
    QUERY_CONTEXT
  );
  const metricColumns = AUDIENCE_SUBSCRIBED_STATUS_METRICS.filter(
    (metric) => metric !== VIEW_SHARE_PERCENT_METRIC
  ).map((metric) => ({
    index: resolveColumnIndex(headers, metric, QUERY_CONTEXT),
    metric,
  }));
  const records = data.rows.flatMap((row) => {
    const subscribedStatus = readStringCell(
      row,
      statusIndex,
      SUBSCRIBED_STATUS_DIMENSION,
      QUERY_CONTEXT
    );
    return metricColumns.map(
      (column): SubscribedStatusMetricRecord => ({
        metric: column.metric,
        segment: SUBSCRIBED_STATUS_DIMENSION,
        subscribedStatus,
        value: readCoercedNumberCell(
          row,
          column.index,
          column.metric,
          QUERY_CONTEXT
        ),
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
  const retryOpts = { shouldRetry: shouldRetryApiQuery, sleep };
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

export const collectAudienceService = createService(
  AudienceAnalyticsInput,
  AudienceAnalyticsOutput,
  async (request, deps: AudienceAnalyticsDeps) => {
    const [demographics, country, subscribedStatus] = await runAudienceQueries(
      deps.youtubeAnalytics,
      buildAudienceQueries(request),
      deps.sleep
    );
    return {
      metrics: [
        ...reshapeDemographics(demographics),
        ...reshapeCountry(country),
        ...reshapeSubscribedStatus(subscribedStatus),
      ],
    };
  }
);
