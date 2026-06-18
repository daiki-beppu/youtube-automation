import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

export const PLAYLISTS_CONFIG_PATH = "config/channel/playlists.json";

const DeletedVideoTitles = ["Deleted video", "Private video"] as const;
export const DELETED_VIDEO_TITLES = new Set<string>(DeletedVideoTitles);

const DryRunSnakeInput = z
  .object({ dry_run: z.boolean().default(false) })
  .strict()
  .transform(snakeToCamel);

const AssignSnakeInput = z
  .object({
    dry_run: z.boolean().default(false),
    theme: z.string().min(1),
    video_id: z.string().min(1),
  })
  .strict()
  .transform(snakeToCamel);

const PlaylistOperation = z
  .object({
    dryRun: z.boolean(),
    key: z.string(),
    persistError: z.string().optional(),
    persisted: z.boolean().optional(),
    playlistId: z.string().optional(),
    title: z.string(),
    videoCount: z.number().int().nonnegative().optional(),
  })
  .strict();

const PlaylistAssignment = PlaylistOperation.extend({
  alreadyPresent: z.boolean(),
  inserted: z.boolean(),
});

const PlaylistCleanup = PlaylistOperation.extend({
  removedItems: z.array(
    z
      .object({
        itemId: z.string(),
        title: z.string(),
      })
      .strict()
  ),
});

const PlaylistSyncedCollection = z
  .object({
    assigned: z.array(PlaylistAssignment),
    collectionName: z.string(),
    theme: z.string(),
    videoId: z.string(),
  })
  .strict();

export const PlaylistStatusInputSchema = z.object({}).strict();
export const PlaylistCreateInputSchema = DryRunSnakeInput;
export const PlaylistAssignInputSchema = AssignSnakeInput;
export const PlaylistCleanDeletedInputSchema = DryRunSnakeInput;
export const PlaylistSyncInputSchema = DryRunSnakeInput;
export const PlaylistInitInputSchema = DryRunSnakeInput;

export const PlaylistStatusOutputSchema = z
  .object({
    playlists: z.array(PlaylistOperation),
  })
  .strict();

export const PlaylistCreateOutputSchema = z
  .object({
    created: z.array(PlaylistOperation),
    skipped: z.array(PlaylistOperation),
  })
  .strict();

export const PlaylistAssignOutputSchema = z
  .object({
    assigned: z.array(PlaylistAssignment),
  })
  .strict();

export const PlaylistCleanDeletedOutputSchema = z
  .object({
    cleaned: z.array(PlaylistCleanup),
  })
  .strict();

export const PlaylistSyncOutputSchema = z
  .object({
    synced: z.array(PlaylistSyncedCollection),
  })
  .strict();

export const PlaylistInitOutputSchema = z
  .object({
    created: z.array(PlaylistOperation),
    skipped: z.array(PlaylistOperation),
    synced: z.array(PlaylistSyncedCollection),
  })
  .strict();

export type PlaylistStatusInput = z.infer<typeof PlaylistStatusInputSchema>;
export type PlaylistCreateInput = z.infer<typeof PlaylistCreateInputSchema>;
export type PlaylistAssignInput = z.infer<typeof PlaylistAssignInputSchema>;
export type PlaylistCleanDeletedInput = z.infer<
  typeof PlaylistCleanDeletedInputSchema
>;
export type PlaylistSyncInput = z.infer<typeof PlaylistSyncInputSchema>;
export type PlaylistInitInput = z.infer<typeof PlaylistInitInputSchema>;
export type PlaylistStatusOutput = z.infer<typeof PlaylistStatusOutputSchema>;
export type PlaylistCreateOutput = z.infer<typeof PlaylistCreateOutputSchema>;
export type PlaylistAssignOutput = z.infer<typeof PlaylistAssignOutputSchema>;
export type PlaylistCleanDeletedOutput = z.infer<
  typeof PlaylistCleanDeletedOutputSchema
>;
export type PlaylistSyncOutput = z.infer<typeof PlaylistSyncOutputSchema>;
export type PlaylistInitOutput = z.infer<typeof PlaylistInitOutputSchema>;
