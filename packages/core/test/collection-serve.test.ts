import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  chmodSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import * as collectionServePublicApi from "@youtube-automation/core/collection-serve";
import {
  collectionServeService,
  CollectionServeInputSchema,
  CollectionServeOutputSchema,
} from "@youtube-automation/core/collection-serve";
import type { ChannelConfig } from "@youtube-automation/core/config";
import { REGISTRY } from "@youtube-automation/core/registry";

import {
  COLLECTIONS_ROUTE,
  collectionPromptsRoute,
  DISTROKID_ASSETS_PREFIX,
  DEFAULT_URL,
  DISTROKID_COLLECTIONS_ROUTE,
  DISTROKID_RELEASE_ROUTE,
  DISTROKID_RELEASES_ROUTE,
  distrokidReleaseRoute,
  PHASE,
  PLAYLISTS_CAPTURE_ROUTE,
  PROMPTS_ROUTE,
  STORAGE_KEY,
  VERSION_ROUTE,
} from "../../../extensions/shared/constants.ts";

interface CapturedServeOptions {
  readonly fetch: (request: Request) => Promise<Response> | Response;
  readonly hostname?: string;
  readonly port?: number;
}

interface CollectionServeOutput {
  readonly distrokidEnabled: boolean;
  readonly mode: "dir" | "single";
  readonly playlistCaptureEnabled: boolean;
  readonly routes: readonly string[];
  readonly url: string;
}

interface CollectionServeInput {
  readonly allowOrigin?: string;
  readonly distrokidStateRoot?: string;
  readonly path: string;
  readonly playlistCapturePrefix?: string;
  readonly playlistCaptureRoot?: string;
  readonly port: number;
}

type CollectionServeResult =
  | { ok: true; value: CollectionServeOutput }
  | { error: { message: string }; ok: false };
interface CollectionSummary {
  has_prompts: boolean;
  id: string;
  mapped: boolean;
  name: string;
  pattern_count: number | null;
  playlist_name: string | null;
}

const tmpDirs: string[] = [];
const originalServe = Bun.serve;

const fakeConfig = (distrokidEnabled: boolean): ChannelConfig =>
  ({
    integrations: {
      distrokid: {
        enabled: distrokidEnabled,
        profile: {
          appleMusicCredit: "",
          artistName: "",
          language: "",
          mainGenre: "",
          songwriter: "",
          trackType: "",
        },
      },
    },
  }) as unknown as ChannelConfig;

const makeTempDir = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const realDir = realpathSync(dir);
  tmpDirs.push(realDir);
  return realDir;
};

const writeCollection = (
  root: string,
  id: string,
  entries: unknown[] | null
): string => {
  const collectionDir = join(root, id);
  const docsDir = join(collectionDir, "20-documentation");
  mkdirSync(docsDir, { recursive: true });
  if (entries !== null) {
    writeFileSync(
      join(docsDir, "suno-prompts.json"),
      JSON.stringify(entries),
      "utf-8"
    );
  }
  return collectionDir;
};

const writeDistrokidDisc = (
  collectionDir: string,
  disc: string,
  albumTitle: string
): void => {
  const distrokidDir = join(collectionDir, "30-distrokid");
  const discDir = join(distrokidDir, disc);
  mkdirSync(discDir, { recursive: true });
  writeFileSync(join(discDir, "track-01.mp3"), "fake-mp3", "utf-8");
  writeFileSync(join(distrokidDir, "cover_art_3000.jpg"), "fake-jpg", "utf-8");
  writeFileSync(
    join(discDir, "metadata.md"),
    [
      "## アルバム情報",
      "",
      "| 項目 | 値 |",
      "|---|---|",
      `| アルバムタイトル | ${albumTitle} |`,
    ].join("\n"),
    "utf-8"
  );
};

const writeDistrokidMetadataWithTracks = (
  collectionDir: string,
  disc: string,
  albumTitle: string,
  tracks: readonly { readonly filename: string; readonly title: string }[]
): void => {
  writeFileSync(
    join(collectionDir, "30-distrokid", disc, "metadata.md"),
    [
      "## アルバム情報",
      "",
      "| 項目 | 値 |",
      "|---|---|",
      `| アルバムタイトル | ${albumTitle} |`,
      "",
      `## トラックリスト (1-${tracks.length})`,
      "",
      "| # | タイトル | ファイル | 尺 | ISRC (任意) | 作詞 | 作曲 |",
      "|---|---------|---------|----|------------|------|------|",
      ...tracks.map(
        (track, index) =>
          `| ${index + 1} | ${track.title} | \`${track.filename}\` | 3:18 |  |  |  |`
      ),
    ].join("\n"),
    "utf-8"
  );
};

