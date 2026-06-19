import type { youtubeAnalytics_v2 } from "googleapis";

import { toServiceError } from "../../errors.ts";
import type { ServiceError } from "../../errors.ts";
import { err, ok } from "../../result.ts";
import type { Result } from "../../result.ts";
import { withRetry } from "../../retry.ts";
import type { SleepMs } from "../../retry.ts";
import {
  shouldRetryAnalyticsQuery,
  toAnalyticsQueryError,
} from "../query-error.ts";
import {
  TRAFFIC_SOURCE_API_METRICS,
  TRAFFIC_SOURCE_VIEWS_METRIC,
  TrafficSourceAnalyticsInput,
  TrafficSourceAnalyticsOutput,
} from "./schema.ts";

const QUERY_CONTEXT = "traffic-source analytics query";
const CHANNEL_ID_PREFIX = "channel==";
const VIDEO_FILTER_PREFIX = "video==";
const TRAFFIC_SOURCE_DIMENSION = "insightTrafficSourceType";
const SORT_BY_VIEWS_DESC = "-views";
const VIEW_SHARE_METRIC = "viewSharePercent";

type QueryParams = youtubeAnalytics_v2.Params$Resource$Reports$Query;
type QueryResponse = youtubeAnalytics_v2.Schema$QueryResponse;
type ColumnHeaders = NonNullable<QueryResponse["columnHeaders"]>;
type TrafficSourceMetricRecord =
  TrafficSourceAnalyticsOutput["metrics"][number];
interface MetricColumn {
  readonly index: number;
  readonly metric: (typeof TRAFFIC_SOURCE_API_METRICS)[number];
}
interface AggregatedTrafficSource {
  readonly averageViewDurationWeightedSum: number;
  readonly estimatedMinutesWatched: number;
  readonly trafficSourceType: string;
  readonly views: number;
}
interface TrafficSourceDeps {
  readonly sleep?: SleepMs;
  readonly youtubeAnalytics: youtubeAnalytics_v2.Youtubeanalytics;
}

const buildQueryParams = (input: TrafficSourceAnalyticsInput): QueryParams => ({
  dimensions: TRAFFIC_SOURCE_DIMENSION,
  endDate: input.endDate,
  ...(input.videoId
    ? { filters: `${VIDEO_FILTER_PREFIX}${input.videoId}` }
    : {}),
  ids: `${CHANNEL_ID_PREFIX}${input.channelId}`,
  metrics: TRAFFIC_SOURCE_API_METRICS.join(","),
  sort: SORT_BY_VIEWS_DESC,
  startDate: input.startDate,
});

const queryTrafficSourceReport = async (
  client: youtubeAnalytics_v2.Youtubeanalytics,
  params: QueryParams
): Promise<QueryResponse> => {
  try {
    const response = await client.reports.query(params);
    return response.data;
  } catch (error) {
    throw toAnalyticsQueryError(error, QUERY_CONTEXT);
  }
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

const readNumberCell = (
  row: readonly unknown[],
  index: number,
  columnName: string
): number => {
  const value = row[index];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(
      `${QUERY_CONTEXT}: response has a non-numeric "${columnName}" value`
    );
  }
  return value;
};

const readStringCell = (
  row: readonly unknown[],
  index: number,
  columnName: string
): string => {
  const value = row[index];
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(
      `${QUERY_CONTEXT}: response has an invalid "${columnName}" value`
    );
  }
  return value;
};

const roundOneDecimal = (value: number): number => Math.round(value * 10) / 10;

