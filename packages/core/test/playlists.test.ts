import { afterEach, describe, expect, spyOn, test } from "bun:test";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { ChannelConfig } from "@youtube-automation/core/config";
import type { YouTubeClient } from "@youtube-automation/core/oauth/client";
import { REGISTRY } from "@youtube-automation/core/registry";

interface PlaylistCoreDeps {
  config: ChannelConfig;
  yt: YouTubeClient;
}

interface PlaylistChannelDeps extends PlaylistCoreDeps {
  channelDir: string;
}

interface InsertCall {
  part?: string;
  requestBody?: {
    snippet?: {
      description?: string;
      playlistId?: string;
      position?: number;
      resourceId?: { kind?: string; videoId?: string };
      title?: string;
    };
    status?: { privacyStatus?: string };
  };
}

interface ListCall {
  maxResults?: number;
  pageToken?: string;
  part?: string;
  playlistId?: string;
}

interface DeleteCall {
  id?: string;
}

interface ListPage {
  items: unknown[];
  nextPageToken?: string;
}

const tmpDirs: string[] = [];

const makeTempChannel = (playlistsJson: unknown): string => {
  const channelDir = mkdtempSync(join(tmpdir(), "playlist-channel-"));
  tmpDirs.push(channelDir);
  mkdirSync(join(channelDir, "config", "channel"), { recursive: true });
  writeFileSync(
    join(channelDir, "config", "channel", "playlists.json"),
    JSON.stringify(playlistsJson, null, 2),
    "utf-8"
  );
  return channelDir;
};

const writeLiveCollection = (
  channelDir: string,
  name: string,
  workflow: unknown,
  tracking: unknown
): void => {
  const collectionDir = join(channelDir, "collections", "live", name);
  mkdirSync(join(collectionDir, "20-documentation"), { recursive: true });
  writeFileSync(
    join(collectionDir, "workflow-state.json"),
    JSON.stringify(workflow, null, 2),
    "utf-8"
  );
  writeFileSync(
    join(collectionDir, "20-documentation", "upload_tracking.json"),
    JSON.stringify(tracking, null, 2),
    "utf-8"
  );
};

const makeLiveCollectionDir = (channelDir: string, name: string): string => {
  const collectionDir = join(channelDir, "collections", "live", name);
  mkdirSync(collectionDir, { recursive: true });
  return collectionDir;
};

const writeLiveWorkflow = (
  channelDir: string,
  name: string,
  workflow: unknown
): void => {
  const collectionDir = makeLiveCollectionDir(channelDir, name);
  writeFileSync(
    join(collectionDir, "workflow-state.json"),
    JSON.stringify(workflow, null, 2),
    "utf-8"
  );
};

const writeInvalidLiveFile = (
  channelDir: string,
  name: string,
  relativePath: string,
  content: string
): void => {
  const collectionDir = makeLiveCollectionDir(channelDir, name);
  writeFileSync(join(collectionDir, relativePath), content, "utf-8");
};

