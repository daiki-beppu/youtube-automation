import type { youtubeAnalytics_v2 } from "googleapis";

import { withRetry } from "../../retry.ts";
import type { SleepMs } from "../../retry.ts";
import { createService } from "../../service.ts";
import {
  readNonEmptyStringCell,
  readNumberCell,
  requireHeaders,
  resolveColumnIndex,
} from "../columns.ts";
import { executeQuery, shouldRetryAnalyticsQuery } from "../query.ts";
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
    const trafficSourceType = readNonEmptyStringCell(
      row,
      trafficSourceIndex,
      TRAFFIC_SOURCE_DIMENSION,
      QUERY_CONTEXT
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
      const value = readNumberCell(
        row,
        column.index,
        column.metric,
        QUERY_CONTEXT
      );
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
  const headers = requireHeaders(data, QUERY_CONTEXT);
  const trafficSourceIndex = resolveColumnIndex(
    headers,
    TRAFFIC_SOURCE_DIMENSION,
    QUERY_CONTEXT
  );
  const metricColumns = TRAFFIC_SOURCE_API_METRICS.map((metric) => ({
    index: resolveColumnIndex(headers, metric, QUERY_CONTEXT),
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

export const collectTrafficSourceService = createService(
  TrafficSourceAnalyticsInput,
  TrafficSourceAnalyticsOutput,
  async (request, deps: TrafficSourceDeps) => {
    const params = buildQueryParams(request);
    const data = await withRetry(
      () => executeQuery(deps.youtubeAnalytics, params, QUERY_CONTEXT),
      { shouldRetry: shouldRetryAnalyticsQuery, sleep: deps.sleep }
    );
    return { metrics: reshapeToLongFormat(data) };
  }
);
