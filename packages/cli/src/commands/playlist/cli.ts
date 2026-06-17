import { err, toServiceError } from "@youtube-automation/core";
import type { Result, ServiceError } from "@youtube-automation/core";
import type {
  PlaylistAssignOutput,
  PlaylistCleanDeletedOutput,
  PlaylistCreateOutput,
  PlaylistInitOutput,
  PlaylistStatusOutput,
  PlaylistSyncOutput,
} from "@youtube-automation/core/playlists";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const statusEntry = REGISTRY["playlists.status"];
const createEntry = REGISTRY["playlists.create"];
const assignEntry = REGISTRY["playlists.assign"];
const syncEntry = REGISTRY["playlists.sync"];
const cleanDeletedEntry = REGISTRY["playlists.cleanDeleted"];
const initEntry = REGISTRY["playlists.init"];

type PlaylistEntry =
  | typeof assignEntry
  | typeof cleanDeletedEntry
  | typeof createEntry
  | typeof initEntry
  | typeof statusEntry
  | typeof syncEntry;

type EntryOutput<E extends PlaylistEntry> =
  Awaited<ReturnType<E["run"]>> extends Result<infer O, ServiceError>
    ? O
    : never;

const runPlaylistEntry = async <E extends PlaylistEntry>(
  entry: E,
  rawInput: unknown
): Promise<Result<EntryOutput<E>, ServiceError>> => {
  try {
    const input = entry.inputSchema.parse(rawInput);
    const deps = await resolveDeps(entry.deps);
    return (await entry.run(input as never, deps as never)) as Result<
      EntryOutput<E>,
      ServiceError
    >;
  } catch (error) {
    return err(toServiceError(error));
  }
};

const emitPlaylistEntry = async <E extends PlaylistEntry>(
  entry: E,
  options: {
    json: boolean;
    rawInput: unknown;
    renderText: (value: EntryOutput<E>) => string;
  }
): Promise<void> => {
  const result = await runPlaylistEntry(entry, options.rawInput);
  emitResult(result, {
    json: options.json,
    renderText: options.renderText,
  });
};

export const renderStatusText = (output: PlaylistStatusOutput): string =>
  output.playlists
    .map((playlist) => {
      const playlistId = playlist.playlistId ?? "(missing)";
      const videoCount =
        playlist.videoCount === undefined
          ? ""
          : ` - ${playlist.videoCount} video(s)`;
      return `${playlist.key}: ${playlist.title} [${playlistId}]${videoCount}`;
    })
    .join("\n");

const renderCreateText = (
  output: PlaylistCreateOutput | PlaylistInitOutput
): string =>
  [
    ...output.created.map((playlist) => {
      const playlistId = playlist.playlistId ?? "(dry-run)";
      return `created: ${playlist.key} [${playlistId}]`;
    }),
    ...output.skipped.map((playlist) => {
      const playlistId = playlist.playlistId ?? "(missing)";
      return `skipped: ${playlist.key} [${playlistId}]`;
    }),
  ].join("\n");

const assignmentState = (
  playlist: PlaylistAssignOutput["assigned"][number]
): string => {
  if (playlist.alreadyPresent) {
    return "already-present";
  }
  if (playlist.inserted) {
    return "inserted";
  }
  return "dry-run";
};

const renderAssignText = (output: PlaylistAssignOutput): string =>
  output.assigned
    .map((playlist) => {
      const state = assignmentState(playlist);
      return `${state}: ${playlist.key}`;
    })
    .join("\n");

interface PlaylistAssignCliArgs {
  "dry-run": boolean;
  "video-id": string;
  json: boolean;
  theme: string;
}

export const playlistAssignRawInput = (args: PlaylistAssignCliArgs) => ({
  dryRun: args["dry-run"],
  theme: args.theme,
  videoId: args["video-id"],
});

const renderCleanDeletedText = (output: PlaylistCleanDeletedOutput): string =>
  output.cleaned
    .map(
      (playlist) =>
        `${playlist.key}: removed ${playlist.removedItems.length} item(s)`
    )
    .join("\n");

