import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import { writePlaylistId, withCreatedPlaylistIds } from "./config-writer.ts";
import {
  liveCollectionDirs,
  readSyncedCollectionInput,
} from "./live-collections.ts";
import {
  activitiesForTheme,
  matchesAssignment,
  splitActivities,
} from "./matching.ts";
import {
  DELETED_VIDEO_TITLES,
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
import { operationFor, playlistEntries, youtubeClient } from "./types.ts";
import type {
  PlaylistAssignment,
  PlaylistChannelDeps,
  PlaylistClient,
  PlaylistCoreDeps,
  PlaylistRecord,
} from "./types.ts";
import {
  createPlaylist,
  deletePlaylistItem,
  hasVideo,
  insertVideoIntoPlaylist,
  listPlaylistItems,
} from "./youtube.ts";

const appendAll = <T>(items: readonly T[], additions: readonly T[]): T[] => [
  ...items,
  ...additions,
];

const assignToPlaylist = async (
  client: PlaylistClient,
  playlist: PlaylistRecord,
  input: PlaylistAssignInput,
  activities: readonly string[]
): Promise<PlaylistAssignment | null> => {
  if (!matchesAssignment(playlist, input.theme, activities)) {
    return null;
  }
  if (playlist.playlistId === undefined) {
    return null;
  }
  const items = await listPlaylistItems(client, playlist.playlistId);
  const alreadyPresent = hasVideo(items, input.videoId);
  if (!alreadyPresent) {
    await insertVideoIntoPlaylist(
      client,
      playlist.playlistId,
      playlist.key,
      input.videoId
    );
  }
  return {
    ...operationFor(playlist, input.dryRun),
    alreadyPresent,
    inserted: !alreadyPresent,
  };
};

const assignResolvedVideo = async (
  deps: PlaylistCoreDeps,
  input: PlaylistAssignInput,
  activityOverride?: string
): Promise<PlaylistAssignOutput> => {
  const activities =
    activityOverride === undefined
      ? activitiesForTheme(deps.config, input.theme)
      : splitActivities(activityOverride);
  const playlists = playlistEntries(deps.config);
  if (input.dryRun) {
    return PlaylistAssignOutputSchema.parse({
      assigned: playlists.flatMap((playlist) =>
        playlist.playlistId !== undefined &&
        matchesAssignment(playlist, input.theme, activities)
          ? [
              {
                ...operationFor(playlist, input.dryRun),
                alreadyPresent: false,
                inserted: false,
              },
            ]
          : []
      ),
    });
  }

  const client = youtubeClient(deps.yt);
  let assigned: PlaylistAssignOutput["assigned"] = [];
  for (const playlist of playlists) {
    const assignment = await assignToPlaylist(
      client,
      playlist,
      input,
      activities
    );
    assigned =
      assignment === null ? assigned : appendAll(assigned, [assignment]);
  }

  return PlaylistAssignOutputSchema.parse({ assigned });
};

const createPlaylistOperation = async (
  deps: PlaylistChannelDeps,
  input: PlaylistCreateInput,
  playlist: PlaylistRecord
): Promise<
  | { created: PlaylistCreateOutput["created"]; skipped: [] }
  | { created: []; skipped: PlaylistCreateOutput["skipped"] }
> => {
  if (playlist.playlistId !== undefined) {
    return { created: [], skipped: [operationFor(playlist, input.dryRun)] };
  }
  if (input.dryRun) {
    return { created: [operationFor(playlist, input.dryRun)], skipped: [] };
  }
  const client = youtubeClient(deps.yt);
  const playlistId = await createPlaylist(client, deps.config, playlist);
  await writePlaylistId(deps.channelDir, playlist.key, playlistId);
  return {
    created: [
      {
        ...operationFor(playlist, input.dryRun),
        playlistId,
      },
    ],
    skipped: [],
  };
};

const statusPlaylistOperation = async (
  client: PlaylistClient,
  playlist: PlaylistRecord
): Promise<PlaylistStatusOutput["playlists"][number]> => {
  if (playlist.playlistId === undefined) {
    return operationFor(playlist, false);
  }
  const items = await listPlaylistItems(client, playlist.playlistId);
  return {
    ...operationFor(playlist, false),
    videoCount: items.length,
  };
};

const cleanDeletedPlaylistOperation = async (
  client: PlaylistClient,
  input: PlaylistCleanDeletedInput,
  playlist: PlaylistRecord
): Promise<PlaylistCleanDeletedOutput["cleaned"]> => {
  if (playlist.playlistId === undefined) {
    return [];
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
    for (const item of removedItems) {
      await deletePlaylistItem(client, item.itemId);
    }
  }
  return [
    {
      ...operationFor(playlist, input.dryRun),
      removedItems,
    },
  ];
};

const syncCollection = async (
  deps: PlaylistChannelDeps,
  input: PlaylistSyncInput,
  collectionDir: string
): Promise<PlaylistSyncOutput["synced"]> => {
  const collection = await readSyncedCollectionInput(collectionDir);
  if (collection === undefined) {
    return [];
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
  return [
    {
      assigned: output.assigned,
      collectionName: collection.collectionName,
      theme: collection.theme,
      videoId: collection.videoId,
    },
  ];
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
  const playlists = playlistEntries(deps.config);
  assertCreateTargetsHaveTitles(playlists);
  let created: PlaylistCreateOutput["created"] = [];
  let skipped: PlaylistCreateOutput["skipped"] = [];
  for (const playlist of playlists) {
    const operation = await createPlaylistOperation(deps, input, playlist);
    created = appendAll(created, operation.created);
    skipped = appendAll(skipped, operation.skipped);
  }

  return PlaylistCreateOutputSchema.parse({
    created,
    skipped,
  });
};

const syncExistingVideos = async (
  deps: PlaylistChannelDeps,
  input: PlaylistSyncInput
): Promise<PlaylistSyncOutput> => {
  let synced: PlaylistSyncOutput["synced"] = [];
  for (const collectionDir of await liveCollectionDirs(deps.channelDir)) {
    synced = appendAll(
      synced,
      await syncCollection(deps, input, collectionDir)
    );
  }
  return PlaylistSyncOutputSchema.parse({ synced });
};

const cleanDeleted = async (
  deps: PlaylistCoreDeps,
  input: PlaylistCleanDeletedInput
): Promise<PlaylistCleanDeletedOutput> => {
  const client = youtubeClient(deps.yt);
  let cleaned: PlaylistCleanDeletedOutput["cleaned"] = [];
  for (const playlist of playlistEntries(deps.config)) {
    cleaned = appendAll(
      cleaned,
      await cleanDeletedPlaylistOperation(client, input, playlist)
    );
  }

  return PlaylistCleanDeletedOutputSchema.parse({ cleaned });
};

export const playlistStatusService = async (
  _input: PlaylistStatusInput,
  deps: PlaylistCoreDeps
): Promise<Result<PlaylistStatusOutput, ServiceError>> => {
  try {
    const client = youtubeClient(deps.yt);
    let playlists: PlaylistStatusOutput["playlists"] = [];
    for (const playlist of playlistEntries(deps.config)) {
      playlists = appendAll(playlists, [
        await statusPlaylistOperation(client, playlist),
      ]);
    }
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
    return ok(await assignResolvedVideo(deps, input));
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
