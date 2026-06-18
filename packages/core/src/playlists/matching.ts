import { activityForTheme } from "../config/index.ts";
import type { ChannelConfig } from "../config/index.ts";
import type { PlaylistRecord } from "./types.ts";

export const splitActivities = (activities: string): readonly string[] =>
  activities
    .split(/[·,|/]/u)
    .map((activity) => activity.trim())
    .filter((activity) => activity.length > 0);

export const activitiesForTheme = (
  config: ChannelConfig,
  theme: string
): readonly string[] =>
  splitActivities(activityForTheme(config.publishing.content.title, theme));

export const matchesAssignment = (
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