afterEach(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

const makeConfig = (
  playlists: Record<string, Record<string, unknown>>
): ChannelConfig =>
  ({
    engagement: { playlists: { items: playlists } },
    publishing: {
      content: {
        title: {
          defaultActivity: "Study",
          template: "{theme} - {activity}",
          themeActivities: {},
          themeScenes: {
            focus: { activities: "Deep Work · Writing" },
            ocean: { activities: "Relaxing" },
          },
        },
      },
    },
  }) as unknown as ChannelConfig;

const makeYouTube = (options?: {
  deleteError?: unknown;
  insertItemError?: unknown;
  listError?: unknown;
  listPages?: Record<string, Record<string, ListPage>>;
  listResponses?: Record<string, unknown[]>;
  playlistInsertError?: unknown;
  playlistId?: string;
}) => {
  const playlistInsertCalls: InsertCall[] = [];
  const playlistItemInsertCalls: InsertCall[] = [];
  const playlistItemListCalls: ListCall[] = [];
  const playlistItemDeleteCalls: DeleteCall[] = [];
  const listResponses = options?.listResponses ?? {};

  const yt = {
    playlistItems: {
      delete: (params: DeleteCall) => {
        playlistItemDeleteCalls.push(params);
        if (options?.deleteError !== undefined) {
          return Promise.reject(options.deleteError);
        }
        return Promise.resolve({ data: {} });
      },
      insert: (params: InsertCall) => {
        playlistItemInsertCalls.push(params);
        if (options?.insertItemError !== undefined) {
          return Promise.reject(options.insertItemError);
        }
        return Promise.resolve({ data: { id: "PLI_new" } });
      },
      list: (params: ListCall) => {
        playlistItemListCalls.push(params);
        if (options?.listError !== undefined) {
          return Promise.reject(options.listError);
        }
        const pages = options?.listPages?.[params.playlistId ?? ""];
        if (pages !== undefined) {
          const page = pages[params.pageToken ?? ""];
          return Promise.resolve({
            data: {
              items: page?.items ?? [],
              nextPageToken: page?.nextPageToken,
            },
          });
        }
        const items = listResponses[params.playlistId ?? ""] ?? [];
        return Promise.resolve({ data: { items } });
      },
    },
    playlists: {
      insert: (params: InsertCall) => {
        playlistInsertCalls.push(params);
        if (options?.playlistInsertError !== undefined) {
          return Promise.reject(options.playlistInsertError);
        }
        return Promise.resolve({
          data: { id: options?.playlistId ?? "PL_NEW" },
        });
      },
    },
  };

  return {
    playlistInsertCalls,
    playlistItemDeleteCalls,
    playlistItemInsertCalls,
    playlistItemListCalls,
    yt: yt as unknown as YouTubeClient,
  };
};

const makeCoreDeps = (
  config: ChannelConfig,
  yt: YouTubeClient
): PlaylistCoreDeps => ({ config, yt });

const makeChannelDeps = (
  channelDir: string,
  config: ChannelConfig,
  yt: YouTubeClient
): PlaylistChannelDeps => ({ channelDir, config, yt });

const gaxiosError = (
  status: number,
  reason: string,
  retryAfter?: string
): Error & {
  response: {
    data: { error: { errors: { reason: string }[] } };
    headers?: Record<string, string>;
    status: number;
  };
} =>
  Object.assign(new Error(`HTTP ${status}`), {
    response: {
      data: { error: { errors: [{ reason }] } },
      headers:
        retryAfter === undefined ? undefined : { "retry-after": retryAfter },
      status,
    },
  });

describe("playlists registry entries", () => {
  test("exposes operation-level dotted entries with YouTube deps", () => {
    const expectedDeps = [
      ["playlists.assign", ["config", "yt"]],
      ["playlists.cleanDeleted", ["config", "yt"]],
      ["playlists.create", ["config", "channelDir", "yt"]],
      ["playlists.init", ["config", "channelDir", "yt"]],
      ["playlists.status", ["config", "yt"]],
      ["playlists.sync", ["config", "channelDir", "yt"]],
    ] as const;

    for (const [key, deps] of expectedDeps) {
      const entry = REGISTRY[key];
      expect(entry.description.length).toBeGreaterThan(0);
      expect(entry.deps).toEqual(deps);
      expect(entry.deps).not.toContain("ytAnalytics");
    }
  });

  test("declares dry-run deps in the core registry contract", () => {
    expect(
      REGISTRY["playlists.assign"].depsForInput?.({
        dryRun: true,
        theme: "focus",
        videoId: "video_123",
      })
    ).toEqual(["config"]);
    expect(
      REGISTRY["playlists.assign"].depsForInput?.({
        dryRun: false,
        theme: "focus",
        videoId: "video_123",
      })
    ).toEqual(["config", "yt"]);
    expect(
      REGISTRY["playlists.create"].depsForInput?.({ dryRun: true })
    ).toEqual(["config", "channelDir"]);
    expect(
      REGISTRY["playlists.create"].depsForInput?.({ dryRun: false })
    ).toEqual(["config", "channelDir", "yt"]);
    expect(REGISTRY["playlists.sync"].depsForInput?.({ dryRun: true })).toEqual(
      ["config", "channelDir"]
    );
    expect(REGISTRY["playlists.init"].depsForInput?.({ dryRun: true })).toEqual(
      ["config", "channelDir"]
    );
  });
});

describe("playlists schemas", () => {
  test("normalizes snake_case assign input before the service boundary", () => {
    const input = REGISTRY["playlists.assign"].inputSchema.parse({
      dry_run: true,
      theme: "focus",
      video_id: "video_123",
    });

    expect(input).toEqual({
      dryRun: true,
      theme: "focus",
      videoId: "video_123",
    });
  });

  test("rejects camelCase inputs at the registry boundary", () => {
    const cases = [
      ["playlists.create", { dryRun: true }],
      [
        "playlists.assign",
        { dryRun: true, theme: "focus", videoId: "video_123" },
      ],
      ["playlists.cleanDeleted", { dryRun: true }],
      ["playlists.sync", { dryRun: true }],
      ["playlists.init", { dryRun: true }],
    ] as const;

    for (const [key, input] of cases) {
      expect(() => REGISTRY[key].inputSchema.parse(input)).toThrow();
    }
  });

  test("normalizes snake_case clean-deleted input before the service boundary", () => {
    const input = REGISTRY["playlists.cleanDeleted"].inputSchema.parse({
      dry_run: true,
    });

    expect(input).toEqual({ dryRun: true });
  });

  test("normalizes snake_case sync input before the service boundary", () => {
    const input = REGISTRY["playlists.sync"].inputSchema.parse({
      dry_run: true,
    });

    expect(input).toEqual({ dryRun: true });
  });

  test("requires dry_run for mutating operations at the registry boundary", () => {
    const cases = [
      ["playlists.create", {}],
      ["playlists.assign", { theme: "focus", video_id: "video_123" }],
      ["playlists.cleanDeleted", {}],
      ["playlists.sync", {}],
      ["playlists.init", {}],
    ] as const;

    for (const [key, input] of cases) {
      expect(() => REGISTRY[key].inputSchema.parse(input)).toThrow();
    }
  });
});

describe("playlists.create", () => {
  test("treats empty playlist_id as missing and creates a playlist", async () => {
    const channelDir = makeTempChannel({
      playlists: { focus: { playlist_id: "", title: "Focus Sessions" } },
    });
    const config = makeConfig({
      focus: { playlist_id: "", title: "Focus Sessions" },
    });
    const { playlistInsertCalls, yt } = makeYouTube({ playlistId: "PL_FOCUS" });

    const result = await REGISTRY["playlists.create"].run(
      REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(playlistInsertCalls).toHaveLength(1);
    expect(result.value.created).toEqual([
      {
        dryRun: false,
        key: "focus",
        playlistId: "PL_FOCUS",
        title: "Focus Sessions",
      },
    ]);
    expect(result.value.skipped).toEqual([]);
  });

  test("creates only entries missing playlist_id and writes the new id back", async () => {
    const channelDir = makeTempChannel({
      playlists: {
        all: { playlist_id: "PL_ALL", title: "All Videos" },
        focus: { title: "Focus Sessions" },
      },
    });
    const config = makeConfig({
      all: { playlist_id: "PL_ALL", title: "All Videos" },
      focus: { title: "Focus Sessions" },
    });
    const { playlistInsertCalls, yt } = makeYouTube({ playlistId: "PL_FOCUS" });

    const result = await REGISTRY["playlists.create"].run(
      REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(playlistInsertCalls).toHaveLength(1);
    expect(playlistInsertCalls[0]?.requestBody).toEqual({
      snippet: {
        description: "",
        title: "Focus Sessions",
      },
      status: { privacyStatus: "public" },
    });
    expect(result.value.created).toEqual([
      {
        dryRun: false,
        key: "focus",
        playlistId: "PL_FOCUS",
        title: "Focus Sessions",
      },
    ]);

    const written = JSON.parse(
      readFileSync(
        join(channelDir, "config", "channel", "playlists.json"),
        "utf-8"
      )
    ) as { playlists: Record<string, { playlist_id?: string }> };
    expect(written.playlists.all?.playlist_id).toBe("PL_ALL");
    expect(written.playlists.focus?.playlist_id).toBe("PL_FOCUS");
  });

  test("preserves existing playlists config when atomic temp write fails", async () => {
    const channelDir = makeTempChannel({
      playlists: {
        focus: { title: "Focus Sessions" },
      },
    });
    const configPath = join(channelDir, "config", "channel", "playlists.json");
    const originalConfig = readFileSync(configPath, "utf-8");
    const nowSpy = spyOn(Date, "now").mockReturnValue(123_456);
    mkdirSync(
      join(
        channelDir,
        "config",
        "channel",
        `.playlists.json.${process.pid}.123456.tmp`
      )
    );
    const config = makeConfig({
      focus: { title: "Focus Sessions" },
    });
    const { playlistInsertCalls, yt } = makeYouTube({ playlistId: "PL_FOCUS" });

    try {
      const result = await REGISTRY["playlists.create"].run(
        REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
        makeChannelDeps(channelDir, config, yt)
      );

      expect(result.ok).toBe(false);
      if (result.ok) {
        throw new Error("expected io error");
      }
      expect(result.error.domain).toBe("io");
      expect(playlistInsertCalls).toHaveLength(1);
      expect(readFileSync(configPath, "utf-8")).toBe(originalConfig);
    } finally {
      nowSpy.mockRestore();
    }
  });

  test("rejects create targets without a non-empty title before calling playlists.insert", async () => {
    const cases = [
      { key: "missing", playlist: {} },
      { key: "blank", playlist: { title: " " } },
    ] as const;

    for (const { key, playlist } of cases) {
      const channelDir = makeTempChannel({
        playlists: { [key]: playlist },
      });
      const config = makeConfig({
        [key]: playlist,
      });
      const { playlistInsertCalls, yt } = makeYouTube({
        playlistId: `PL_${key.toUpperCase()}`,
      });

      const result = await REGISTRY["playlists.create"].run(
        REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
        makeChannelDeps(channelDir, config, yt)
      );

      expect(result.ok).toBe(false);
      if (result.ok) {
        throw new Error("expected config error");
      }
      expect(result.error).toEqual({
        domain: "config",
        message: `config: playlists.${key}.title is required`,
      });
      expect(playlistInsertCalls).toHaveLength(0);
    }
  });

  test("validates every create target before creating or writing any playlist", async () => {
    const playlists = Object.fromEntries([
      ["valid", { title: "Valid Sessions" }],
      ["missing", {}],
    ]);
    const channelDir = makeTempChannel({
      playlists,
    });
    const config = makeConfig(playlists);
    const { playlistInsertCalls, yt } = makeYouTube({
      playlistId: "PL_VALID",
    });

    const result = await REGISTRY["playlists.create"].run(
      REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected config error");
    }
    expect(result.error).toEqual({
      domain: "config",
      message: "config: playlists.missing.title is required",
    });
    expect(playlistInsertCalls).toHaveLength(0);

    const written = JSON.parse(
      readFileSync(
        join(channelDir, "config", "channel", "playlists.json"),
        "utf-8"
      )
    ) as { playlists: Record<string, { playlist_id?: string }> };
    expect(written.playlists.valid?.playlist_id).toBeUndefined();
    expect(written.playlists.missing?.playlist_id).toBeUndefined();
  });

  test("maps malformed playlists.insert response to api service error", async () => {
    const channelDir = makeTempChannel({
      playlists: { focus: { title: "Focus Sessions" } },
    });
    const config = makeConfig({
      focus: { title: "Focus Sessions" },
    });
    const { yt } = makeYouTube({ playlistId: "" });

    const result = await REGISTRY["playlists.create"].run(
      REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected api error");
    }
    expect(result.error.domain).toBe("api");
    if (result.error.domain !== "api") {
      throw new Error(`expected api, got ${result.error.domain}`);
    }
    expect(result.error.httpStatus).toBe(500);
  });

  test("maps playlists.insert failures to api service error", async () => {
    const channelDir = makeTempChannel({
      playlists: { focus: { title: "Focus Sessions" } },
    });
    const config = makeConfig({
      focus: { title: "Focus Sessions" },
    });
    const { playlistInsertCalls, yt } = makeYouTube({
      playlistInsertError: gaxiosError(403, "forbidden"),
    });

    const result = await REGISTRY["playlists.create"].run(
      REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected api error");
    }
    expect(playlistInsertCalls).toHaveLength(1);
    expect(result.error.domain).toBe("api");
    if (result.error.domain !== "api") {
      throw new Error(`expected api, got ${result.error.domain}`);
    }
    expect(result.error.httpStatus).toBe(403);
    expect(result.error.reason).toBe("forbidden");
    expect(result.error.message).toBe("playlists.insert: HTTP 403");
  });

  test("returns config error when local config persistence fails", async () => {
    const channelDir = makeTempChannel({
      playlists: {},
    });
    const config = makeConfig({
      focus: { title: "Focus Sessions" },
    });
    const { playlistInsertCalls, yt } = makeYouTube({
      playlistId: "PL_CREATED",
    });

    const result = await REGISTRY["playlists.create"].run(
      REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected config error");
    }
    expect(playlistInsertCalls).toHaveLength(1);
    expect(result.error).toEqual({
      domain: "config",
      message: "config: playlists.focus must be object or string",
    });

    const written = JSON.parse(
      readFileSync(
        join(channelDir, "config", "channel", "playlists.json"),
        "utf-8"
      )
    ) as { playlists: Record<string, { playlist_id?: string }> };
    expect(written.playlists.focus?.playlist_id).toBeUndefined();
  });

  test("stops creating more playlists when local config persistence fails", async () => {
    const channelDir = makeTempChannel({
      playlists: {
        sleep: { title: "Sleep Sessions" },
      },
    });
    const config = makeConfig({
      focus: { title: "Focus Sessions" },
      sleep: { title: "Sleep Sessions" },
    });
    const { playlistInsertCalls, yt } = makeYouTube({
      playlistId: "PL_CREATED",
    });

    const result = await REGISTRY["playlists.create"].run(
      REGISTRY["playlists.create"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected config error");
    }
    expect(playlistInsertCalls).toHaveLength(1);
    expect(result.error.domain).toBe("config");

    const written = JSON.parse(
      readFileSync(
        join(channelDir, "config", "channel", "playlists.json"),
        "utf-8"
      )
    ) as { playlists: Record<string, { playlist_id?: string }> };
    expect(written.playlists.focus?.playlist_id).toBeUndefined();
    expect(written.playlists.sleep?.playlist_id).toBeUndefined();
  });
});

describe("playlists.assign", () => {
  test("does not call playlistItems with an empty configured playlist_id", async () => {
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "", title: "All Videos" },
    });
    const { playlistItemInsertCalls, playlistItemListCalls, yt } = makeYouTube({
      listResponses: { "": [] },
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "focus",
        video_id: "video_123",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.assigned).toEqual([]);
    expect(playlistItemListCalls).toHaveLength(0);
    expect(playlistItemInsertCalls).toHaveLength(0);
  });

  test("adds a video to auto and activity-matched playlists without duplicating existing items", async () => {
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
      focus: {
        auto_add_activities: ["Deep Work"],
        playlist_id: "PL_FOCUS",
        title: "Focus Sessions",
      },
      ocean: {
        auto_add_themes: ["ocean"],
        playlist_id: "PL_OCEAN",
        title: "Ocean",
      },
    });
    const { playlistItemInsertCalls, yt } = makeYouTube({
      listResponses: {
        PL_ALL: [],
        PL_FOCUS: [{ contentDetails: { videoId: "video_123" } }],
        PL_OCEAN: [],
      },
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "focus",
        video_id: "video_123",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    expect(playlistItemInsertCalls).toHaveLength(1);
    expect(playlistItemInsertCalls[0]?.requestBody?.snippet).toEqual({
      playlistId: "PL_ALL",
      resourceId: { kind: "youtube#video", videoId: "video_123" },
    });
  });

  test("uses paginated playlist items when checking existing videos", async () => {
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemInsertCalls, playlistItemListCalls, yt } = makeYouTube({
      listPages: {
        PL_ALL: {
          "": {
            items: [{ contentDetails: { videoId: "video_first_page" } }],
            nextPageToken: "page-2",
          },
          "page-2": {
            items: [{ contentDetails: { videoId: "video_123" } }],
          },
        },
      },
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "focus",
        video_id: "video_123",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.assigned).toEqual([
      {
        alreadyPresent: true,
        dryRun: false,
        inserted: false,
        key: "all",
        playlistId: "PL_ALL",
        title: "All Videos",
      },
    ]);
    expect(playlistItemListCalls).toEqual([
      {
        maxResults: 50,
        pageToken: undefined,
        part: "snippet,contentDetails",
        playlistId: "PL_ALL",
      },
      {
        maxResults: 50,
        pageToken: "page-2",
        part: "snippet,contentDetails",
        playlistId: "PL_ALL",
      },
    ]);
    expect(playlistItemInsertCalls).toHaveLength(0);
  });

  test("dry-run reports matched playlists without inserting playlist items", async () => {
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemInsertCalls, playlistItemListCalls, yt } = makeYouTube({
      listResponses: { PL_ALL: [] },
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: true,
        theme: "focus",
        video_id: "video_123",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.assigned).toEqual([
      {
        alreadyPresent: false,
        dryRun: true,
        inserted: false,
        key: "all",
        playlistId: "PL_ALL",
        title: "All Videos",
      },
    ]);
    expect(playlistItemListCalls).toHaveLength(0);
    expect(playlistItemInsertCalls).toHaveLength(0);
  });

  test("dry-run skips matched playlists without playlist_id", async () => {
    const config = makeConfig({
      all: { auto_add: true, title: "All Videos" },
    });
    const { playlistItemInsertCalls, playlistItemListCalls, yt } =
      makeYouTube();

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: true,
        theme: "focus",
        video_id: "video_123",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.assigned).toEqual([]);
    expect(playlistItemListCalls).toHaveLength(0);
    expect(playlistItemInsertCalls).toHaveLength(0);
  });

  test("inserts non-all playlist matches at the head", async () => {
    const config = makeConfig({
      focus: {
        auto_add_activities: ["Deep Work"],
        playlist_id: "PL_FOCUS",
        title: "Focus Sessions",
      },
    });
    const { playlistItemInsertCalls, yt } = makeYouTube({
      listResponses: { PL_FOCUS: [] },
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "focus",
        video_id: "video_456",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    expect(playlistItemInsertCalls[0]?.requestBody?.snippet).toEqual({
      playlistId: "PL_FOCUS",
      position: 0,
      resourceId: { kind: "youtube#video", videoId: "video_456" },
    });
  });

  test("matches auto_add_themes by case-insensitive substring", async () => {
    const config = makeConfig({
      relaxation: {
        auto_add_themes: ["ocean", "forest"],
        playlist_id: "PL_RELAX",
        title: "Relaxation",
      },
    });
    const { playlistItemInsertCalls, yt } = makeYouTube({
      listResponses: { PL_RELAX: [] },
    });

    const ocean = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "Deep Ocean Waves",
        video_id: "video_ocean",
      }),
      makeCoreDeps(config, yt)
    );
    const forest = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "FOREST Ambience",
        video_id: "video_forest",
      }),
      makeCoreDeps(config, yt)
    );

    expect(ocean.ok).toBe(true);
    expect(forest.ok).toBe(true);
    expect(
      playlistItemInsertCalls.map((call) => call.requestBody?.snippet)
    ).toEqual([
      {
        playlistId: "PL_RELAX",
        position: 0,
        resourceId: { kind: "youtube#video", videoId: "video_ocean" },
      },
      {
        playlistId: "PL_RELAX",
        position: 0,
        resourceId: { kind: "youtube#video", videoId: "video_forest" },
      },
    ]);
  });

  test("maps playlist item 429 failures to quota service error", async () => {
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { yt } = makeYouTube({
      listError: gaxiosError(429, "rateLimitExceeded", "30"),
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "focus",
        video_id: "video_429",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected quota error");
    }
    expect(result.error).toEqual({
      domain: "quota",
      httpStatus: 429,
      message: "playlistItems.list: HTTP 429",
      retryAfterSeconds: 30,
    });
  });

  test("maps non-quota YouTube API failures to api service error", async () => {
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { yt } = makeYouTube({
      listError: gaxiosError(403, "forbidden"),
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "focus",
        video_id: "video_403",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected api error");
    }
    expect(result.error.domain).toBe("api");
    if (result.error.domain !== "api") {
      throw new Error(`expected api, got ${result.error.domain}`);
    }
    expect(result.error.httpStatus).toBe(403);
    expect(result.error.reason).toBe("forbidden");
  });

  test("maps playlistItems.insert failures to api service error", async () => {
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemInsertCalls, yt } = makeYouTube({
      insertItemError: gaxiosError(403, "forbidden"),
      listResponses: { PL_ALL: [] },
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "focus",
        video_id: "video_403",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected api error");
    }
    expect(playlistItemInsertCalls).toHaveLength(1);
    expect(result.error.domain).toBe("api");
    if (result.error.domain !== "api") {
      throw new Error(`expected api, got ${result.error.domain}`);
    }
    expect(result.error.httpStatus).toBe(403);
    expect(result.error.reason).toBe("forbidden");
    expect(result.error.message).toBe("playlistItems.insert: HTTP 403");
  });

  test("stops assigning after the first playlistItems.insert failure", async () => {
    const config = makeConfig({
      first: { auto_add: true, playlist_id: "PL_FIRST", title: "First" },
      second: { auto_add: true, playlist_id: "PL_SECOND", title: "Second" },
    });
    const { playlistItemInsertCalls, playlistItemListCalls, yt } = makeYouTube({
      insertItemError: gaxiosError(403, "forbidden"),
      listResponses: { PL_FIRST: [], PL_SECOND: [] },
    });

    const result = await REGISTRY["playlists.assign"].run(
      REGISTRY["playlists.assign"].inputSchema.parse({
        dry_run: false,
        theme: "focus",
        video_id: "video_403",
      }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(false);
    expect(playlistItemListCalls).toEqual([
      {
        maxResults: 50,
        pageToken: undefined,
        part: "snippet,contentDetails",
        playlistId: "PL_FIRST",
      },
    ]);
    expect(playlistItemInsertCalls).toHaveLength(1);
  });
});

describe("playlists.sync", () => {
  test("assigns every uploaded live collection from workflow and tracking files", async () => {
    const channelDir = makeTempChannel({ playlists: {} });
    writeLiveCollection(
      channelDir,
      "20260617-focus",
      { planning: { activities: "Gaming" }, theme: "unknown-theme" },
      { complete_collection: { video_id: "video_live" } }
    );
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
      battle: {
        auto_add_activities: ["Gaming"],
        playlist_id: "PL_BATTLE",
        title: "Battle",
      },
    });
    const { playlistItemInsertCalls, yt } = makeYouTube({
      listResponses: { PL_ALL: [], PL_BATTLE: [] },
    });

    const result = await REGISTRY["playlists.sync"].run(
      REGISTRY["playlists.sync"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.synced).toEqual([
      {
        assigned: [
          {
            alreadyPresent: false,
            dryRun: false,
            inserted: true,
            key: "all",
            playlistId: "PL_ALL",
            title: "All Videos",
          },
          {
            alreadyPresent: false,
            dryRun: false,
            inserted: true,
            key: "battle",
            playlistId: "PL_BATTLE",
            title: "Battle",
          },
        ],
        collectionName: "20260617-focus",
        theme: "unknown-theme",
        videoId: "video_live",
      },
    ]);
    expect(playlistItemInsertCalls).toHaveLength(2);
  });

  test("skips incomplete live collections and continues syncing valid collections", async () => {
    const channelDir = makeTempChannel({ playlists: {} });
    makeLiveCollectionDir(channelDir, "missing-workflow");
    writeLiveCollection(
      channelDir,
      "missing-theme",
      { planning: { activities: "Gaming" } },
      { complete_collection: { video_id: "video_missing_theme" } }
    );
    writeLiveWorkflow(channelDir, "missing-tracking", {
      planning: { activities: "Gaming" },
      theme: "missing-tracking-theme",
    });
    writeLiveCollection(
      channelDir,
      "missing-video-id",
      { planning: { activities: "Gaming" }, theme: "missing-video-theme" },
      { complete_collection: {} }
    );
    writeLiveCollection(
      channelDir,
      "valid",
      { planning: { activities: "Gaming" }, theme: "valid-theme" },
      { complete_collection: { video_id: "video_valid" } }
    );
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
      battle: {
        auto_add_activities: ["Gaming"],
        playlist_id: "PL_BATTLE",
        title: "Battle",
      },
    });
    const { playlistItemInsertCalls, yt } = makeYouTube({
      listResponses: { PL_ALL: [], PL_BATTLE: [] },
    });

    const result = await REGISTRY["playlists.sync"].run(
      REGISTRY["playlists.sync"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(
      result.value.synced.map((collection) => collection.collectionName)
    ).toEqual(["valid"]);
    expect(result.value.synced[0]?.videoId).toBe("video_valid");
    expect(playlistItemInsertCalls).toHaveLength(2);
  });

  test("stops on malformed workflow-state.json before inserting playlist items", async () => {
    const channelDir = makeTempChannel({ playlists: {} });
    writeInvalidLiveFile(
      channelDir,
      "bad-workflow",
      "workflow-state.json",
      "{"
    );
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemInsertCalls, playlistItemListCalls, yt } = makeYouTube({
      listResponses: { PL_ALL: [] },
    });

    const result = await REGISTRY["playlists.sync"].run(
      REGISTRY["playlists.sync"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected io error");
    }
    expect(result.error.domain).toBe("io");
    expect(playlistItemListCalls).toHaveLength(0);
    expect(playlistItemInsertCalls).toHaveLength(0);
  });

  test("stops on malformed upload_tracking.json before inserting playlist items", async () => {
    const channelDir = makeTempChannel({ playlists: {} });
    const collectionDir = makeLiveCollectionDir(channelDir, "bad-tracking");
    mkdirSync(join(collectionDir, "20-documentation"), { recursive: true });
    writeFileSync(
      join(collectionDir, "workflow-state.json"),
      JSON.stringify({ theme: "focus" }, null, 2),
      "utf-8"
    );
    writeFileSync(
      join(collectionDir, "20-documentation", "upload_tracking.json"),
      "{",
      "utf-8"
    );
    const config = makeConfig({
      all: { auto_add: true, playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemInsertCalls, playlistItemListCalls, yt } = makeYouTube({
      listResponses: { PL_ALL: [] },
    });

    const result = await REGISTRY["playlists.sync"].run(
      REGISTRY["playlists.sync"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected io error");
    }
    expect(result.error.domain).toBe("io");
    expect(playlistItemListCalls).toHaveLength(0);
    expect(playlistItemInsertCalls).toHaveLength(0);
  });
});

describe("playlists.init", () => {
  test("writes created playlist id and uses it for same-run sync inserts", async () => {
    const channelDir = makeTempChannel({
      playlists: {
        focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
      },
    });
    writeLiveCollection(
      channelDir,
      "20260617-focus",
      { theme: "focus" },
      { complete_collection: { video_id: "video_live" } }
    );
    const config = makeConfig({
      focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
    });
    const { playlistItemInsertCalls, yt } = makeYouTube({
      listResponses: { PL_FOCUS: [] },
      playlistId: "PL_FOCUS",
    });

    const result = await REGISTRY["playlists.init"].run(
      REGISTRY["playlists.init"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.created).toEqual([
      {
        dryRun: false,
        key: "focus",
        playlistId: "PL_FOCUS",
        title: "Focus Sessions",
      },
    ]);
    expect(playlistItemInsertCalls).toHaveLength(1);
    expect(playlistItemInsertCalls[0]?.requestBody?.snippet).toEqual({
      playlistId: "PL_FOCUS",
      position: 0,
      resourceId: { kind: "youtube#video", videoId: "video_live" },
    });

    const written = JSON.parse(
      readFileSync(
        join(channelDir, "config", "channel", "playlists.json"),
        "utf-8"
      )
    ) as { playlists: Record<string, { playlist_id?: string }> };
    expect(written.playlists.focus?.playlist_id).toBe("PL_FOCUS");
  });

  test("returns config error and does not sync when persistence fails", async () => {
    const channelDir = makeTempChannel({
      playlists: {},
    });
    writeLiveCollection(
      channelDir,
      "20260617-focus",
      { theme: "focus" },
      { complete_collection: { video_id: "video_live" } }
    );
    const config = makeConfig({
      focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
    });
    const { playlistItemInsertCalls, playlistItemListCalls, yt } = makeYouTube({
      listResponses: { PL_FOCUS: [] },
      playlistId: "PL_FOCUS",
    });

    const result = await REGISTRY["playlists.init"].run(
      REGISTRY["playlists.init"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected config error");
    }
    expect(result.error).toEqual({
      domain: "config",
      message: "config: playlists.focus must be object or string",
    });
    expect(playlistItemListCalls).toHaveLength(0);
    expect(playlistItemInsertCalls).toHaveLength(0);
  });

  test("returns api error and preserves written playlist id when sync fails after create", async () => {
    const channelDir = makeTempChannel({
      playlists: {
        focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
      },
    });
    writeLiveCollection(
      channelDir,
      "20260617-focus",
      { theme: "focus" },
      { complete_collection: { video_id: "video_live" } }
    );
    const config = makeConfig({
      focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
    });
    const { playlistInsertCalls, playlistItemListCalls, yt } = makeYouTube({
      listError: gaxiosError(403, "forbidden"),
      playlistId: "PL_FOCUS",
    });

    const result = await REGISTRY["playlists.init"].run(
      REGISTRY["playlists.init"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected api error");
    }
    expect(playlistInsertCalls).toHaveLength(1);
    expect(playlistItemListCalls).toEqual([
      {
        maxResults: 50,
        pageToken: undefined,
        part: "snippet,contentDetails",
        playlistId: "PL_FOCUS",
      },
    ]);
    expect(result.error.domain).toBe("api");
    if (result.error.domain !== "api") {
      throw new Error(`expected api, got ${result.error.domain}`);
    }
    expect(result.error.httpStatus).toBe(403);
    expect(result.error.reason).toBe("forbidden");
    expect(result.error.message).toBe("playlistItems.list: HTTP 403");

    const written = JSON.parse(
      readFileSync(
        join(channelDir, "config", "channel", "playlists.json"),
        "utf-8"
      )
    ) as { playlists: Record<string, { playlist_id?: string }> };
    expect(written.playlists.focus?.playlist_id).toBe("PL_FOCUS");

    const retryConfig = makeConfig({
      focus: {
        auto_add_activities: ["Deep Work"],
        playlist_id: "PL_FOCUS",
        title: "Focus Sessions",
      },
    });
    const {
      playlistInsertCalls: retryPlaylistInsertCalls,
      playlistItemInsertCalls: retryPlaylistItemInsertCalls,
      yt: retryYt,
    } = makeYouTube({
      listResponses: { PL_FOCUS: [] },
      playlistId: "PL_DUPLICATE",
    });

    const retryResult = await REGISTRY["playlists.init"].run(
      REGISTRY["playlists.init"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, retryConfig, retryYt)
    );

    expect(retryResult.ok).toBe(true);
    if (!retryResult.ok) {
      throw new Error(`expected retry ok, got ${retryResult.error.domain}`);
    }
    expect(retryPlaylistInsertCalls).toHaveLength(0);
    expect(retryPlaylistItemInsertCalls[0]?.requestBody?.snippet).toEqual({
      playlistId: "PL_FOCUS",
      position: 0,
      resourceId: { kind: "youtube#video", videoId: "video_live" },
    });
  });

  test("dry-run does not write created playlist ids or insert synced videos", async () => {
    const channelDir = makeTempChannel({
      playlists: {
        focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
      },
    });
    writeLiveCollection(
      channelDir,
      "20260617-focus",
      { theme: "focus" },
      { complete_collection: { video_id: "video_live" } }
    );
    const config = makeConfig({
      focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
    });
    const { playlistItemInsertCalls, playlistInsertCalls, yt } = makeYouTube({
      playlistId: "PL_FOCUS",
    });

    const result = await REGISTRY["playlists.init"].run(
      REGISTRY["playlists.init"].inputSchema.parse({ dry_run: true }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.synced).toEqual([
      {
        assigned: [],
        collectionName: "20260617-focus",
        theme: "focus",
        videoId: "video_live",
      },
    ]);
    expect(playlistInsertCalls).toHaveLength(0);
    expect(playlistItemInsertCalls).toHaveLength(0);

    const written = JSON.parse(
      readFileSync(
        join(channelDir, "config", "channel", "playlists.json"),
        "utf-8"
      )
    ) as { playlists: Record<string, { playlist_id?: string }> };
    expect(written.playlists.focus?.playlist_id).toBeUndefined();
  });

  test("stops on malformed workflow-state.json after persisting created playlist id", async () => {
    const channelDir = makeTempChannel({
      playlists: {
        focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
      },
    });
    writeInvalidLiveFile(
      channelDir,
      "bad-workflow",
      "workflow-state.json",
      "{"
    );
    const config = makeConfig({
      focus: { auto_add_activities: ["Deep Work"], title: "Focus Sessions" },
    });
    const {
      playlistInsertCalls,
      playlistItemInsertCalls,
      playlistItemListCalls,
      yt,
    } = makeYouTube({
      playlistId: "PL_FOCUS",
    });

    const result = await REGISTRY["playlists.init"].run(
      REGISTRY["playlists.init"].inputSchema.parse({ dry_run: false }),
      makeChannelDeps(channelDir, config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected io error");
    }
    expect(result.error.domain).toBe("io");
    expect(playlistInsertCalls).toHaveLength(1);
    expect(playlistItemListCalls).toHaveLength(0);
    expect(playlistItemInsertCalls).toHaveLength(0);

    const written = JSON.parse(
      readFileSync(
        join(channelDir, "config", "channel", "playlists.json"),
        "utf-8"
      )
    ) as { playlists: Record<string, { playlist_id?: string }> };
    expect(written.playlists.focus?.playlist_id).toBe("PL_FOCUS");
  });
});

describe("playlists.cleanDeleted", () => {
  test("removes Deleted video and Private video playlist items but leaves normal items", async () => {
    const config = makeConfig({
      all: { playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemDeleteCalls, yt } = makeYouTube({
      listResponses: {
        PL_ALL: [
          { id: "item_deleted", snippet: { title: "Deleted video" } },
          { id: "item_private", snippet: { title: "Private video" } },
          { id: "item_live", snippet: { title: "A normal video" } },
        ],
      },
    });

    const result = await REGISTRY["playlists.cleanDeleted"].run(
      REGISTRY["playlists.cleanDeleted"].inputSchema.parse({ dry_run: false }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    expect(playlistItemDeleteCalls).toEqual([
      { id: "item_deleted" },
      { id: "item_private" },
    ]);
  });

  test("dry-run reports removable playlist items without deleting them", async () => {
    const config = makeConfig({
      all: { playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemDeleteCalls, yt } = makeYouTube({
      listResponses: {
        PL_ALL: [
          { id: "item_deleted", snippet: { title: "Deleted video" } },
          { id: "item_live", snippet: { title: "A normal video" } },
        ],
      },
    });

    const result = await REGISTRY["playlists.cleanDeleted"].run(
      REGISTRY["playlists.cleanDeleted"].inputSchema.parse({ dry_run: true }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.cleaned).toEqual([
      {
        dryRun: true,
        key: "all",
        playlistId: "PL_ALL",
        removedItems: [{ itemId: "item_deleted", title: "Deleted video" }],
        title: "All Videos",
      },
    ]);
    expect(playlistItemDeleteCalls).toHaveLength(0);
  });

  test("maps playlistItems.delete failures to api service error", async () => {
    const config = makeConfig({
      all: { playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemDeleteCalls, yt } = makeYouTube({
      deleteError: gaxiosError(403, "forbidden"),
      listResponses: {
        PL_ALL: [
          { id: "item_deleted", snippet: { title: "Deleted video" } },
          { id: "item_private", snippet: { title: "Private video" } },
        ],
      },
    });

    const result = await REGISTRY["playlists.cleanDeleted"].run(
      REGISTRY["playlists.cleanDeleted"].inputSchema.parse({ dry_run: false }),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected api error");
    }
    expect(playlistItemDeleteCalls).toEqual([{ id: "item_deleted" }]);
    expect(result.error.domain).toBe("api");
    if (result.error.domain !== "api") {
      throw new Error(`expected api, got ${result.error.domain}`);
    }
    expect(result.error.httpStatus).toBe(403);
    expect(result.error.reason).toBe("forbidden");
    expect(result.error.message).toBe("playlistItems.delete: HTTP 403");
  });
});

describe("playlists.status", () => {
  test("treats empty playlist_id as missing and does not call playlistItems.list", async () => {
    const config = makeConfig({
      all: { playlist_id: "", title: "All Videos" },
    });
    const { playlistItemListCalls, yt } = makeYouTube({
      listResponses: { "": [] },
    });

    const result = await REGISTRY["playlists.status"].run(
      REGISTRY["playlists.status"].inputSchema.parse({}),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.playlists).toEqual([
      {
        dryRun: false,
        key: "all",
        title: "All Videos",
      },
    ]);
    expect(playlistItemListCalls).toHaveLength(0);
  });

  test("includes video counts for playlists with playlist_id", async () => {
    const config = makeConfig({
      all: { playlist_id: "PL_ALL", title: "All Videos" },
      missing: { title: "Missing Playlist" },
    });
    const { playlistItemListCalls, yt } = makeYouTube({
      listPages: {
        PL_ALL: {
          "": {
            items: [{ contentDetails: { videoId: "video_1" } }],
            nextPageToken: "page-2",
          },
          "page-2": {
            items: [{ contentDetails: { videoId: "video_2" } }],
          },
        },
      },
    });

    const result = await REGISTRY["playlists.status"].run(
      REGISTRY["playlists.status"].inputSchema.parse({}),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expect(result.value.playlists).toEqual([
      {
        dryRun: false,
        key: "all",
        playlistId: "PL_ALL",
        title: "All Videos",
        videoCount: 2,
      },
      {
        dryRun: false,
        key: "missing",
        title: "Missing Playlist",
      },
    ]);
    expect(playlistItemListCalls).toEqual([
      {
        maxResults: 50,
        pageToken: undefined,
        part: "snippet,contentDetails",
        playlistId: "PL_ALL",
      },
      {
        maxResults: 50,
        pageToken: "page-2",
        part: "snippet,contentDetails",
        playlistId: "PL_ALL",
      },
    ]);
  });

  test("maps playlistItems.list failures to api service error", async () => {
    const config = makeConfig({
      all: { playlist_id: "PL_ALL", title: "All Videos" },
    });
    const { playlistItemListCalls, yt } = makeYouTube({
      listError: gaxiosError(403, "forbidden"),
    });

    const result = await REGISTRY["playlists.status"].run(
      REGISTRY["playlists.status"].inputSchema.parse({}),
      makeCoreDeps(config, yt)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected api error");
    }
    expect(playlistItemListCalls).toEqual([
      {
        maxResults: 50,
        pageToken: undefined,
        part: "snippet,contentDetails",
        playlistId: "PL_ALL",
      },
    ]);
    expect(result.error.domain).toBe("api");
    if (result.error.domain !== "api") {
      throw new Error(`expected api, got ${result.error.domain}`);
    }
    expect(result.error.httpStatus).toBe(403);
    expect(result.error.reason).toBe("forbidden");
    expect(result.error.message).toBe("playlistItems.list: HTTP 403");
  });
});
