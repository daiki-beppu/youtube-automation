import { readFile, stat, readdir } from "node:fs/promises";
import { basename, join } from "node:path";

import {
  deriveCollectionPlaylistName,
  deriveCollectionSlug,
  readMappedPlaylistSlugs,
} from "./playlists.ts";

const DOCUMENTATION_DIR = "20-documentation";
const SUNO_PROMPTS_JSON = "suno-prompts.json";
const COLLECTION_SUFFIX = "-collection";

export type NodeError = Error & { code?: string };

export interface CollectionSummary {
  readonly has_prompts: boolean;
  readonly id: string;
  readonly mapped: boolean;
  readonly name: string;
  readonly pattern_count: number | null;
  readonly playlist_name: string | null;
}

export interface PlaylistCaptureIndexOptions {
  readonly prefix: string;
  readonly root: string;
}

const promptPathFor = (root: string, collectionId: string): string =>
  join(root, collectionId, DOCUMENTATION_DIR, SUNO_PROMPTS_JSON);

const listCollectionDirs = async (root: string): Promise<string[]> => {
  const entries = await readdir(root, { withFileTypes: true });
  return entries
    .filter(
      (entry) => entry.isDirectory() && entry.name.endsWith(COLLECTION_SUFFIX)
    )
    .map((entry) => entry.name)
    .toSorted();
};

const collectionDisplayName = (collectionId: string): string => {
  const [datePart, , ...nameParts] = collectionId.split("-");
  if (
    nameParts.length === 0 ||
    datePart === undefined ||
    !/^\d{8}$/u.test(datePart)
  ) {
    throw new Error(`validation: invalid collection id: ${collectionId}`);
  }
  return nameParts.join("-");
};

const readPromptCount = async (path: string): Promise<number | null> => {
  try {
    const text = await readFile(path, "utf-8");
    const parsed: unknown = JSON.parse(text);
    if (!Array.isArray(parsed)) {
      throw new TypeError(`validation: ${SUNO_PROMPTS_JSON} must be an array`);
    }
    return parsed.length;
  } catch (error) {
    if ((error as NodeError).code === "ENOENT") {
      return null;
    }
    throw error;
  }
};

export const buildCollectionsIndex = async (
  root: string,
  playlistCapture?: PlaylistCaptureIndexOptions
): Promise<CollectionSummary[]> => {
  const collectionIds = await listCollectionDirs(root);
  const mappedSlugs =
    playlistCapture === undefined
      ? new Set<string>()
      : readMappedPlaylistSlugs(playlistCapture.root);
  return Promise.all(
    collectionIds.map(async (collectionId) => {
      const patternCount = await readPromptCount(
        promptPathFor(root, collectionId)
      );
      const collectionSlug =
        playlistCapture === undefined
          ? null
          : deriveCollectionSlug(collectionId, playlistCapture.prefix);
      return {
        has_prompts: patternCount !== null,
        id: collectionId,
        mapped: collectionSlug !== null && mappedSlugs.has(collectionSlug),
        name: collectionDisplayName(collectionId),
        pattern_count: patternCount,
        playlist_name:
          playlistCapture === undefined
            ? null
            : deriveCollectionPlaylistName(
                collectionId,
                playlistCapture.prefix
              ),
      };
    })
  );
};

export const resolveCollectionPromptsPath = async (
  root: string,
  collectionId: string
): Promise<string | null> => {
  const knownIds = await listCollectionDirs(root);
  if (!knownIds.includes(collectionId)) {
    return null;
  }
  return promptPathFor(root, collectionId);
};

export const resolveKnownCollectionDir = async (
  root: string,
  collectionId: string
): Promise<string | null> => {
  const knownIds = await listCollectionDirs(root);
  if (!knownIds.includes(collectionId)) {
    return null;
  }
  return join(root, collectionId);
};

const resolveSingleCollectionPromptsPath = (root: string): string =>
  join(root, DOCUMENTATION_DIR, SUNO_PROMPTS_JSON);

export const resolveSinglePromptsPath = async (
  path: string
): Promise<string> => {
  const info = await stat(path);
  return info.isFile() ? path : resolveSingleCollectionPromptsPath(path);
};

export const resolveCollectionServeMode = async (
  path: string
): Promise<"dir" | "single"> => {
  const info = await stat(path);
  if (!info.isDirectory()) {
    return "single";
  }
  return basename(path).endsWith(COLLECTION_SUFFIX) ? "single" : "dir";
};
