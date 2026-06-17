// Tests for the CLI dependency resolver (#993). resolveDeps() is the single
// place that turns a registry entry's `deps` declaration into the concrete
// DepsMap slice handed to run(). It must build each requested dependency lazily
// — config via loadConfig(), yt / ytAnalytics via one shared OAuth dance — and
// do nothing at all for an empty list, so deps-free commands (skills.list) never
// trigger config loading or authentication.
//
// Network-free assertions mirror oauth.test.ts: env-supplied secrets + a
// still-valid stored token build clients without any Google round trip. The
// "single dance" case routes client_secrets through op (no env / no file) so the
// one Bun.spawn becomes a countable proof that yt + ytAnalytics resolved the
// token together rather than each running its own dance.

import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// reset() clears the channelDir / config singletons between cases so a per-test
// CHANNEL_DIR actually takes effect (both memoize their first resolve).
import { reset } from "@tayk/core/config";

import { resolveDeps } from "../lib/resolve-deps.ts";

// --- env harness ---------------------------------------------------------

const managedKeys = ["CHANNEL_DIR", "CLIENT_SECRETS_JSON"] as const;
let savedEnv: Record<string, string | undefined> = {};
const tmpDirs: string[] = [];

beforeEach(() => {
  savedEnv = {};
  for (const key of managedKeys) {
    savedEnv[key] = process.env[key];
    Reflect.deleteProperty(process.env, key);
  }
  reset();
});

afterEach(() => {
  for (const key of managedKeys) {
    const original = savedEnv[key];
    if (original === undefined) {
      Reflect.deleteProperty(process.env, key);
    } else {
      process.env[key] = original;
    }
  }
  reset();
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

// --- helpers -------------------------------------------------------------

type FakeProc = ReturnType<typeof Bun.spawn>;

// Fake `Bun.spawn` subprocess (op read). A fresh ReadableStream per call because
// `new Response(stream).text()` consumes the stream once.
const fakeProc = (stdout: string, exitCode: number): FakeProc => {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(stdout));
      controller.close();
    },
  });
  return {
    exitCode,
    exited: Promise.resolve(exitCode),
    stdout: stream,
  } as unknown as FakeProc;
};

const makeChannelDir = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "cli-resolve-deps-"));
  tmpDirs.push(dir);
  return dir;
};

// Writes a non-expired token.json (year 2100 expiry) so the dance reads it as
// valid and never refreshes — keeping the build network-free.
const seedValidToken = (dir: string): void => {
  mkdirSync(join(dir, "auth"), { recursive: true });
  writeFileSync(
    join(dir, "auth", "token.json"),
    JSON.stringify({
      access_token: "valid-access",
      expiry_date: 4_102_444_800_000,
      refresh_token: "r",
    }),
    "utf-8"
  );
};

const fakeClientSecretsJson = JSON.stringify({
  installed: { client_id: "cid", client_secret: "cs" },
});

// --- empty deps (lazy) ---------------------------------------------------

describe("resolveDeps — empty deps", () => {
  test("returns {} without loading config or authenticating", async () => {
    process.env.CHANNEL_DIR = join(
      tmpdir(),
      "resolve-deps-nonexistent-xyz-993"
    );
    reset();
    const spawnSpy = spyOn(Bun, "spawn");

    const deps = await resolveDeps([]);

    expect(deps).toEqual({});
    expect(spawnSpy).not.toHaveBeenCalled();

    spawnSpy.mockRestore();
  });
});

// --- config --------------------------------------------------------------

describe("resolveDeps — config", () => {
  const repoRoot = resolve(import.meta.dir, "..", "..", "..");
  const sampleChannel = join(repoRoot, "tests", "fixtures", "sample_channel");

  test("loads the channel config via loadConfig and returns it under `config`", async () => {
    process.env.CHANNEL_DIR = sampleChannel;
    reset();

    const deps = await resolveDeps(["config"]);

    expect(deps.config.identity.meta.channelName).toBe("Test Channel");
    expect("yt" in deps).toBe(false);
    expect("ytAnalytics" in deps).toBe(false);
  });
});

// --- channelDir ----------------------------------------------------------

describe("resolveDeps — channelDir", () => {
  test("resolves the selected channel root without loading config or auth", async () => {
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    reset();
    const spawnSpy = spyOn(Bun, "spawn");

    const deps = await resolveDeps(["channelDir"]);

    expect(deps.channelDir).toBe(dir);
    expect("config" in deps).toBe(false);
    expect("yt" in deps).toBe(false);
    expect("ytAnalytics" in deps).toBe(false);
    expect(spawnSpy).not.toHaveBeenCalled();

    spawnSpy.mockRestore();
  });
});

// --- yt (network-free) ---------------------------------------------------

describe("resolveDeps — yt", () => {
  test("builds the Data API client from a still-valid stored token without op", async () => {
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    process.env.CLIENT_SECRETS_JSON = fakeClientSecretsJson;
    seedValidToken(dir);
    reset();
    const spawnSpy = spyOn(Bun, "spawn");

    const deps = await resolveDeps(["yt"]);

    expect(typeof deps.yt.videos).toBe("object");
    expect("config" in deps).toBe(false);
    expect("ytAnalytics" in deps).toBe(false);
    expect(spawnSpy).not.toHaveBeenCalled();

    spawnSpy.mockRestore();
  });
});

// --- ytAnalytics (network-free) ------------------------------------------

describe("resolveDeps — ytAnalytics", () => {
  test("builds the Analytics API client from a still-valid stored token without op", async () => {
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    process.env.CLIENT_SECRETS_JSON = fakeClientSecretsJson;
    seedValidToken(dir);
    reset();
    const spawnSpy = spyOn(Bun, "spawn");

    const deps = await resolveDeps(["ytAnalytics"]);

    expect(typeof deps.ytAnalytics.reports).toBe("object");
    expect("yt" in deps).toBe(false);
    expect(spawnSpy).not.toHaveBeenCalled();

    spawnSpy.mockRestore();
  });
});

// --- yt + ytAnalytics share one dance ------------------------------------

describe("resolveDeps — yt + ytAnalytics share a single auth dance", () => {
  test("resolves the token once (op consulted a single time) and builds both clients", async () => {
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    seedValidToken(dir);
    reset();
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(
      fakeProc(fakeClientSecretsJson, 0)
    );

    const deps = await resolveDeps(["yt", "ytAnalytics"]);

    expect(typeof deps.yt.videos).toBe("object");
    expect(typeof deps.ytAnalytics.reports).toBe("object");
    expect(spawnSpy).toHaveBeenCalledTimes(1);

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });
});
