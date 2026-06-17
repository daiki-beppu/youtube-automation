import {
  COLLECTIONS_ROUTE,
  DISTROKID_ASSETS_PREFIX,
  DISTROKID_COLLECTIONS_ROUTE,
  DISTROKID_RELEASES_ROUTE,
  PLAYLISTS_CAPTURE_ROUTE,
  PROMPTS_ROUTE,
  VERSION_ROUTE,
} from "../../../../extensions/shared/constants.ts";
import type { ChannelConfig } from "../config/index.ts";
import {
  handleDistrokidCollectionGet,
  handleDistrokidCollectionsIndex,
  handleDistrokidReleaseRecord,
  handleSingleDistrokidAsset,
  handleSingleDistrokidRelease,
  isSingleDistrokidReleaseRoute,
} from "./distrokid-routes.ts";
import {
  allowedOrigin,
  forbiddenPostResponse,
  jsonResponse,
  notFoundResponse,
  preflightHeaders,
} from "./http.ts";
import type { FetchHandler } from "./http.ts";
import type { CollectionServeInput } from "./schema.ts";
import {
  handleCollectionPrompts,
  handleCollectionsIndex,
  handlePlaylistCapture,
  handleSinglePrompts,
} from "./suno-routes.ts";
import { readPackageVersion } from "./version.ts";

type CollectionServeMode = "dir" | "single";
const MIN_EXTENSION_VERSION = "0.1.0";

const handleCollectionGet = async (
  request: Request,
  input: CollectionServeInput,
  config: ChannelConfig
): Promise<Response> =>
  (await handleCollectionPrompts(request, input)) ??
  handleDistrokidCollectionGet(request, input, config);

const handleVersion = async (
  request: Request,
  input: CollectionServeInput
): Promise<Response> => {
  const version = await readPackageVersion();
  return jsonResponse(
    { min_extension_version: MIN_EXTENSION_VERSION, version },
    200,
    request,
    input.allowOrigin
  );
};

const handleDirGet = (
  request: Request,
  input: CollectionServeInput,
  config: ChannelConfig
): Promise<Response> | Response => {
  const { pathname } = new URL(request.url);
  if (pathname === COLLECTIONS_ROUTE) {
    return handleCollectionsIndex(request, input);
  }
  if (pathname.startsWith(`${COLLECTIONS_ROUTE}/`)) {
    return handleCollectionGet(request, input, config);
  }
  if (
    pathname === DISTROKID_COLLECTIONS_ROUTE &&
    config.integrations.distrokid.enabled
  ) {
    return handleDistrokidCollectionsIndex(request, input);
  }
  return notFoundResponse(request, input);
};

const handleSingleGet = (
  request: Request,
  input: CollectionServeInput,
  config: ChannelConfig
): Promise<Response> | Response => {
  const { pathname } = new URL(request.url);
  if (pathname === PROMPTS_ROUTE) {
    return handleSinglePrompts(request, input);
  }
  if (!config.integrations.distrokid.enabled) {
    return notFoundResponse(request, input);
  }
  if (isSingleDistrokidReleaseRoute(pathname)) {
    return handleSingleDistrokidRelease(request, input, config);
  }
  if (pathname.startsWith(DISTROKID_ASSETS_PREFIX)) {
    return handleSingleDistrokidAsset(request, input);
  }
  return notFoundResponse(request, input);
};

const handleGet = (
  request: Request,
  input: CollectionServeInput,
  config: ChannelConfig,
  mode: CollectionServeMode
): Promise<Response> | Response => {
  const { pathname } = new URL(request.url);
  if (pathname === VERSION_ROUTE) {
    return handleVersion(request, input);
  }
  return mode === "dir"
    ? handleDirGet(request, input, config)
    : handleSingleGet(request, input, config);
};

const handlePost = (
  request: Request,
  input: CollectionServeInput,
  config: ChannelConfig
): Promise<Response> | Response => {
  const { pathname } = new URL(request.url);
  if (allowedOrigin(request, input.allowOrigin) === undefined) {
    return forbiddenPostResponse(request, input);
  }
  if (pathname === PLAYLISTS_CAPTURE_ROUTE) {
    return handlePlaylistCapture(request, input);
  }
  if (pathname === DISTROKID_RELEASES_ROUTE) {
    return handleDistrokidReleaseRecord(
      request,
      input,
      config.integrations.distrokid.enabled
    );
  }
  return notFoundResponse(request, input);
};

export const createCollectionServeFetchHandler =
  (
    input: CollectionServeInput,
    config: ChannelConfig,
    mode: CollectionServeMode
  ): FetchHandler =>
  (request) => {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: preflightHeaders(request, input.allowOrigin),
        status: 204,
      });
    }
    if (request.method === "POST") {
      return handlePost(request, input, config);
    }
    return request.method === "GET"
      ? handleGet(request, input, config, mode)
      : notFoundResponse(request, input);
  };
