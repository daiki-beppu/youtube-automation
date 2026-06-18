import type { ChannelConfig } from "../config/index.ts";
import { classifyGaxiosError, YouTubeAPIError } from "../errors.ts";
import type { PlaylistClient, PlaylistItem, PlaylistRecord } from "./types.ts";

export const listPlaylistItems = async (
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

export const hasVideo = (
  items: readonly PlaylistItem[],
  videoId: string
): boolean => items.some((item) => videoIdOf(item) === videoId);

export const insertVideoIntoPlaylist = async (
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

const playlistDescription = (
  config: ChannelConfig,
  playlist: PlaylistRecord
): string => {
  const rawDescription =
    config.engagement.playlists.items[playlist.key]?.description;
  return typeof rawDescription === "string" ? rawDescription : "";
};

export const createPlaylist = async (
  client: PlaylistClient,
  config: ChannelConfig,
  playlist: PlaylistRecord
): Promise<string> => {
  if (playlist.configuredTitle === undefined) {
    throw new Error(`config: playlists.${playlist.key}.title is required`);
  }
  try {
    const response = await client.playlists.insert({
      part: "snippet,status",
      requestBody: {
        snippet: {
          description: playlistDescription(config, playlist),
          title: playlist.configuredTitle,
        },
        status: { privacyStatus: "public" },
      },
    });
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
  } catch (error) {
    if (error instanceof YouTubeAPIError) {
      throw error;
    }
    throw classifyGaxiosError(error, "playlists.insert");
  }
};

export const deletePlaylistItem = async (
  client: PlaylistClient,
  itemId: string
): Promise<void> => {
  try {
    await client.playlistItems.delete({ id: itemId });
  } catch (error) {
    throw classifyGaxiosError(error, "playlistItems.delete");
  }
};
