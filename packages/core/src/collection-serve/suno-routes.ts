import {
  COLLECTIONS_ROUTE,
  PROMPTS_ROUTE,
} from "../../../../extensions/shared/constants.ts";
import {
  buildCollectionsIndex,
  resolveCollectionPromptsPath,
  resolveSinglePromptsPath,
} from "./collections.ts";
import { fileResponse } from "./file-response.ts";
import { jsonResponse, notFoundResponse } from "./http.ts";
import { parseCapturedPlaylists, writeCapturedPlaylists } from "./playlists.ts";
import type { CollectionServeInput } from "./schema.ts";

export const handlePlaylistCapture = async (
  request: Request,
  input: CollectionServeInput
): Promise<Response> => {
  if (
    input.playlistCaptureRoot === undefined ||
    input.playlistCapturePrefix === undefined
  ) {
    return notFoundResponse(request, input);
  }
  const items = await parseCapturedPlaylists(request);
  if (items === null) {
    return jsonResponse(
      { error: "Bad Request" },
      400,
      request,
      input.allowOrigin
    );
  }
  return jsonResponse(
    writeCapturedPlaylists(
      input.playlistCaptureRoot,
      input.playlistCapturePrefix,
      items
    ),
    200,
    request,
    input.allowOrigin
  );
};

export const handleCollectionsIndex = async (
  request: Request,
  input: CollectionServeInput
): Promise<Response> => {
  const playlistCaptureIndex =
    input.playlistCaptureRoot === undefined ||
    input.playlistCapturePrefix === undefined
      ? undefined
      : {
          prefix: input.playlistCapturePrefix,
          root: input.playlistCaptureRoot,
        };
  return jsonResponse(
    await buildCollectionsIndex(input.path, playlistCaptureIndex),
    200,
    request,
    input.allowOrigin
  );
};

export const handleSinglePrompts = async (
  request: Request,
  input: CollectionServeInput
): Promise<Response> =>
  fileResponse(
    request,
    input,
    await resolveSinglePromptsPath(input.path),
    "application/json"
  );

export const handleCollectionPrompts = async (
  request: Request,
  input: CollectionServeInput
): Promise<Response | null> => {
  const url = new URL(request.url);
  if (!url.pathname.endsWith(PROMPTS_ROUTE)) {
    return null;
  }
  const routePrefix = `${COLLECTIONS_ROUTE}/`;
  const collectionId = url.pathname.slice(
    routePrefix.length,
    -PROMPTS_ROUTE.length
  );
  const resolved = await resolveCollectionPromptsPath(input.path, collectionId);
  if (resolved === null) {
    return notFoundResponse(request, input);
  }
  return fileResponse(request, input, resolved, "application/json");
};
