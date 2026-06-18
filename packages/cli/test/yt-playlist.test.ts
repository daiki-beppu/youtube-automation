import { describe, expect, spyOn, test } from "bun:test";
import { join, resolve } from "node:path";

import type { ChannelConfig } from "@youtube-automation/core/config";
import type { YouTubeClient } from "@youtube-automation/core/oauth/client";
import type { DepsMap } from "@youtube-automation/core/registry";
import { REGISTRY } from "@youtube-automation/core/registry";

import {
  createPlaylistCommand,
  playlistAssignRawInput,
  renderStatusText,
} from "../src/commands/playlist/cli.ts";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const taykBin = join(repoRoot, "packages", "cli", "bin", "tayk.ts");

const runTayk = (...argv: string[]) =>
  Bun.spawnSync(["bun", taykBin, ...argv], {
    cwd: repoRoot,
    env: process.env,
  });

interface TestCommand {
  args?: Record<string, unknown>;
  meta?: { description?: string; name?: string };
  run?: (context: unknown) => Promise<void> | void;
  subCommands?: Record<string, TestCommand>;
}

const playlistSubCommand = (name: string): TestCommand => {
  const command = createPlaylistCommand({
    resolveDeps: (deps) =>
      Promise.resolve({} as unknown as Pick<DepsMap, (typeof deps)[number]>),
  });
  const subCommands = command.subCommands as Record<string, TestCommand>;
  const subCommand = subCommands[name];
  if (subCommand === undefined) {
    throw new Error(`playlist ${name} command is required`);
  }
  return subCommand;
};

const createRecordingPlaylistCommand = () => {
  const resolvedDeps: (keyof DepsMap)[][] = [];
  const command = createPlaylistCommand({
    resolveDeps: (deps) => {
      resolvedDeps.push([...deps]);
      return Promise.resolve({
        channelDir: "/tmp/channel",
        config: {
          engagement: {
            playlists: {
              items: {
                all: {
                  auto_add: true,
                  playlist_id: "PL_ALL",
                  title: "All Videos",
                },
              },
            },
          },
          publishing: {
            content: {
              title: {
                defaultActivity: "Study",
                template: "{theme} - {activity}",
                themeActivities: {},
                themeScenes: {},
              },
            },
          },
        } as unknown as ChannelConfig,
      } as unknown as Pick<DepsMap, (typeof deps)[number]>);
    },
  }) as TestCommand;
  return { command, resolvedDeps };
};

const silenceCommandIo = () => {
  const stdoutSpy = spyOn(process.stdout, "write").mockReturnValue(true);
  const exitSpy = spyOn(process, "exit").mockImplementation((code) => {
    throw new Error(`unexpected exit ${String(code)}`);
  });
  return {
    restore: () => {
      stdoutSpy.mockRestore();
      exitSpy.mockRestore();
    },
  };
};

describe("core registry - playlist entries visible from cli package", () => {
  test("should expose the operation entries consumed by the CLI adapter", () => {
    expect(REGISTRY["playlists.status"].deps).toEqual(["config", "yt"]);
    expect(REGISTRY["playlists.create"].deps).toEqual([
      "config",
      "channelDir",
      "yt",
    ]);
    expect(REGISTRY["playlists.assign"].deps).toEqual(["config", "yt"]);
    expect(REGISTRY["playlists.sync"].deps).toEqual([
      "config",
      "channelDir",
      "yt",
    ]);
    expect(REGISTRY["playlists.cleanDeleted"].deps).toEqual(["config", "yt"]);
    expect(REGISTRY["playlists.init"].deps).toEqual([
      "config",
      "channelDir",
      "yt",
    ]);
  });
});

