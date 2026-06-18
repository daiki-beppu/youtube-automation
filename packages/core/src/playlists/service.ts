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

const assignToPlaylist = async (
  client: PlaylistClient,
  playlist: PlaylistRecord,
  input: PlaylistAssignInput,
  activities: readonly string[]
): Promise<PlaylistAssignment | null> => {
  if (!matchesAssignment(playlist, input.theme, activities)) {
    return null;
  }
  if (input.dryRun) {
    return {
      ...operationFor(playlist, input.dryRun),
      alreadyPresent: false,
      inserted: false,
    };
  }
  if (playlist.playlistId === undefined) {
    return null;
  }
  const items = await listPlaylistItems(client, playlist.playlistId);
  const alreadyPresent = hasVideo(items, input.videoId);
  if (!alreadyPresent) {
    await insertVideoIntoPlaylist(client, playlist, input.videoId);
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
  const client = youtubeClient(deps.yt);
  const activities =
    activityOverride === undefined
      ? activitiesForTheme(deps.config, input.theme)
      : splitActivities(activityOverride);
  let assigned: PlaylistAssignOutput["assigned"] = [];
  for (const playlist of playlistEntries(deps.config)) {
    const assignment = await assignToPlaylist(
      client,
      playlist,
      input,
      activities
    );
    if (assignment !== null) {
      assigned = assigned.toSpliced(assigned.length, 0, assignment);
    }
  }

  return PlaylistAssignOutputSchema.parse({ assigned });
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
  let created: PlaylistCreateOutput["created"] = [];
  let skipped: PlaylistCreateOutput["skipped"] = [];

  for (const playlist of playlists) {
    if (playlist.playlistId !== undefined) {
      skipped = skipped.toSpliced(
        skipped.length,
        0,
        operationFor(playlist, input.dryRun)
      );
      continue;
    }
    if (input.dryRun) {
      created = created.toSpliced(
        created.length,
        0,
        operationFor(playlist, input.dryRun)
      );
      continue;
    }
    const playlistId = await createPlaylist(client, deps.config, playlist);
    await writePlaylistId(deps.channelDir, playlist.key, playlistId);
    created = created.toSpliced(created.length, 0, {
      ...operationFor(playlist, input.dryRun),
      playlistId,
    });
  }

  return PlaylistCreateOutputSchema.parse({ created, skipped });
};

const syncExistingVideos = async (
  deps: PlaylistChannelDeps,
  input: PlaylistSyncInput
): Promise<PlaylistSyncOutput> => {
  let synced: PlaylistSyncOutput["synced"] = [];
  for (const collectionDir of await liveCollectionDirs(deps.channelDir)) {
    const collection = await readSyncedCollectionInput(collectionDir);
    if (collection === undefined) {
      continue;
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
    synced = synced.toSpliced(synced.length, 0, {
      assigned: output.assigned,
      collectionName: collection.collectionName,
      theme: collection.theme,
      videoId: collection.videoId,
    });
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
    if (playlist.playlistId === undefined) {
      continue;
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
    cleaned = cleaned.toSpliced(cleaned.length, 0, {
      ...operationFor(playlist, input.dryRun),
      removedItems,
    });
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
      if (playlist.playlistId === undefined) {
        playlists = playlists.toSpliced(
          playlists.length,
          0,
          operationFor(playlist, false)
        );
        continue;
      }
      const items = await listPlaylistItems(client, playlist.playlistId);
      playlists = playlists.toSpliced(playlists.length, 0, {
        ...operationFor(playlist, false),
        videoCount: items.length,
      });
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
