import type { Dirent } from "node:fs";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";

import { activityForTheme } from "../config/index.ts";
import type { ChannelConfig } from "../config/index.ts";
import {
  classifyGaxiosError,
  toServiceError,
  YouTubeAPIError,
} from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import type { YouTubeClient } from "../oauth/client.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import {
  DELETED_VIDEO_TITLES,
  PLAYLISTS_CONFIG_PATH,
  PlaylistAssignOutputSchema,
  PlaylistCleanDeletedOutputSchema,
  PlaylistCreateOutputSchema,
  PlaylistInitOutputSchema,
  PlaylistStatusOutputSchema,
  PlaylistSyncOutputSchema,
} from "./schema.ts";
import type {
  PlaylistAssignInput,
  PlaylistAssignOutput,
  PlaylistCleanDeletedInput,
  PlaylistCleanDeletedOutput,
  PlaylistCreateInput,
  PlaylistCreateOutput,
  PlaylistInitInput,
  PlaylistInitOutput,
  PlaylistStatusInput,
  PlaylistStatusOutput,
  PlaylistSyncInput,
  PlaylistSyncOutput,
} from "./schema.ts";

interface PlaylistCoreDeps {
  config: ChannelConfig;
  yt: YouTubeClient;
}

interface PlaylistChannelDeps extends PlaylistCoreDeps {
  channelDir: string;
}

interface PlaylistRecord {
  key: string;
  playlistId?: string;
  configuredTitle?: string;
  title: string;
  autoAdd: boolean;
  autoAddActivities: readonly string[];
  autoAddThemes: readonly string[];
}

interface PlaylistItem {
  id?: string;
  snippet?: {
    resourceId?: { videoId?: string };
    title?: string;
  };
  contentDetails?: { videoId?: string };
}

interface PlaylistItemsListResponse {
  data: {
    items?: PlaylistItem[];
    nextPageToken?: string;
  };
}

interface CollectionUploadTracking {
  complete_collection?: {
    video_id?: unknown;
  };
}

interface CollectionWorkflowState {
  planning?: {
    activities?: unknown;
  };
  steps?: {
    planning?: {
      final_title?: unknown;
    };
  };
  theme?: unknown;
}

interface PlaylistInsertResponse {
  data: { id?: string | null };
}

interface PlaylistClient {
  playlistItems: {
    delete(params: { id: string }): Promise<unknown>;
    insert(params: {
      part: string;
      requestBody: {
        snippet: {
          playlistId: string;
          position?: number;
          resourceId: { kind: string; videoId: string };
        };
      };
    }): Promise<unknown>;
    list(params: {
      maxResults: number;
      pageToken?: string;
      part: string;
      playlistId: string;
    }): Promise<PlaylistItemsListResponse>;
  };
  playlists: {
    insert(params: {
      part: string;
      requestBody: {
        snippet: { description: string; title: string };
        status: { privacyStatus: string };
      };
    }): Promise<PlaylistInsertResponse>;
  };
}

type PlaylistOperation = PlaylistCreateOutput["created"][number];
type PlaylistAssignment = PlaylistAssignOutput["assigned"][number];

const youtubeClient = (yt: YouTubeClient): PlaylistClient =>
  yt as unknown as PlaylistClient;

const isPresent = <T>(value: T | null): value is T => value !== null;

const stringArray = (value: unknown): readonly string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];

const playlistEntries = (config: ChannelConfig): PlaylistRecord[] =>
  Object.entries(config.engagement.playlists.items).map(([key, raw]) => {
    const playlistId =
      typeof raw.playlist_id === "string" ? raw.playlist_id : undefined;
    const rawTitle = raw.title;
    const configuredTitle =
      typeof rawTitle === "string" && rawTitle.trim().length > 0
        ? rawTitle
        : undefined;
    return {
      autoAdd: raw.auto_add === true,
      autoAddActivities: stringArray(raw.auto_add_activities),
      autoAddThemes: stringArray(raw.auto_add_themes),
      configuredTitle,
      key,
      playlistId,
      title: configuredTitle ?? key,
    };
  });

