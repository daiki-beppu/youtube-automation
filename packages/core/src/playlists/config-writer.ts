import { readFile, rename, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";

import type { ChannelConfig } from "../config/index.ts";
import { PLAYLISTS_CONFIG_PATH } from "./schema.ts";
import type { PlaylistOperation } from "./types.ts";

const playlistsConfigFile = (channelDir: string): string =>
  join(channelDir, PLAYLISTS_CONFIG_PATH);

const atomicWriteFile = async (
  path: string,
  content: string
): Promise<void> => {
  const tempPath = join(
    dirname(path),
    `.${basename(path)}.${process.pid}.${Date.now()}.tmp`
  );
  try {
    await writeFile(tempPath, content, "utf-8");
    await rename(tempPath, path);
  } catch (error) {
    await rm(tempPath, { force: true, recursive: true });
    throw error;
  }
};

export const writePlaylistId = async (
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
  await atomicWriteFile(path, `${JSON.stringify(next, null, 2)}\n`);
};

export const withCreatedPlaylistIds = (
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
