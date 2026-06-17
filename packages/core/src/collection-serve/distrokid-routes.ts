import {
  COLLECTIONS_ROUTE,
  DISTROKID_ASSETS_PREFIX,
  DISTROKID_RELEASE_ROUTE,
} from "../../../../extensions/shared/constants.ts";
import type { ChannelConfig } from "../config/index.ts";
import { resolveKnownCollectionDir } from "./collections.ts";
import {
  buildDistrokidCollectionsIndex,
  buildDistrokidReleasePayload,
  findDistrokidDiscs,
  readReleasedDiscs,
  resolveDistrokidAssetPath,
  writeDistrokidRelease,
} from "./distrokid.ts";
import { fileResponse } from "./file-response.ts";
import { jsonResponse, notFoundResponse } from "./http.ts";
import type { CollectionServeInput } from "./schema.ts";

const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

const internalErrorResponse = (
  error: unknown,
  request: Request,
  input: CollectionServeInput
): Response =>
  jsonResponse({ error: errorMessage(error) }, 500, request, input.allowOrigin);

const parseDistrokidReleaseRecord = async (
  request: Request
): Promise<
  | { albumTitle: string; collectionId: string; disc: string; ok: true }
  | { ok: false }
> => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return { ok: false };
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false };
  }
  const record = body as Record<string, unknown>;
  if (
    typeof record.collection_id !== "string" ||
    typeof record.disc !== "string" ||
    typeof record.album_title !== "string" ||
    record.collection_id.length === 0 ||
    record.disc.length === 0 ||
    record.album_title.length === 0
  ) {
    return { ok: false };
  }
  return {
    albumTitle: record.album_title,
    collectionId: record.collection_id,
    disc: record.disc,
    ok: true,
  };
};

export const handleDistrokidReleaseRecord = async (
  request: Request,
  input: CollectionServeInput,
  distrokidEnabled: boolean
): Promise<Response> => {
  if (!distrokidEnabled || input.distrokidStateRoot === undefined) {
    return notFoundResponse(request, input);
  }
  const record = await parseDistrokidReleaseRecord(request);
  if (!record.ok) {
    return jsonResponse(
      { error: "Bad Request" },
      400,
      request,
      input.allowOrigin
    );
  }
  return jsonResponse(
    await writeDistrokidRelease(
      input.distrokidStateRoot,
      record.collectionId,
      record.disc,
      record.albumTitle
    ),
    200,
    request,
    input.allowOrigin
  );
};

const parseCollectionDistrokidPath = (
  pathname: string
): { collectionId: string; subpath: string } | null => {
  const routePrefix = `${COLLECTIONS_ROUTE}/`;
  const rest = pathname.slice(routePrefix.length);
  const [collectionId, subpath] = rest.split(/\/(.+)/u);
  return collectionId === undefined || subpath === undefined
    ? null
    : { collectionId, subpath };
};

const handleCollectionAsset = async (
  request: Request,
  input: CollectionServeInput,
  collectionDir: string,
  relpath: string
): Promise<Response> => {
  const asset = await resolveDistrokidAssetPath(collectionDir, relpath);
  return asset === null
    ? notFoundResponse(request, input)
    : fileResponse(request, input, asset, "application/octet-stream");
};

const handleCollectionRelease = async (
  request: Request,
  input: CollectionServeInput,
  config: ChannelConfig,
  parsed: {
    readonly collectionDir: string;
    readonly collectionId: string;
    readonly subpath: string;
  }
): Promise<Response> => {
  if (
    !parsed.subpath.startsWith("distrokid/") ||
    !parsed.subpath.endsWith("/release.json")
  ) {
    return notFoundResponse(request, input);
  }
  const disc = parsed.subpath.slice(
    "distrokid/".length,
    -"/release.json".length
  );
  if (disc.length === 0 || disc.includes("/")) {
    return notFoundResponse(request, input);
  }
  const knownDiscs = await findDistrokidDiscs(parsed.collectionDir);
  if (!knownDiscs.includes(disc)) {
    return notFoundResponse(request, input);
  }
  try {
    const payload = await buildDistrokidReleasePayload(
      parsed.collectionDir,
      config.integrations.distrokid,
      {
        assetsPrefix: `${COLLECTIONS_ROUTE}/${parsed.collectionId}/distrokid/assets/`,
        disc,
      }
    );
    return jsonResponse(payload, 200, request, input.allowOrigin);
  } catch (error) {
    return internalErrorResponse(error, request, input);
  }
};

export const handleDistrokidCollectionGet = async (
  request: Request,
  input: CollectionServeInput,
  config: ChannelConfig
): Promise<Response> => {
  const parsed = parseCollectionDistrokidPath(new URL(request.url).pathname);
  if (parsed === null || !config.integrations.distrokid.enabled) {
    return notFoundResponse(request, input);
  }
  const collectionDir = await resolveKnownCollectionDir(
    input.path,
    parsed.collectionId
  );
  if (collectionDir === null) {
    return notFoundResponse(request, input);
  }
  if (parsed.subpath.startsWith("distrokid/assets/")) {
    return handleCollectionAsset(
      request,
      input,
      collectionDir,
      parsed.subpath.slice("distrokid/assets/".length)
    );
  }
  return handleCollectionRelease(request, input, config, {
    collectionDir,
    collectionId: parsed.collectionId,
    subpath: parsed.subpath,
  });
};

export const handleDistrokidCollectionsIndex = async (
  request: Request,
  input: CollectionServeInput
): Promise<Response> => {
  const released =
    input.distrokidStateRoot === undefined
      ? new Set<string>()
      : await readReleasedDiscs(input.distrokidStateRoot);
  return jsonResponse(
    await buildDistrokidCollectionsIndex(input.path, released),
    200,
    request,
    input.allowOrigin
  );
};

export const handleSingleDistrokidRelease = async (
  request: Request,
  input: CollectionServeInput,
  config: ChannelConfig
): Promise<Response> => {
  try {
    const payload = await buildDistrokidReleasePayload(
      input.path,
      config.integrations.distrokid,
      {
        assetsPrefix: DISTROKID_ASSETS_PREFIX,
        source: input.distrokidSource,
      }
    );
    return jsonResponse(payload, 200, request, input.allowOrigin);
  } catch (error) {
    return internalErrorResponse(error, request, input);
  }
};

export const handleSingleDistrokidAsset = async (
  request: Request,
  input: CollectionServeInput
): Promise<Response> => {
  const asset = await resolveDistrokidAssetPath(
    input.path,
    new URL(request.url).pathname.slice(DISTROKID_ASSETS_PREFIX.length)
  );
  return asset === null
    ? notFoundResponse(request, input)
    : fileResponse(request, input, asset, "application/octet-stream");
};

export const isSingleDistrokidReleaseRoute = (pathname: string): boolean =>
  pathname === DISTROKID_RELEASE_ROUTE;
