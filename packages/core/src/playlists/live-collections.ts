import type { Dirent } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import { basename, join } from "node:path";

interface CollectionUploadTracking {
  complete_collection?: {
    video_id?: unknown;
  };
}

interface CollectionWorkflowState {
  planning?: {
    activities?: unknown;
  };
  theme?: unknown;
}

export interface SyncedCollectionInput {
  activityOverride?: string;
  collectionName: string;
  theme: string;
  videoId: string;
}

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

export const liveCollectionDirs = async (
  channelDir: string
): Promise<string[]> => {
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

export const readSyncedCollectionInput = async (
  collectionDir: string
): Promise<SyncedCollectionInput | undefined> => {
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
