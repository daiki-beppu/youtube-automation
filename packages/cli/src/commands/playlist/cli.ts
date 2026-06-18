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
import type { DepsMap } from "@youtube-automation/core/registry";
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

interface PlaylistCommandDeps {
  resolveDeps: <D extends keyof DepsMap>(
    deps: readonly D[]
  ) => Promise<Pick<DepsMap, D>>;
}

const defaultDeps: PlaylistCommandDeps = {
  resolveDeps: (deps) => resolveDeps(deps),
};

const runStatus = async (
  rawInput: unknown,
  commandDeps: PlaylistCommandDeps
): Promise<Result<PlaylistStatusOutput, ServiceError>> => {
  try {
    const input = statusEntry.inputSchema.parse(rawInput);
    const deps = await commandDeps.resolveDeps(statusEntry.deps);
    return await statusEntry.run(input, deps);
  } catch (error) {
    return err(toServiceError(error));
  }
};

const runCreate = async (
  rawInput: unknown,
  commandDeps: PlaylistCommandDeps
): Promise<Result<PlaylistCreateOutput, ServiceError>> => {
  try {
    const input = createEntry.inputSchema.parse(rawInput);
    const deps = await commandDeps.resolveDeps(createEntry.deps);
    return await createEntry.run(input, deps);
  } catch (error) {
    return err(toServiceError(error));
  }
};

const runAssign = async (
  rawInput: unknown,
  commandDeps: PlaylistCommandDeps
): Promise<Result<PlaylistAssignOutput, ServiceError>> => {
  try {
    const input = assignEntry.inputSchema.parse(rawInput);
    const deps = await commandDeps.resolveDeps(assignEntry.deps);
    return await assignEntry.run(input, deps);
  } catch (error) {
    return err(toServiceError(error));
  }
};

const runSync = async (
  rawInput: unknown,
  commandDeps: PlaylistCommandDeps
): Promise<Result<PlaylistSyncOutput, ServiceError>> => {
  try {
    const input = syncEntry.inputSchema.parse(rawInput);
    const deps = await commandDeps.resolveDeps(syncEntry.deps);
    return await syncEntry.run(input, deps);
  } catch (error) {
    return err(toServiceError(error));
  }
};

const runCleanDeleted = async (
  rawInput: unknown,
  commandDeps: PlaylistCommandDeps
): Promise<Result<PlaylistCleanDeletedOutput, ServiceError>> => {
  try {
    const input = cleanDeletedEntry.inputSchema.parse(rawInput);
    const deps = await commandDeps.resolveDeps(cleanDeletedEntry.deps);
    return await cleanDeletedEntry.run(input, deps);
  } catch (error) {
    return err(toServiceError(error));
  }
};

const runInit = async (
  rawInput: unknown,
  commandDeps: PlaylistCommandDeps
): Promise<Result<PlaylistInitOutput, ServiceError>> => {
  try {
    const input = initEntry.inputSchema.parse(rawInput);
    const deps = await commandDeps.resolveDeps(initEntry.deps);
    return await initEntry.run(input, deps);
  } catch (error) {
    return err(toServiceError(error));
  }
};

const emitPlaylistResult = <T>(
  result: Result<T, ServiceError>,
  options: {
    json: boolean;
    renderText: (value: T) => string;
  }
): void => {
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
      if (playlist.persisted === false) {
        return `created-unpersisted: ${playlist.key} [${playlistId}]`;
      }
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
  dry_run: args["dry-run"],
  theme: args.theme,
  video_id: args["video-id"],
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

const statusCommand = (commandDeps: PlaylistCommandDeps) =>
  defineCommand({
    args: {
      json: { default: false, description: "JSON で出力する", type: "boolean" },
    },
    meta: { description: statusEntry.description, name: "status" },
    async run({ args }) {
      const result = await runStatus({}, commandDeps);
      emitPlaylistResult(result, {
        json: args.json,
        renderText: renderStatusText,
      });
    },
  });

const createCommand = (commandDeps: PlaylistCommandDeps) =>
  defineCommand({
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
      const result = await runCreate({ dry_run: args["dry-run"] }, commandDeps);
      emitPlaylistResult(result, {
        json: args.json,
        renderText: renderCreateText,
      });
    },
  });

const assignCommand = (commandDeps: PlaylistCommandDeps) =>
  defineCommand({
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
      const result = await runAssign(playlistAssignRawInput(args), commandDeps);
      emitPlaylistResult(result, {
        json: args.json,
        renderText: renderAssignText,
      });
    },
  });

const syncCommand = (commandDeps: PlaylistCommandDeps) =>
  defineCommand({
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
      const result = await runSync({ dry_run: args["dry-run"] }, commandDeps);
      emitPlaylistResult(result, {
        json: args.json,
        renderText: renderSyncText,
      });
    },
  });

const cleanDeletedCommand = (commandDeps: PlaylistCommandDeps) =>
  defineCommand({
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
      const result = await runCleanDeleted(
        { dry_run: args["dry-run"] },
        commandDeps
      );
      emitPlaylistResult(result, {
        json: args.json,
        renderText: renderCleanDeletedText,
      });
    },
  });

const initCommand = (commandDeps: PlaylistCommandDeps) =>
  defineCommand({
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
      const result = await runInit({ dry_run: args["dry-run"] }, commandDeps);
      emitPlaylistResult(result, {
        json: args.json,
        renderText: renderInitText,
      });
    },
  });

export const createPlaylistCommand = (deps?: PlaylistCommandDeps) => {
  const commandDeps = deps ?? defaultDeps;
  return defineCommand({
    meta: {
      description: "YouTube playlist の作成・割り当て・整理",
      name: "playlist",
    },
    subCommands: {
      assign: assignCommand(commandDeps),
      "clean-deleted": cleanDeletedCommand(commandDeps),
      create: createCommand(commandDeps),
      init: initCommand(commandDeps),
      status: statusCommand(commandDeps),
      sync: syncCommand(commandDeps),
    },
  });
};

export const playlistCommand = createPlaylistCommand();