const renderSyncText = (output: PlaylistSyncOutput): string =>
  output.synced
    .map(
      (collection) =>
        `${collection.collectionName}: ${collection.assigned.length} playlist(s)`
    )
    .join("\n");

const renderInitText = (output: PlaylistInitOutput): string =>
  [renderCreateText(output), renderSyncText({ synced: output.synced })]
    .filter((line) => line.length > 0)
    .join("\n");

const statusCommand = defineCommand({
  args: {
    json: { default: false, description: "JSON で出力する", type: "boolean" },
  },
  meta: { description: statusEntry.description, name: "status" },
  async run({ args }) {
    await emitPlaylistEntry(statusEntry, {
      json: args.json,
      rawInput: {},
      renderText: renderStatusText,
    });
  },
});

const createCommand = defineCommand({
  args: {
    "dry-run": {
      default: false,
      description: "YouTube API へ書き込まず実行内容だけ表示する",
      type: "boolean",
    },
    json: { default: false, description: "JSON で出力する", type: "boolean" },
  },
  meta: { description: createEntry.description, name: "create" },
  async run({ args }) {
    await emitPlaylistEntry(createEntry, {
      json: args.json,
      rawInput: { dryRun: args["dry-run"] },
      renderText: renderCreateText,
    });
  },
});

const assignCommand = defineCommand({
  args: {
    "dry-run": {
      default: false,
      description: "YouTube API へ書き込まず実行内容だけ表示する",
      type: "boolean",
    },
    json: { default: false, description: "JSON で出力する", type: "boolean" },
    theme: {
      description: "collection theme slug",
      required: true,
      type: "string",
    },
    "video-id": {
      description: "追加する YouTube video id",
      required: true,
      type: "positional",
    },
  },
  meta: { description: assignEntry.description, name: "assign" },
  async run({ args }) {
    await emitPlaylistEntry(assignEntry, {
      json: args.json,
      rawInput: playlistAssignRawInput(args),
      renderText: renderAssignText,
    });
  },
});

const syncCommand = defineCommand({
  args: {
    "dry-run": {
      default: false,
      description: "YouTube API へ書き込まず実行内容だけ表示する",
      type: "boolean",
    },
    json: { default: false, description: "JSON で出力する", type: "boolean" },
  },
  meta: { description: syncEntry.description, name: "sync" },
  async run({ args }) {
    await emitPlaylistEntry(syncEntry, {
      json: args.json,
      rawInput: { dryRun: args["dry-run"] },
      renderText: renderSyncText,
    });
  },
});

const cleanDeletedCommand = defineCommand({
  args: {
    "dry-run": {
      default: false,
      description: "YouTube API へ書き込まず実行内容だけ表示する",
      type: "boolean",
    },
    json: { default: false, description: "JSON で出力する", type: "boolean" },
  },
  meta: { description: cleanDeletedEntry.description, name: "clean-deleted" },
  async run({ args }) {
    await emitPlaylistEntry(cleanDeletedEntry, {
      json: args.json,
      rawInput: { dryRun: args["dry-run"] },
      renderText: renderCleanDeletedText,
    });
  },
});

const initCommand = defineCommand({
  args: {
    "dry-run": {
      default: false,
      description: "YouTube API へ書き込まず実行内容だけ表示する",
      type: "boolean",
    },
    json: { default: false, description: "JSON で出力する", type: "boolean" },
  },
  meta: { description: initEntry.description, name: "init" },
  async run({ args }) {
    await emitPlaylistEntry(initEntry, {
      json: args.json,
      rawInput: { dryRun: args["dry-run"] },
      renderText: renderInitText,
    });
  },
});

export const playlistCommand = defineCommand({
  meta: {
    description: "YouTube playlist の作成・割り当て・整理",
    name: "playlist",
  },
  subCommands: {
    assign: assignCommand,
    "clean-deleted": cleanDeletedCommand,
    create: createCommand,
    init: initCommand,
    status: statusCommand,
    sync: syncCommand,
  },
});
