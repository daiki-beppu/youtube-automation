import { describe, expect, test } from "bun:test";
import { join, resolve } from "node:path";

import { REGISTRY } from "@youtube-automation/core/registry";

import {
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
      dryRun: true,
      theme: "focus",
      videoId: "video_123",
    });
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