const metricRecordsForRow = (
  source: AggregatedTrafficSource,
  totalViews: number
): TrafficSourceMetricRecord[] => {
  const averageViewDuration =
    source.views === 0
      ? 0
      : roundOneDecimal(source.averageViewDurationWeightedSum / source.views);
  const viewSharePercent =
    totalViews === 0 ? 0 : roundOneDecimal((source.views / totalViews) * 100);
  return [
    {
      metric: TRAFFIC_SOURCE_VIEWS_METRIC,
      trafficSourceType: source.trafficSourceType,
      value: source.views,
    },
    {
      metric: "estimatedMinutesWatched",
      trafficSourceType: source.trafficSourceType,
      value: source.estimatedMinutesWatched,
    },
    {
      metric: "averageViewDuration",
      trafficSourceType: source.trafficSourceType,
      value: averageViewDuration,
    },
    {
      metric: VIEW_SHARE_METRIC,
      trafficSourceType: source.trafficSourceType,
      value: viewSharePercent,
    },
  ];
};

const aggregateTrafficSources = (
  rows: readonly (readonly unknown[])[],
  trafficSourceIndex: number,
  metricColumns: readonly MetricColumn[]
): AggregatedTrafficSource[] => {
  const aggregated = new Map<string, AggregatedTrafficSource>();
  for (const row of rows) {
    const trafficSourceType = readStringCell(
      row,
      trafficSourceIndex,
      TRAFFIC_SOURCE_DIMENSION
    );
    const previous = aggregated.get(trafficSourceType) ?? {
      averageViewDurationWeightedSum: 0,
      estimatedMinutesWatched: 0,
      trafficSourceType,
      views: 0,
    };
    const {
      averageViewDurationWeightedSum: previousAverageViewDurationWeightedSum,
      estimatedMinutesWatched: previousEstimatedMinutesWatched,
      views: previousViews,
    } = previous;
    let averageViewDurationWeightedSum = previousAverageViewDurationWeightedSum;
    let views = previousViews;
    let estimatedMinutesWatched = previousEstimatedMinutesWatched;
    let rowViews = 0;
    let rowAverageViewDuration = 0;
    for (const column of metricColumns) {
      const value = readNumberCell(row, column.index, column.metric);
      if (column.metric === TRAFFIC_SOURCE_VIEWS_METRIC) {
        rowViews = value;
        views += value;
      } else if (column.metric === "estimatedMinutesWatched") {
        estimatedMinutesWatched += value;
      } else if (column.metric === "averageViewDuration") {
        rowAverageViewDuration = value;
      }
    }
    averageViewDurationWeightedSum += rowAverageViewDuration * rowViews;
    aggregated.set(trafficSourceType, {
      averageViewDurationWeightedSum,
      estimatedMinutesWatched,
      trafficSourceType,
      views,
    });
  }
  return [...aggregated.values()];
};

const reshapeToLongFormat = (
  data: QueryResponse
): TrafficSourceMetricRecord[] => {
  const { rows } = data;
  if (!rows) {
    return [];
  }
  const headers = data.columnHeaders;
  if (!headers) {
    throw new Error(`${QUERY_CONTEXT}: response has rows but no columnHeaders`);
  }
  const trafficSourceIndex = resolveColumnIndex(
    headers,
    TRAFFIC_SOURCE_DIMENSION
  );
  const metricColumns = TRAFFIC_SOURCE_API_METRICS.map((metric) => ({
    index: resolveColumnIndex(headers, metric),
    metric,
  }));
  const aggregated = aggregateTrafficSources(
    rows,
    trafficSourceIndex,
    metricColumns
  );
  let totalViews = 0;
  for (const source of aggregated) {
    totalViews += source.views;
  }
  return aggregated.flatMap((source) =>
    metricRecordsForRow(source, totalViews)
  );
};

export const collectTrafficSourceService = async (
  input: TrafficSourceAnalyticsInput,
  deps: TrafficSourceDeps
): Promise<Result<TrafficSourceAnalyticsOutput, ServiceError>> => {
  try {
    const request = TrafficSourceAnalyticsInput.parse(input);
    const params = buildQueryParams(request);
    const data = await withRetry(
      () => queryTrafficSourceReport(deps.youtubeAnalytics, params),
      { shouldRetry: shouldRetryAnalyticsQuery, sleep: deps.sleep }
    );
    return ok(
      TrafficSourceAnalyticsOutput.parse({
        metrics: reshapeToLongFormat(data),
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
