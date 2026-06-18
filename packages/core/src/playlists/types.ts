import type { ChannelConfig } from "../config/index.ts";
import type { YouTubeClient } from "../oauth/client.ts";
import type { PlaylistAssignOutput, PlaylistCreateOutput } from "./schema.ts";

export const ALL_PLAYLIST_KEY = "all" as const;

export interface PlaylistCoreDeps {
  config: ChannelConfig;
  yt: YouTubeClient;
}

export interface PlaylistChannelDeps extends PlaylistCoreDeps {
  channelDir: string;
}

export interface PlaylistRecord {
  key: string;
  playlistId?: string;
  configuredTitle?: string;
  title: string;
  autoAdd: boolean;
  autoAddActivities: readonly string[];
  autoAddThemes: readonly string[];
}

export interface PlaylistItem {
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

interface PlaylistInsertResponse {
  data: { id?: string | null };
}

export interface PlaylistClient {
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

export type PlaylistOperation = PlaylistCreateOutput["created"][number];
export type PlaylistAssignment = PlaylistAssignOutput["assigned"][number];

export const youtubeClient = (
  yt: YouTubeClient | undefined
): PlaylistClient => {
  if (yt === undefined) {
    throw new Error("auth: YouTube client dependency is required");
  }
  return yt as unknown as PlaylistClient;
};

const stringArray = (value: unknown): readonly string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];

export const playlistEntries = (config: ChannelConfig): PlaylistRecord[] =>
  Object.entries(config.engagement.playlists.items).map(([key, raw]) => {
    const playlistId =
      typeof raw.playlist_id === "string" && raw.playlist_id.trim().length > 0
        ? raw.playlist_id.trim()
        : undefined;
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

export const operationFor = (
  playlist: PlaylistRecord,
  dryRun: boolean
): PlaylistOperation => ({
  dryRun,
  key: playlist.key,
  playlistId: playlist.playlistId,
  title: playlist.title,
});
