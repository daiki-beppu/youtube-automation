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

const runTaykWithoutChannelDir = (...argv: string[]) => {
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([key]) => key !== "CHANNEL_DIR")
  ) as Record<string, string>;
  return Bun.spawnSync(["bun", taykBin, ...argv], {
    cwd: repoRoot,
    env,
  });
};

const runTaykWithChannelDir = (channelDir: string, ...argv: string[]) =>
  Bun.spawnSync(["bun", taykBin, ...argv], {
    cwd: repoRoot,
    env: { ...process.env, CHANNEL_DIR: channelDir },
  });

interface TestCommand {
  run?: (context: unknown) => Promise<void> | void;
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
  test("should list playlist in dispatcher help", () => {
    const proc = runTayk("--help");

    expect(proc.exitCode).toBe(0);
    expect(proc.stdout.toString()).toContain("playlist");
  });

  test("should list playlist operations in subcommand help", () => {
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

  test("should expose assign video id as positional and theme as required option", () => {
    const proc = runTayk("playlist", "assign", "--help");

    expect(proc.exitCode).toBe(0);
    const stdout = proc.stdout.toString();
    expect(stdout).toContain(
      "USAGE playlist assign [OPTIONS] --theme=<theme> <VIDEO-ID>"
    );
    expect(stdout).toContain("--theme");
    expect(stdout).not.toContain("<THEME> <VIDEO-ID>");
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

  test("should reject assign when the video id positional is missing", () => {
    const proc = runTayk("playlist", "assign", "--theme", "focus");

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toContain(
      "Missing required positional argument: VIDEO-ID"
    );
  });

  test("should reject assign when the theme option is missing", () => {
    const proc = runTayk("playlist", "assign", "video_123");

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toContain(
      "Missing required argument: --theme"
    );
  });

  test("should reach dependency resolution for valid assign input", () => {
    const proc = runTaykWithChannelDir(
      "/tmp/nonexistent",
      "playlist",
      "assign",
      "video_123",
      "--theme",
      "focus",
      "--dry-run"
    );

    expect(proc.exitCode).toBe(1);
    expect(proc.stderr.toString()).toContain("[config]");
    expect(proc.stderr.toString()).toContain("/tmp/nonexistent/config/channel");
    expect(proc.stderr.toString()).not.toContain("Missing required");
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

  test("should report missing CHANNEL_DIR through the real status command", () => {
    const proc = runTaykWithoutChannelDir("playlist", "status");

    expect(proc.exitCode).toBe(1);
    expect(proc.stdout.toString()).toBe("");
    expect(proc.stderr.toString()).toContain("[config]");
    expect(proc.stderr.toString()).toContain("CHANNEL_DIR");
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