const operationFor = (
  playlist: PlaylistRecord,
  dryRun: boolean
): PlaylistOperation => ({
  dryRun,
  key: playlist.key,
  playlistId: playlist.playlistId,
  title: playlist.title,
});

const splitActivities = (activities: string): readonly string[] =>
  activities
    .split(/[·,|/]/u)
    .map((activity) => activity.trim())
    .filter((activity) => activity.length > 0);

const activitiesForTheme = (
  config: ChannelConfig,
  theme: string
): readonly string[] =>
  splitActivities(activityForTheme(config.publishing.content.title, theme));

const matchesAssignment = (
  playlist: PlaylistRecord,
  theme: string,
  activities: readonly string[]
): boolean => {
  if (playlist.autoAdd) {
    return true;
  }
  const themeLower = theme.toLowerCase();
  if (
    playlist.autoAddThemes.some((keyword) =>
      themeLower.includes(keyword.toLowerCase())
    )
  ) {
    return true;
  }
  return playlist.autoAddActivities.some((expected) =>
    activities.includes(expected)
  );
};

const listPlaylistItems = async (
  client: PlaylistClient,
  playlistId: string
): Promise<PlaylistItem[]> => {
  const listPage = async (pageToken?: string): Promise<PlaylistItem[]> => {
    const response = await client.playlistItems.list({
      maxResults: 50,
      pageToken,
      part: "snippet,contentDetails",
      playlistId,
    });
    const { items = [], nextPageToken } = response.data;
    if (nextPageToken === undefined) {
      return items;
    }
    return [...items, ...(await listPage(nextPageToken))];
  };

  try {
    return await listPage();
  } catch (error) {
    throw classifyGaxiosError(error, "playlistItems.list");
  }
};

const videoIdOf = (item: PlaylistItem): string | undefined =>
  item.contentDetails?.videoId ?? item.snippet?.resourceId?.videoId;

const hasVideo = (items: readonly PlaylistItem[], videoId: string): boolean =>
  items.some((item) => videoIdOf(item) === videoId);

const insertVideoIntoPlaylist = async (
  client: PlaylistClient,
  playlist: PlaylistRecord,
  videoId: string
): Promise<void> => {
  if (playlist.playlistId === undefined) {
    throw new Error(`config: playlist ${playlist.key} is missing playlist_id`);
  }
  const snippet =
    playlist.key === "all"
      ? {
          playlistId: playlist.playlistId,
          resourceId: { kind: "youtube#video", videoId },
        }
      : {
          playlistId: playlist.playlistId,
          position: 0,
          resourceId: { kind: "youtube#video", videoId },
        };
  try {
    await client.playlistItems.insert({
      part: "snippet",
      requestBody: { snippet },
    });
  } catch (error) {
    throw classifyGaxiosError(error, "playlistItems.insert");
  }
};

const assignToPlaylist = async (
  client: PlaylistClient,
  playlist: PlaylistRecord,
  input: PlaylistAssignInput,
  activities: readonly string[]
): Promise<PlaylistAssignment | null> => {
  if (
    playlist.playlistId === undefined ||
    !matchesAssignment(playlist, input.theme, activities)
  ) {
    return null;
  }
  const items = await listPlaylistItems(client, playlist.playlistId);
  const alreadyPresent = hasVideo(items, input.videoId);
  if (!(input.dryRun || alreadyPresent)) {
    await insertVideoIntoPlaylist(client, playlist, input.videoId);
  }
  return {
    ...operationFor(playlist, input.dryRun),
    alreadyPresent,
    inserted: !(input.dryRun || alreadyPresent),
  };
};

const assignResolvedVideo = async (
  deps: PlaylistCoreDeps,
  input: PlaylistAssignInput,
  activityOverride?: string
): Promise<PlaylistAssignOutput> => {
  const client = youtubeClient(deps.yt);
  const activities =
    activityOverride === undefined
      ? activitiesForTheme(deps.config, input.theme)
      : splitActivities(activityOverride);
  const assignmentResults = await Promise.all(
    playlistEntries(deps.config).map((playlist) =>
      assignToPlaylist(client, playlist, input, activities)
    )
  );
  const assigned = assignmentResults.filter(isPresent);

  return PlaylistAssignOutputSchema.parse({ assigned });
};

