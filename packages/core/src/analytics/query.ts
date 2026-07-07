import type { youtubeAnalytics_v2 } from "googleapis";

import { classifyGaxiosError, YouTubeAPIError } from "../errors.ts";
import type { YouTubeAnalyticsClient } from "../oauth/client.ts";
import { defaultShouldRetry } from "../retry.ts";

const HTTP_SERVER_ERROR_MIN = 500;

export type QueryParams = youtubeAnalytics_v2.Params$Resource$Reports$Query;
export type QueryResponse = youtubeAnalytics_v2.Schema$QueryResponse;

export const executeQuery = async (
  client: YouTubeAnalyticsClient,
  params: QueryParams,
  context: string
): Promise<QueryResponse> => {
  try {
    const response = await client.reports.query(params);
    return response.data;
  } catch (error) {
    throw classifyGaxiosError(error, context);
  }
};

export const shouldRetryAnalyticsQuery = (error: unknown): boolean => {
  if (!defaultShouldRetry(error)) {
    return false;
  }
  if (!(error instanceof YouTubeAPIError)) {
    return false;
  }
  return (
    error.statusCode === undefined || error.statusCode >= HTTP_SERVER_ERROR_MIN
  );
};