describe("tayk playlist - smoke", () => {
  test("should reach playlist help through the tayk dispatcher", () => {
    const proc = runTayk("playlist", "--help");

    expect(proc.exitCode).toBe(0);
    const stdout = proc.stdout.toString();
    expect(stdout).toContain("status");
    expect(stdout).toContain("create");
    expect(stdout).toContain("assign");
    expect(stdout).toContain("sync");
    expect(stdout).toContain("clean-deleted");
    expect(stdout).toContain("init");
  });

  test("should expose playlist operations from the command adapter", () => {
    const command = createPlaylistCommand() as TestCommand;

    expect(command.meta?.name).toBe("playlist");
    expect(Object.keys(command.subCommands ?? {}).toSorted()).toEqual([
      "assign",
      "clean-deleted",
      "create",
      "init",
      "status",
      "sync",
    ]);
  });

  test("should expose assign video id as positional and theme as required option", () => {
    const assign = playlistSubCommand("assign");

    expect(assign.args?.["video-id"]).toMatchObject({
      required: true,
      type: "positional",
    });
    expect(assign.args?.theme).toMatchObject({
      required: true,
      type: "string",
    });
  });

  test("should bind `playlist assign video_123 --theme focus --dry-run` input", () => {
    expect(
      playlistAssignRawInput({
        "dry-run": true,
        json: false,
        theme: "focus",
        "video-id": "video_123",
      })
    ).toEqual({
      dry_run: true,
      theme: "focus",
      video_id: "video_123",
    });
  });

  test("should run assign through subcommand schema, deps, registry, and stdout", async () => {
    const seenListCalls: unknown[] = [];
    const command = createPlaylistCommand({
      resolveDeps: (deps) =>
        Promise.resolve({
          config: {
            engagement: {
              playlists: {
                items: {
                  all: {
                    auto_add: true,
                    playlist_id: "PL_ALL",
                    title: "All Videos",
                  },
                },
              },
            },
            publishing: {
              content: {
                title: {
                  defaultActivity: "Study",
                  template: "{theme} - {activity}",
                  themeActivities: {},
                  themeScenes: {},
                },
              },
            },
          } as unknown as ChannelConfig,
          yt: {
            playlistItems: {
              list: (params: unknown) => {
                seenListCalls.push(params);
                return Promise.resolve({ data: { items: [] } });
              },
            },
          } as unknown as YouTubeClient,
        } as unknown as Pick<DepsMap, (typeof deps)[number]>),
    });
    const subCommands = command.subCommands as Record<string, TestCommand>;
    const { assign } = subCommands;
    if (assign === undefined) {
      throw new Error("playlist assign command is required");
    }
    const stdoutSpy = spyOn(process.stdout, "write").mockReturnValue(true);
    const exitSpy = spyOn(process, "exit").mockImplementation((code) => {
      throw new Error(`unexpected exit ${String(code)}`);
    });

    await assign.run?.({
      args: {
        "dry-run": true,
        json: false,
        theme: "focus",
        "video-id": "video_123",
      },
    });

    expect(seenListCalls).toEqual([]);
    expect(stdoutSpy).toHaveBeenCalledWith("dry-run: all\n");
    expect(exitSpy).not.toHaveBeenCalled();

    stdoutSpy.mockRestore();
    exitSpy.mockRestore();
  });

  test("should pass create dry-run through the registry execution path", async () => {
    const runSpy = spyOn(REGISTRY["playlists.create"], "run").mockResolvedValue(
      {
        ok: true,
        value: { created: [], skipped: [] },
      }
    );
    const io = silenceCommandIo();

    try {
      await playlistSubCommand("create").run?.({
        args: { "dry-run": true, json: false },
      });
      expect(runSpy.mock.calls[0]?.[0]).toEqual({ dryRun: true });
    } finally {
      io.restore();
      runSpy.mockRestore();
    }
  });

  test("should pass status through the registry execution path and stdout", async () => {
    const runSpy = spyOn(REGISTRY["playlists.status"], "run").mockResolvedValue(
      {
        ok: true,
        value: {
          playlists: [
            {
              dryRun: false,
              key: "all",
              playlistId: "PL_ALL",
              title: "All Videos",
              videoCount: 2,
            },
          ],
        },
      }
    );
    const stdoutSpy = spyOn(process.stdout, "write").mockReturnValue(true);
    const exitSpy = spyOn(process, "exit").mockImplementation((code) => {
      throw new Error(`unexpected exit ${String(code)}`);
    });

    try {
      await playlistSubCommand("status").run?.({
        args: { json: false },
      });
      expect(runSpy.mock.calls[0]?.[0]).toEqual({});
      expect(stdoutSpy).toHaveBeenCalledWith(
        "all: All Videos [PL_ALL] - 2 video(s)\n"
      );
      expect(exitSpy).not.toHaveBeenCalled();
    } finally {
      stdoutSpy.mockRestore();
      exitSpy.mockRestore();
      runSpy.mockRestore();
    }
  });

  test("should not resolve YouTube deps for create dry-run", async () => {
    const { command, resolvedDeps } = createRecordingPlaylistCommand();
    const create = command.subCommands?.create;
    const io = silenceCommandIo();

    try {
      await create?.run?.({ args: { "dry-run": true, json: false } });
    } finally {
      io.restore();
    }

    expect(resolvedDeps).toEqual([["config", "channelDir"]]);
  });

  test("should not resolve YouTube deps for assign dry-run", async () => {
    const { command, resolvedDeps } = createRecordingPlaylistCommand();
    const assign = command.subCommands?.assign;
    const io = silenceCommandIo();

    try {
      await assign?.run?.({
        args: {
          "dry-run": true,
          json: false,
          theme: "focus",
          "video-id": "video_123",
        },
      });
    } finally {
      io.restore();
    }

    expect(resolvedDeps).toEqual([["config"]]);
  });

  test("should pass sync dry-run through the registry execution path", async () => {
    const runSpy = spyOn(REGISTRY["playlists.sync"], "run").mockResolvedValue({
      ok: true,
      value: { synced: [] },
    });
    const io = silenceCommandIo();

    try {
      await playlistSubCommand("sync").run?.({
        args: { "dry-run": true, json: false },
      });
      expect(runSpy.mock.calls[0]?.[0]).toEqual({ dryRun: true });
    } finally {
      io.restore();
      runSpy.mockRestore();
    }
  });

  test("should not resolve YouTube deps for sync dry-run", async () => {
    const { command, resolvedDeps } = createRecordingPlaylistCommand();
    const sync = command.subCommands?.sync;
    const io = silenceCommandIo();

    try {
      await sync?.run?.({ args: { "dry-run": true, json: false } });
    } finally {
      io.restore();
    }

    expect(resolvedDeps).toEqual([["config", "channelDir"]]);
  });

  test("should pass clean-deleted dry-run through the registry execution path", async () => {
    const runSpy = spyOn(
      REGISTRY["playlists.cleanDeleted"],
      "run"
    ).mockResolvedValue({
      ok: true,
      value: { cleaned: [] },
    });
    const io = silenceCommandIo();

    try {
      await playlistSubCommand("clean-deleted").run?.({
        args: { "dry-run": true, json: false },
      });
      expect(runSpy.mock.calls[0]?.[0]).toEqual({ dryRun: true });
    } finally {
      io.restore();
      runSpy.mockRestore();
    }
  });

  test("should pass init dry-run through the registry execution path", async () => {
    const runSpy = spyOn(REGISTRY["playlists.init"], "run").mockResolvedValue({
      ok: true,
      value: { created: [], skipped: [], synced: [] },
    });
    const io = silenceCommandIo();

    try {
      await playlistSubCommand("init").run?.({
        args: { "dry-run": true, json: false },
      });
      expect(runSpy.mock.calls[0]?.[0]).toEqual({ dryRun: true });
    } finally {
      io.restore();
      runSpy.mockRestore();
    }
  });

  test("should not resolve YouTube deps for init dry-run", async () => {
    const { command, resolvedDeps } = createRecordingPlaylistCommand();
    const init = command.subCommands?.init;
    const io = silenceCommandIo();

    try {
      await init?.run?.({ args: { "dry-run": true, json: false } });
    } finally {
      io.restore();
    }

    expect(resolvedDeps).toEqual([["config", "channelDir"]]);
  });

  test("should render playlist status video counts in text output", () => {
    const output = renderStatusText({
      playlists: [
        {
          dryRun: false,
          key: "all",
          playlistId: "PL_ALL",
          title: "All Videos",
          videoCount: 2,
        },
      ],
    });

    expect(output).toBe("all: All Videos [PL_ALL] - 2 video(s)");
  });
});