const assignVideo = (
  deps: PlaylistCoreDeps,
  input: PlaylistAssignInput
): Promise<PlaylistAssignOutput> => assignResolvedVideo(deps, input);

const playlistsConfigFile = (channelDir: string): string =>
  join(channelDir, PLAYLISTS_CONFIG_PATH);

const writePlaylistId = async (
  channelDir: string,
  key: string,
  playlistId: string
): Promise<void> => {
  const path = playlistsConfigFile(channelDir);
  const raw = JSON.parse(await readFile(path, "utf-8")) as {
    playlists?: Record<string, unknown>;
  };
  const { playlists } = raw;
  if (playlists === undefined || typeof playlists !== "object") {
    throw new Error(
      `config: ${PLAYLISTS_CONFIG_PATH} playlists must be object`
    );
  }
  const current = playlists[key];
  const nextEntry =
    typeof current === "string" ? { playlist_id: playlistId } : current;
  if (nextEntry === null || typeof nextEntry !== "object") {
    throw new Error(`config: playlists.${key} must be object or string`);
  }
  const next = {
    ...raw,
    playlists: {
      ...playlists,
      [key]: { ...nextEntry, playlist_id: playlistId },
    },
  };
  await writeFile(path, `${JSON.stringify(next, null, 2)}\n`, "utf-8");
};

const withCreatedPlaylistIds = (
  config: ChannelConfig,
  created: readonly PlaylistOperation[]
): ChannelConfig => {
  const createdByKey = new Map(
    created.flatMap((playlist) =>
      playlist.playlistId === undefined
        ? []
        : [[playlist.key, playlist.playlistId] as const]
    )
  );
  if (createdByKey.size === 0) {
    return config;
  }
  const items = Object.fromEntries(
    Object.entries(config.engagement.playlists.items).map(([key, value]) => [
      key,
      createdByKey.has(key)
        ? { ...value, playlist_id: createdByKey.get(key) }
        : value,
    ])
  );
  return {
    ...config,
    engagement: {
      ...config.engagement,
      playlists: { items },
    },
  };
};

const playlistDescription = (
  config: ChannelConfig,
  playlist: PlaylistRecord
): string => {
  const rawDescription =
    config.engagement.playlists.items[playlist.key]?.description;
  return typeof rawDescription === "string"
    ? rawDescription
    : `Auto-managed playlist for ${playlist.title}`;
};

const createPlaylist = async (
  client: PlaylistClient,
  config: ChannelConfig,
  playlist: PlaylistRecord
): Promise<string> => {
  if (playlist.configuredTitle === undefined) {
    throw new Error(`config: playlists.${playlist.key}.title is required`);
  }
  let response: PlaylistInsertResponse;
  try {
    response = await client.playlists.insert({
      part: "snippet,status",
      requestBody: {
        snippet: {
          description: playlistDescription(config, playlist),
          title: playlist.configuredTitle,
        },
        status: { privacyStatus: "public" },
      },
    });
  } catch (error) {
    throw classifyGaxiosError(error, "playlists.insert");
  }

  const { id: playlistId } = response.data;
  if (typeof playlistId !== "string" || playlistId.length === 0) {
    throw new YouTubeAPIError(
      "playlists.insert: response is missing playlist id",
      {
        context: "playlists.insert",
      }
    );
  }
  return playlistId;
};

const createPlaylistOperations = async (
  deps: PlaylistChannelDeps,
  input: PlaylistCreateInput,
  client: PlaylistClient,
  playlists: readonly PlaylistRecord[]
): Promise<PlaylistCreateOutput> => {
  const [playlist, ...rest] = playlists;
  if (playlist === undefined) {
    return { created: [], skipped: [] };
  }
  if (playlist.playlistId !== undefined) {
    const next = await createPlaylistOperations(deps, input, client, rest);
    return {
      created: next.created,
      skipped: [operationFor(playlist, input.dryRun), ...next.skipped],
    };
  }
  if (playlist.configuredTitle === undefined) {
    throw new Error(`config: playlists.${playlist.key}.title is required`);
  }
  if (input.dryRun) {
    const next = await createPlaylistOperations(deps, input, client, rest);
    return {
      created: [operationFor(playlist, input.dryRun), ...next.created],
      skipped: next.skipped,
    };
  }
  const playlistId = await createPlaylist(client, deps.config, playlist);
  await writePlaylistId(deps.channelDir, playlist.key, playlistId);
  const next = await createPlaylistOperations(deps, input, client, rest);
  return {
    created: [
      { ...operationFor(playlist, input.dryRun), playlistId },
      ...next.created,
    ],
    skipped: next.skipped,
  };
};