const jsonRequest = (url: string, body: unknown): Request =>
  new Request(url, {
    body: JSON.stringify(body),
    headers: {
      "content-type": "application/json",
      origin: "https://suno.com",
    },
    method: "POST",
  });

const jsonRequestWithOrigin = (
  url: string,
  body: unknown,
  origin?: string
): Request => {
  const headers = new Headers({ "content-type": "application/json" });
  if (origin !== undefined) {
    headers.set("origin", origin);
  }
  return new Request(url, {
    body: JSON.stringify(body),
    headers,
    method: "POST",
  });
};

afterEach(() => {
  Bun.serve = originalServe;
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

describe("collection-serve public API — exports map", () => {
  test("should expose only service boundary runtime symbols", () => {
    expect(Object.keys(collectionServePublicApi).toSorted()).toEqual([
      "CollectionServeInputSchema",
      "CollectionServeOutputSchema",
      "collectionServeService",
    ]);
  });
});

describe("CollectionServeInputSchema — contract", () => {
  test("should transform snake_case adapter input to camelCase service input", () => {
    const raw = {
      allow_origin: "https://suno.com",
      distrokid_source: "30-distrokid/disc1-test-album",
      path: "/tmp/channel/collections/planning",
      playlist_capture_prefix: "clm",
      playlist_capture_root: "/tmp/channel",
      port: 7874,
    };

    const parsed = CollectionServeInputSchema.parse(raw);

    expect(parsed).toEqual({
      allowOrigin: "https://suno.com",
      distrokidSource: "30-distrokid/disc1-test-album",
      path: "/tmp/channel/collections/planning",
      playlistCapturePrefix: "clm",
      playlistCaptureRoot: "/tmp/channel",
      port: 7874,
    });
  });

  test("should accept DistroKid state root without Suno playlist capture options", () => {
    const parsed = CollectionServeInputSchema.parse({
      distrokid_state_root: "/tmp/channel",
      path: "/tmp/channel/collections/planning",
    });

    expect(parsed).toEqual({
      distrokidStateRoot: "/tmp/channel",
      path: "/tmp/channel/collections/planning",
      port: 7873,
    });
  });

  test("should default to the shared localhost port when port is omitted", () => {
    const parsed = CollectionServeInputSchema.parse({
      path: "/tmp/channel/collections/planning",
    });

    expect(parsed).toEqual({
      path: "/tmp/channel/collections/planning",
      port: 7873,
    });
  });

  test("should reject playlist capture options unless root and prefix are paired", () => {
    expect(() =>
      CollectionServeInputSchema.parse({
        path: "/tmp/channel/collections/planning",
        playlist_capture_root: "/tmp/channel",
      })
    ).toThrow();
    expect(() =>
      CollectionServeInputSchema.parse({
        path: "/tmp/channel/collections/planning",
        playlist_capture_prefix: "clm",
      })
    ).toThrow();
  });

  test("should reject unknown keys so adapters cannot smuggle deps through input", () => {
    expect(() =>
      CollectionServeInputSchema.parse({
        config: {},
        path: "/tmp/channel/collections/planning",
      })
    ).toThrow();
  });
});

describe("collection.serve registry entry — contract", () => {
  test("should require config from adapters and expose serializable output schema", () => {
    const entry = REGISTRY["collection.serve"];

    expect(entry.deps).toEqual(["config"]);
    expect(entry.description.length).toBeGreaterThan(0);
    expect(entry.inputSchema).toBe(CollectionServeInputSchema);
    expect(entry.outputSchema).toBe(CollectionServeOutputSchema);
    expect(
      CollectionServeOutputSchema.parse({
        distrokidEnabled: false,
        mode: "dir",
        playlistCaptureEnabled: true,
        routes: [COLLECTIONS_ROUTE, PLAYLISTS_CAPTURE_ROUTE],
        url: "http://localhost:7873",
      })
    ).toEqual({
      distrokidEnabled: false,
      mode: "dir",
      playlistCaptureEnabled: true,
      routes: [COLLECTIONS_ROUTE, PLAYLISTS_CAPTURE_ROUTE],
      url: "http://localhost:7873",
    });
  });
});

describe("collection-serve shared extension constants — contract", () => {
  test("should use the Suno helper and DistroKid helper contract values from one TS source", () => {
    expect(DEFAULT_URL).toBe("http://localhost:7873");
    expect(STORAGE_KEY).toBe("sunoServerUrl");
    expect(PROMPTS_ROUTE).toBe("/suno/prompts.json");
    expect(COLLECTIONS_ROUTE).toBe("/collections");
    expect(PLAYLISTS_CAPTURE_ROUTE).toBe("/suno/playlists");
    expect(VERSION_ROUTE).toBe("/version");
    expect(DISTROKID_COLLECTIONS_ROUTE).toBe("/distrokid/collections");
    expect(DISTROKID_RELEASE_ROUTE).toBe("/distrokid/release.json");
    expect(DISTROKID_ASSETS_PREFIX).toBe("/distrokid/assets/");
    expect(DISTROKID_RELEASES_ROUTE).toBe("/distrokid/releases");
    expect(collectionPromptsRoute("20260601-clm-aaa-collection")).toBe(
      "/collections/20260601-clm-aaa-collection/suno/prompts.json"
    );
    expect(
      distrokidReleaseRoute(
        "20260601-clm-aaa-collection",
        "disc1-coding-focus-vol1"
      )
    ).toBe(
      "/collections/20260601-clm-aaa-collection/distrokid/disc1-coding-focus-vol1/release.json"
    );
    expect(PHASE.ADDING_TO_PLAYLIST).toBe("adding-to-playlist");
  });

  test("should expose the Python package version through the compatibility route", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const pyproject = readFileSync(
      join(import.meta.dir, "..", "..", "..", "pyproject.toml"),
      "utf-8"
    );
    const version = /^version = "([^"]+)"$/mu.exec(pyproject)?.[1];
    if (version === undefined) {
      throw new Error("pyproject version was not found");
    }
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7878"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        path: planning,
        port: 7878,
      }) as CollectionServeInput,
      { config: fakeConfig(false) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    const response = await handler(
      new Request(`http://localhost:7878${VERSION_ROUTE}`)
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      min_extension_version: "0.1.0",
      version,
    });
  });

  test("should serve single-mode prompts route from the collection directory", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const entries = [{ lyrics: "", name: "A — A", style: "slow, jazz" }];
    const collectionDir = writeCollection(
      planning,
      "20260601-clm-single-collection",
      entries
    );
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7878"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        path: collectionDir,
        port: 7878,
      }) as CollectionServeInput,
      { config: fakeConfig(false) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.mode).toBe("single");
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }

    const response = await handler(
      new Request(`http://localhost:7878${PROMPTS_ROUTE}`)
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(entries);
  });

  test("should serve single-mode prompts route from a direct suno-prompts.json path", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const entries = [{ lyrics: "", name: "A — A", style: "slow, jazz" }];
    const collectionDir = writeCollection(
      planning,
      "20260601-clm-single-collection",
      entries
    );
    const promptsPath = join(
      collectionDir,
      "20-documentation",
      "suno-prompts.json"
    );
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7880"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        path: promptsPath,
        port: 7880,
      }) as CollectionServeInput,
      { config: fakeConfig(false) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    const response = await handler(
      new Request(`http://localhost:7880${PROMPTS_ROUTE}`)
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(entries);
  });

  test("should expose DistroKid dir-mode routes used by the helper extension", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const stateRoot = makeTempDir("collection-serve-state-");
    const collectionId = "20260601-clm-distrokid-collection";
    const collectionDir = writeCollection(planning, collectionId, []);
    writeDistrokidDisc(collectionDir, "disc1-test-album", "Test Album");
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7879"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        distrokid_state_root: stateRoot,
        path: planning,
        port: 7879,
      }) as CollectionServeInput,
      { config: fakeConfig(true) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }

    const preflight = await handler(
      new Request(`http://localhost:7879${DISTROKID_RELEASES_ROUTE}`, {
        headers: {
          "access-control-request-headers": "content-type",
          "access-control-request-method": "POST",
          origin: "https://distrokid.com",
        },
        method: "OPTIONS",
      })
    );
    expect(preflight.status).toBe(204);
    expect(preflight.headers.get("access-control-allow-methods")).toBe(
      "GET, POST, OPTIONS"
    );
    expect(preflight.headers.get("access-control-allow-headers")).toBe(
      "Content-Type"
    );

    const indexResponse = await handler(
      new Request(`http://localhost:7879${DISTROKID_COLLECTIONS_ROUTE}`)
    );
    expect(indexResponse.status).toBe(200);
    expect(await indexResponse.json()).toEqual([
      {
        album_title: "Test Album",
        collection_id: collectionId,
        disc: "disc1-test-album",
        name: "distrokid-collection",
        released: false,
        track_count: 1,
      },
    ]);

    const releaseResponse = await handler(
      new Request(
        `http://localhost:7879${distrokidReleaseRoute(collectionId, "disc1-test-album")}`
      )
    );
    expect(releaseResponse.status).toBe(200);
    const release = (await releaseResponse.json()) as {
      release: { album_title: string; tracks: { asset_path: string }[] };
    };
    expect(release.release.album_title).toBe("Test Album");
    expect(release.release.tracks[0]?.asset_path).toBe(
      `${COLLECTIONS_ROUTE}/${collectionId}/distrokid/assets/30-distrokid/disc1-test-album/track-01.mp3`
    );

    const assetResponse = await handler(
      new Request(
        `http://localhost:7879${COLLECTIONS_ROUTE}/${collectionId}/distrokid/assets/30-distrokid/disc1-test-album/track-01.mp3`
      )
    );
    expect(assetResponse.status).toBe(200);
    expect(await assetResponse.text()).toBe("fake-mp3");

    const noOriginReleaseResponse = await handler(
      jsonRequestWithOrigin(
        `http://localhost:7879${DISTROKID_RELEASES_ROUTE}`,
        {
          album_title: "Test Album",
          collection_id: collectionId,
          disc: "disc1-test-album",
        }
      )
    );
    expect(noOriginReleaseResponse.status).toBe(403);

    const disallowedOriginReleaseResponse = await handler(
      jsonRequestWithOrigin(
        `http://localhost:7879${DISTROKID_RELEASES_ROUTE}`,
        {
          album_title: "Test Album",
          collection_id: collectionId,
          disc: "disc1-test-album",
        },
        "https://evil.com"
      )
    );
    expect(disallowedOriginReleaseResponse.status).toBe(403);

    const postResponse = await handler(
      jsonRequest(`http://localhost:7879${DISTROKID_RELEASES_ROUTE}`, {
        album_title: "Test Album",
        collection_id: collectionId,
        disc: "disc1-test-album",
      })
    );
    expect(postResponse.status).toBe(200);
    expect(await postResponse.json()).toMatchObject({ recorded: true });

    const updatedIndexResponse = await handler(
      new Request(`http://localhost:7879${DISTROKID_COLLECTIONS_ROUTE}`)
    );
    const updatedIndex = (await updatedIndexResponse.json()) as {
      released: boolean;
    }[];
    expect(updatedIndex[0]?.released).toBe(true);
  });

  test("should use metadata title for DistroKid index when spec.json is corrupt", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const collectionId = "20260601-clm-distrokid-collection";
    const collectionDir = writeCollection(planning, collectionId, []);
    writeDistrokidDisc(collectionDir, "disc1-test-album", "Metadata Album");
    writeFileSync(
      join(collectionDir, "30-distrokid", "spec.json"),
      "{not json",
      "utf-8"
    );
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7883"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        path: planning,
        port: 7883,
      }) as CollectionServeInput,
      { config: fakeConfig(true) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    const response = await handler(
      new Request(`http://localhost:7883${DISTROKID_COLLECTIONS_ROUTE}`)
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([
      {
        album_title: "Metadata Album",
        collection_id: collectionId,
        disc: "disc1-test-album",
        name: "distrokid-collection",
        released: false,
        track_count: 1,
      },
    ]);
  });

  test("should return CORS JSON 500 for corrupt single-mode DistroKid spec", async () => {
    const collectionDir = writeCollection(
      makeTempDir("collection-serve-single-"),
      "20260601-clm-distrokid-collection",
      []
    );
    writeDistrokidDisc(collectionDir, "disc1-test-album", "Metadata Album");
    writeFileSync(
      join(collectionDir, "30-distrokid", "spec.json"),
      "{not json",
      "utf-8"
    );
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7884"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        distrokid_source: "30-distrokid/disc1-test-album",
        path: collectionDir,
        port: 7884,
      }) as CollectionServeInput,
      { config: fakeConfig(true) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    const response = await handler(
      new Request(`http://localhost:7884${DISTROKID_RELEASE_ROUTE}`, {
        headers: { origin: "https://distrokid.com" },
      })
    );

    expect(response.status).toBe(500);
    expect(response.headers.get("access-control-allow-origin")).toBe(
      "https://distrokid.com"
    );
    const body = (await response.json()) as { error?: string };
    expect(body.error).toContain("JSON");
  });

  test("should return CORS JSON 500 for corrupt dir-mode DistroKid spec", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const collectionId = "20260601-clm-distrokid-collection";
    const collectionDir = writeCollection(planning, collectionId, []);
    writeDistrokidDisc(collectionDir, "disc1-test-album", "Metadata Album");
    writeFileSync(
      join(collectionDir, "30-distrokid", "spec.json"),
      "{not json",
      "utf-8"
    );
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7885"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        path: planning,
        port: 7885,
      }) as CollectionServeInput,
      { config: fakeConfig(true) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    const response = await handler(
      new Request(
        `http://localhost:7885${COLLECTIONS_ROUTE}/${collectionId}/distrokid/disc1-test-album/release.json`,
        { headers: { origin: "chrome-extension://abcdef" } }
      )
    );

    expect(response.status).toBe(500);
    expect(response.headers.get("access-control-allow-origin")).toBe(
      "chrome-extension://abcdef"
    );
    const body = (await response.json()) as { error?: string };
    expect(body.error).toContain("JSON");
  });
});