const assertCreateTargetsHaveTitles = (
  playlists: readonly PlaylistRecord[]
): void => {
  const invalid = playlists.find(
    (playlist) =>
      playlist.playlistId === undefined &&
      playlist.configuredTitle === undefined
  );
  if (invalid !== undefined) {
    throw new Error(`config: playlists.${invalid.key}.title is required`);
  }
};

const createPlaylists = async (
  deps: PlaylistChannelDeps,
  input: PlaylistCreateInput
): Promise<PlaylistCreateOutput> => {
  const client = youtubeClient(deps.yt);
  const playlists = playlistEntries(deps.config);
  assertCreateTargetsHaveTitles(playlists);
  const { created, skipped } = await createPlaylistOperations(
    deps,
    input,
    client,
    playlists
  );
  return PlaylistCreateOutputSchema.parse({ created, skipped });
};

const readJsonFile = async <T>(path: string): Promise<T> =>
  JSON.parse(await readFile(path, "utf-8")) as T;

const readOptionalJsonFile = async <T>(
  path: string
): Promise<T | undefined> => {
  try {
    return await readJsonFile<T>(path);
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return undefined;
    }
    throw error;
  }
};

const collectionsLiveDir = (channelDir: string): string =>
  join(channelDir, "collections", "live");

const liveCollectionDirs = async (channelDir: string): Promise<string[]> => {
  const liveDir = collectionsLiveDir(channelDir);
  let entries: Dirent[];
  try {
    entries = await readdir(liveDir, { withFileTypes: true });
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return [];
    }
    throw error;
  }
  return entries
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
    .map((entry) => join(liveDir, entry.name))
    .toSorted();
};

const workflowStatePath = (collectionDir: string): string =>
  join(collectionDir, "workflow-state.json");

const uploadTrackingPath = (collectionDir: string): string =>
  join(collectionDir, "20-documentation", "upload_tracking.json");

const collectionName = (collectionDir: string): string =>
  basename(collectionDir);

const readSyncedCollectionInput = async (
  collectionDir: string
): Promise<
  | {
      activityOverride?: string;
      collectionName: string;
      theme: string;
      videoId: string;
    }
  | undefined
> => {
  const workflow = await readOptionalJsonFile<CollectionWorkflowState>(
    workflowStatePath(collectionDir)
  );
  if (workflow === undefined) {
    return undefined;
  }
  if (typeof workflow.theme !== "string" || workflow.theme.length === 0) {
    return undefined;
  }
  const tracking = await readOptionalJsonFile<CollectionUploadTracking>(
    uploadTrackingPath(collectionDir)
  );
  if (tracking === undefined) {
    return undefined;
  }
  const videoId = tracking.complete_collection?.video_id;
  if (typeof videoId !== "string" || videoId.length === 0) {
    return undefined;
  }
  const activities = workflow.planning?.activities;
  return {
    activityOverride:
      typeof activities === "string" && activities.length > 0
        ? activities
        : undefined,
    collectionName: collectionName(collectionDir),
    theme: workflow.theme,
    videoId,
  };
};

const syncExistingVideos = async (
  deps: PlaylistChannelDeps,
  input: PlaylistSyncInput
): Promise<PlaylistSyncOutput> => {
  const collectionDirs = await liveCollectionDirs(deps.channelDir);
  const syncResults = await Promise.all(
    collectionDirs.map(async (collectionDir) => {
      const collection = await readSyncedCollectionInput(collectionDir);
      if (collection === undefined) {
        return null;
      }
      const output = await assignResolvedVideo(
        deps,
        {
          dryRun: input.dryRun,
          theme: collection.theme,
          videoId: collection.videoId,
        },
        collection.activityOverride
      );
      return {
        assigned: output.assigned,
        collectionName: collection.collectionName,
        theme: collection.theme,
        videoId: collection.videoId,
      };
    })
  );
  const synced = syncResults.filter(isPresent);
  return PlaylistSyncOutputSchema.parse({ synced });
};

const deletePlaylistItem = async (
  client: PlaylistClient,
  itemId: string
): Promise<void> => {
  try {
    await client.playlistItems.delete({ id: itemId });
  } catch (error) {
    throw classifyGaxiosError(error, "playlistItems.delete");
  }
};

const cleanDeleted = async (
  deps: PlaylistCoreDeps,
  input: PlaylistCleanDeletedInput
): Promise<PlaylistCleanDeletedOutput> => {
  const client = youtubeClient(deps.yt);
  const cleanResults = await Promise.all(
    playlistEntries(deps.config).map(async (playlist) => {
      if (playlist.playlistId === undefined) {
        return null;
      }
      const items = await listPlaylistItems(client, playlist.playlistId);
      const removedItems = items.flatMap((item) => {
        const title = item.snippet?.title;
        if (
          item.id === undefined ||
          title === undefined ||
          !DELETED_VIDEO_TITLES.has(title)
        ) {
          return [];
        }
        return [{ itemId: item.id, title }];
      });
      if (!input.dryRun) {
        await Promise.all(
          removedItems.map((item) => deletePlaylistItem(client, item.itemId))
        );
      }
      return { ...operationFor(playlist, input.dryRun), removedItems };
    })
  );
  const cleaned = cleanResults.filter(isPresent);

  return PlaylistCleanDeletedOutputSchema.parse({ cleaned });
};

export const playlistStatusService = async (
  _input: PlaylistStatusInput,
  deps: PlaylistCoreDeps
): Promise<Result<PlaylistStatusOutput, ServiceError>> => {
  try {
    const client = youtubeClient(deps.yt);
    const playlists = await Promise.all(
      playlistEntries(deps.config).map(async (playlist) => {
        if (playlist.playlistId === undefined) {
          return operationFor(playlist, false);
        }
        const items = await listPlaylistItems(client, playlist.playlistId);
        return {
          ...operationFor(playlist, false),
          videoCount: items.length,
        };
      })
    );
    return ok(PlaylistStatusOutputSchema.parse({ playlists }));
  } catch (error) {
    return err(toServiceError(error));
  }
};

export const playlistCreateService = async (
  input: PlaylistCreateInput,
  deps: PlaylistChannelDeps
): Promise<Result<PlaylistCreateOutput, ServiceError>> => {
  try {
    return ok(await createPlaylists(deps, input));
  } catch (error) {
    return err(toServiceError(error));
  }
};

export const playlistAssignService = async (
  input: PlaylistAssignInput,
  deps: PlaylistCoreDeps
): Promise<Result<PlaylistAssignOutput, ServiceError>> => {
  try {
    return ok(await assignVideo(deps, input));
  } catch (error) {
    return err(toServiceError(error));
  }
};

export const playlistCleanDeletedService = async (
  input: PlaylistCleanDeletedInput,
  deps: PlaylistCoreDeps
): Promise<Result<PlaylistCleanDeletedOutput, ServiceError>> => {
  try {
    return ok(await cleanDeleted(deps, input));
  } catch (error) {
    return err(toServiceError(error));
  }
};

export const playlistSyncService = async (
  input: PlaylistSyncInput,
  deps: PlaylistChannelDeps
): Promise<Result<PlaylistSyncOutput, ServiceError>> => {
  try {
    return ok(await syncExistingVideos(deps, input));
  } catch (error) {
    return err(toServiceError(error));
  }
};

export const playlistInitService = async (
  input: PlaylistInitInput,
  deps: PlaylistChannelDeps
): Promise<Result<PlaylistInitOutput, ServiceError>> => {
  try {
    const output = await createPlaylists(deps, input);
    const syncDeps = {
      ...deps,
      config: withCreatedPlaylistIds(deps.config, output.created),
    };
    const synced = await syncExistingVideos(syncDeps, input);
    return ok(PlaylistInitOutputSchema.parse({ ...output, ...synced }));
  } catch (error) {
    return err(toServiceError(error));
  }
};