describe("collectionServeService — Bun.serve HTTP contract", () => {
  test("should start Bun.serve and serve dir-mode collection routes", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const entries = [{ lyrics: "", name: "A — A", style: "slow, jazz" }];
    writeCollection(planning, "20260601-clm-aaa-collection", entries);
    writeCollection(planning, "20260602-clm-bbb-collection", null);
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL(
          `http://${options.hostname ?? "localhost"}:${options.port ?? 7873}`
        ),
      };
    }) as unknown as typeof Bun.serve;

    const input = CollectionServeInputSchema.parse({
      path: planning,
      port: 7874,
    }) as CollectionServeInput;
    const result = (await collectionServeService(input, {
      config: fakeConfig(false),
    })) as CollectionServeResult;

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value).toMatchObject({
      distrokidEnabled: false,
      mode: "dir",
      playlistCaptureEnabled: false,
      url: "http://localhost:7874",
    });
    expect(result.value.routes).toContain(COLLECTIONS_ROUTE);
    expect(result.value.routes).not.toContain(DISTROKID_COLLECTIONS_ROUTE);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }

    const collectionsResponse = await handler(
      new Request(`http://localhost:7874${COLLECTIONS_ROUTE}`, {
        headers: { origin: "chrome-extension://abcdef" },
      })
    );
    expect(collectionsResponse.status).toBe(200);
    expect(collectionsResponse.headers.get("access-control-allow-origin")).toBe(
      "chrome-extension://abcdef"
    );
    const collections =
      (await collectionsResponse.json()) as CollectionSummary[];
    expect(collections).toContainEqual({
      has_prompts: true,
      id: "20260601-clm-aaa-collection",
      mapped: false,
      name: "aaa-collection",
      pattern_count: 1,
      playlist_name: null,
    });

    const promptsResponse = await handler(
      new Request(
        `http://localhost:7874${collectionPromptsRoute("20260601-clm-aaa-collection")}`
      )
    );
    expect(promptsResponse.status).toBe(200);
    expect(await promptsResponse.json()).toEqual(entries);
  });

  test("should serve explicit DistroKid source with metadata track titles", async () => {
    const root = makeTempDir("collection-serve-single-");
    const collectionDir = writeCollection(
      root,
      "20260601-clm-distrokid-collection",
      []
    );
    writeDistrokidDisc(collectionDir, "disc1-test-album", "Metadata Album");
    writeDistrokidMetadataWithTracks(
      collectionDir,
      "disc1-test-album",
      "Metadata Album",
      [{ filename: "track-01.mp3", title: "Metadata Track Title" }]
    );
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7886"),
      };
    }) as unknown as typeof Bun.serve;

    const input = CollectionServeInputSchema.parse({
      distrokid_source: "30-distrokid/disc1-test-album",
      path: collectionDir,
      port: 7886,
    }) as CollectionServeInput;
    const result = (await collectionServeService(input, {
      config: fakeConfig(true),
    })) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    const response = await handler(
      new Request(`http://localhost:7886${DISTROKID_RELEASE_ROUTE}`)
    );
    const body = (await response.json()) as {
      release: { album_title: string; tracks: { title: string }[] };
    };

    expect(response.status).toBe(200);
    expect(body.release.album_title).toBe("Metadata Album");
    expect(body.release.tracks[0]?.title).toBe("Metadata Track Title");
  });

  test("should mark captured collections and derive playlist names in dir mode", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const captureRoot = makeTempDir("collection-serve-capture-");
    writeCollection(
      planning,
      "20260601-soulful-grooves-wah-groove-collection",
      [{ lyrics: "", name: "A", style: "soul" }]
    );
    writeCollection(
      planning,
      "20260602-soulful-grooves-rain-drive-collection",
      [{ lyrics: "", name: "B", style: "jazz" }]
    );
    mkdirSync(join(captureRoot, "config"), { recursive: true });
    writeFileSync(
      join(captureRoot, "config", "suno-playlists.json"),
      JSON.stringify({
        "soulful-grooves-wah-groove": {
          title: "Soulful Grooves | Wah Groove",
          url: "https://suno.com/playlist/wah",
        },
      }),
      "utf-8"
    );
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7876"),
      };
    }) as unknown as typeof Bun.serve;

    const input = CollectionServeInputSchema.parse({
      path: planning,
      playlist_capture_prefix: "soulful-grooves",
      playlist_capture_root: captureRoot,
      port: 7876,
    }) as CollectionServeInput;
    const result = (await collectionServeService(input, {
      config: fakeConfig(false),
    })) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }

    const response = await handler(
      new Request(`http://localhost:7876${COLLECTIONS_ROUTE}`)
    );
    expect(response.status).toBe(200);
    const collections = (await response.json()) as CollectionSummary[];
    expect(
      collections.find(
        (collection) =>
          collection.id === "20260601-soulful-grooves-wah-groove-collection"
      )
    ).toMatchObject({
      mapped: true,
      playlist_name: "soulful-grooves | wah-groove",
    });
    expect(
      collections.find(
        (collection) =>
          collection.id === "20260602-soulful-grooves-rain-drive-collection"
      )
    ).toMatchObject({
      mapped: false,
      playlist_name: "soulful-grooves | rain-drive",
    });
  });

  test("should read legacy playlist list schema and preserve it when merging capture updates", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const captureRoot = makeTempDir("collection-serve-capture-");
    writeCollection(planning, "20260601-clm-legacy-mood-collection", [
      { lyrics: "", name: "A", style: "soul" },
    ]);
    writeCollection(planning, "20260602-clm-new-mood-collection", [
      { lyrics: "", name: "B", style: "jazz" },
    ]);
    mkdirSync(join(captureRoot, "config"), { recursive: true });
    writeFileSync(
      join(captureRoot, "config", "suno-playlists.json"),
      JSON.stringify([
        {
          captured_at: "2026-06-01T00:00:00.000Z",
          slug: "clm-legacy-mood",
          suno_title: "clm | Legacy Mood",
          suno_url: "https://suno.com/playlist/legacy",
        },
      ]),
      "utf-8"
    );
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7881"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        path: planning,
        playlist_capture_prefix: "clm",
        playlist_capture_root: captureRoot,
        port: 7881,
      }) as CollectionServeInput,
      { config: fakeConfig(false) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    const collectionsResponse = await handler(
      new Request(`http://localhost:7881${COLLECTIONS_ROUTE}`)
    );
    const collections =
      (await collectionsResponse.json()) as CollectionSummary[];
    expect(
      collections.find(
        (collection) => collection.id === "20260601-clm-legacy-mood-collection"
      )
    ).toMatchObject({ mapped: true });

    const captureResponse = await handler(
      jsonRequest(`http://localhost:7881${PLAYLISTS_CAPTURE_ROUTE}`, [
        {
          title: "clm | New Mood",
          url: "https://suno.com/playlist/new",
        },
      ])
    );
    expect(captureResponse.status).toBe(200);
    const stored = JSON.parse(
      readFileSync(join(captureRoot, "config", "suno-playlists.json"), "utf-8")
    ) as Record<string, { title: string; url: string }>;
    expect(stored["clm-legacy-mood"]).toMatchObject({
      title: "clm | Legacy Mood",
      url: "https://suno.com/playlist/legacy",
    });
    expect(stored["clm-new-mood"]).toMatchObject({
      title: "clm | New Mood",
      url: "https://suno.com/playlist/new",
    });
  });

  test("should keep the existing playlist file when capture write cannot complete", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const captureRoot = makeTempDir("collection-serve-capture-");
    const configDir = join(captureRoot, "config");
    const playlistsPath = join(configDir, "suno-playlists.json");
    writeCollection(planning, "20260601-clm-midnight-mood-collection", [
      { lyrics: "", name: "A", style: "soul" },
    ]);
    mkdirSync(configDir, { recursive: true });
    writeFileSync(
      playlistsPath,
      JSON.stringify({
        "clm-existing": {
          title: "clm | Existing",
          url: "https://suno.com/playlist/existing",
        },
      }),
      "utf-8"
    );
    chmodSync(configDir, 0o555);
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7882"),
      };
    }) as unknown as typeof Bun.serve;

    const result = (await collectionServeService(
      CollectionServeInputSchema.parse({
        path: planning,
        playlist_capture_prefix: "clm",
        playlist_capture_root: captureRoot,
        port: 7882,
      }) as CollectionServeInput,
      { config: fakeConfig(false) }
    )) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    await expect(
      handler(
        jsonRequest(`http://localhost:7882${PLAYLISTS_CAPTURE_ROUTE}`, [
          {
            title: "clm | Midnight Mood",
            url: "https://suno.com/playlist/midnight",
          },
        ])
      )
    ).rejects.toThrow();
    chmodSync(configDir, 0o755);
    expect(JSON.parse(readFileSync(playlistsPath, "utf-8"))).toEqual({
      "clm-existing": {
        title: "clm | Existing",
        url: "https://suno.com/playlist/existing",
      },
    });
  });

  test("should require root array body for playlist capture and reject envelope-shaped requests", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const captureRoot = makeTempDir("collection-serve-capture-");
    writeCollection(planning, "20260601-clm-midnight-mood-collection", [
      { lyrics: "", name: "A — A", style: "slow, jazz" },
    ]);
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7875"),
      };
    }) as unknown as typeof Bun.serve;

    const input = CollectionServeInputSchema.parse({
      path: planning,
      playlist_capture_prefix: "clm",
      playlist_capture_root: captureRoot,
      port: 7875,
    }) as CollectionServeInput;
    const result = (await collectionServeService(input, {
      config: fakeConfig(false),
    })) as CollectionServeResult;

    expect(result.ok).toBe(true);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }
    const preflight = await handler(
      new Request(`http://localhost:7875${PLAYLISTS_CAPTURE_ROUTE}`, {
        headers: {
          "access-control-request-headers": "content-type",
          "access-control-request-method": "POST",
          origin: "https://suno.com",
        },
        method: "OPTIONS",
      })
    );
    expect(preflight.status).toBe(204);
    expect(preflight.headers.get("access-control-allow-methods")).toBe(
      "GET, POST, OPTIONS"
    );
    expect(preflight.headers.get("access-control-allow-headers")).toBe(
      "Content-Type"
    );
    const okResponse = await handler(
      jsonRequest(`http://localhost:7875${PLAYLISTS_CAPTURE_ROUTE}`, [
        {
          title: "clm | Midnight Mood",
          url: "https://suno.com/playlist/abc",
        },
      ])
    );
    expect(okResponse.status).toBe(200);
    expect(await okResponse.json()).toEqual({
      path: join(captureRoot, "config", "suno-playlists.json"),
      written: 1,
    });
    const stored = JSON.parse(
      readFileSync(join(captureRoot, "config", "suno-playlists.json"), "utf-8")
    ) as Record<string, { title: string; url: string }>;
    expect(stored["clm-midnight-mood"]).toMatchObject({
      title: "clm | Midnight Mood",
      url: "https://suno.com/playlist/abc",
    });

    const envelopeResponse = await handler(
      jsonRequest(`http://localhost:7875${PLAYLISTS_CAPTURE_ROUTE}`, {
        data: [
          {
            title: "clm | Midnight Mood",
            url: "https://suno.com/playlist/abc",
          },
        ],
      })
    );
    expect(envelopeResponse.status).toBe(400);

    const invalidJsonResponse = await handler(
      new Request(`http://localhost:7875${PLAYLISTS_CAPTURE_ROUTE}`, {
        body: "{not json",
        headers: {
          "content-type": "application/json",
          origin: "https://suno.com",
        },
        method: "POST",
      })
    );
    expect(invalidJsonResponse.status).toBe(400);

    const noOriginResponse = await handler(
      jsonRequestWithOrigin(`http://localhost:7875${PLAYLISTS_CAPTURE_ROUTE}`, [
        { title: "clm | Origin Missing", url: "https://suno.com/playlist/no" },
      ])
    );
    expect(noOriginResponse.status).toBe(403);

    const disallowedOriginResponse = await handler(
      jsonRequestWithOrigin(
        `http://localhost:7875${PLAYLISTS_CAPTURE_ROUTE}`,
        [{ title: "clm | Origin Evil", url: "https://suno.com/playlist/evil" }],
        "https://evil.com"
      )
    );
    expect(disallowedOriginResponse.status).toBe(403);
  });

  test("should serve distrokid collection index only when the integration is enabled", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7876"),
      };
    }) as unknown as typeof Bun.serve;

    const input = CollectionServeInputSchema.parse({
      path: planning,
      port: 7876,
    }) as CollectionServeInput;
    const result = (await collectionServeService(input, {
      config: fakeConfig(true),
    })) as CollectionServeResult;

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.distrokidEnabled).toBe(true);
    expect(result.value.routes).toContain(DISTROKID_COLLECTIONS_ROUTE);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }

    const response = await handler(
      new Request(`http://localhost:7876${DISTROKID_COLLECTIONS_ROUTE}`)
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([]);
  });

  test("should return 404 for distrokid collection index when the integration is disabled", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7877"),
      };
    }) as unknown as typeof Bun.serve;

    const input = CollectionServeInputSchema.parse({
      path: planning,
      port: 7877,
    }) as CollectionServeInput;
    const result = (await collectionServeService(input, {
      config: fakeConfig(false),
    })) as CollectionServeResult;

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.distrokidEnabled).toBe(false);
    expect(result.value.routes).not.toContain(DISTROKID_COLLECTIONS_ROUTE);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }

    const response = await handler(
      new Request(`http://localhost:7877${DISTROKID_COLLECTIONS_ROUTE}`)
    );

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "Not Found" });
  });

  test("should reject distrokid release records when the integration is disabled", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const stateRoot = makeTempDir("collection-serve-state-");
    const collectionId = "20260601-clm-distrokid-collection";
    const collectionDir = writeCollection(planning, collectionId, []);
    writeDistrokidDisc(collectionDir, "disc1-test-album", "Test Album");
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7878"),
      };
    }) as unknown as typeof Bun.serve;

    const input = CollectionServeInputSchema.parse({
      distrokid_state_root: stateRoot,
      path: planning,
      port: 7878,
    }) as CollectionServeInput;
    const result = (await collectionServeService(input, {
      config: fakeConfig(false),
    })) as CollectionServeResult;

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.distrokidEnabled).toBe(false);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }

    const response = await handler(
      jsonRequest(`http://localhost:7878${DISTROKID_RELEASES_ROUTE}`, {
        album_title: "Test Album",
        collection_id: collectionId,
        disc: "disc1-test-album",
      })
    );

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "Not Found" });
    expect(
      existsSync(join(stateRoot, "config", "distrokid-releases.json"))
    ).toBe(false);
  });

  test("should return 404 for distrokid collection assets when the integration is disabled", async () => {
    const planning = makeTempDir("collection-serve-planning-");
    const collectionId = "20260601-clm-distrokid-collection";
    const collectionDir = writeCollection(planning, collectionId, []);
    writeDistrokidDisc(collectionDir, "disc1-test-album", "Test Album");
    let fetchHandler:
      | ((request: Request) => Promise<Response> | Response)
      | undefined;
    Bun.serve = ((options: CapturedServeOptions) => {
      fetchHandler = options.fetch;
      return {
        stop: () => {},
        url: new URL("http://localhost:7878"),
      };
    }) as unknown as typeof Bun.serve;

    const input = CollectionServeInputSchema.parse({
      path: planning,
      port: 7878,
    }) as CollectionServeInput;
    const result = (await collectionServeService(input, {
      config: fakeConfig(false),
    })) as CollectionServeResult;

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.distrokidEnabled).toBe(false);
    const handler = fetchHandler;
    if (handler === undefined) {
      throw new Error("fetchHandler was not captured");
    }

    const response = await handler(
      new Request(
        `http://localhost:7878${COLLECTIONS_ROUTE}/${collectionId}/distrokid/assets/30-distrokid/disc1-test-album/track-01.mp3`
      )
    );

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "Not Found" });
  });
});
