// Tests for the CLI high-level OAuth helper (ADR-0003 §6). oauth.ts owns the
// orchestration the MCP layer must NOT run (browser/local-server interactive
// flow) plus the small pure pieces: the SCOPES constant (Python parity,
// oauth_handler.py:69-74), token expiry detection, and the token.json path.
//
// getYouTubeClient() is the full env -> secrets -> token read -> (refresh /
// interactive) -> token write 0o600 -> buildYouTubeClient dance. The refresh /
// interactive branches require a real Google round trip and are covered at the
// core service level (oauth-refresh.test.ts) instead. Here we exercise the
// network-free happy path: a still-valid stored token, so the helper only
// resolves secrets from env, reads the token, and builds the client.

import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// reset() clears the channelDir singleton between cases so a per-test
// CHANNEL_DIR actually takes effect (channelDir() memoizes its first resolve).
import { reset } from "@youtube-automation/core/config";

import {
  getYouTubeAnalyticsClient,
  getYouTubeClient,
  isExpired,
  SCOPES,
  tokenJsonPath,
} from "../lib/oauth.ts";
import { permissionBits } from "./permission-bits.ts";

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

const makeChannelDir = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "cli-oauth-"));
  tmpDirs.push(dir);
  return dir;
};

// --- SCOPES constant -----------------------------------------------------

describe("SCOPES", () => {
  test("declares the four YouTube + Analytics + Reporting scopes (Python parity)", () => {
    // Given the ported SCOPES (oauth_handler.py:69-74)
    // When inspecting the exported constant
    // Then it carries exactly the four required scopes
    expect([...SCOPES].toSorted()).toEqual(
      [
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
      ].toSorted()
    );
  });
});

// --- isExpired -----------------------------------------------------------

describe("isExpired", () => {
  test("reports a token whose expiry_date is in the past as expired", () => {
    // Given a token whose access token expired in 1970
    const tokenJson = JSON.stringify({ access_token: "a", expiry_date: 1000 });
    // When checking expiry
    // Then it is expired (oauth_handler.py:177 credentials.expired)
    expect(isExpired(tokenJson)).toBe(true);
  });

  test("reports a token whose expiry_date is comfortably in the future as valid", () => {
    // Given a token expiring in the year 2100
    const tokenJson = JSON.stringify({
      access_token: "a",
      expiry_date: 4_102_444_800_000,
    });
    // When checking expiry
    // Then it is not expired
    expect(isExpired(tokenJson)).toBe(false);
  });
});

// --- tokenJsonPath -------------------------------------------------------

describe("tokenJsonPath", () => {
  test("resolves to <channelDir>/auth/token.json", () => {
    // Given a channel dir selected via CHANNEL_DIR
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    reset();

    // When resolving the token path
    // Then it sits under <channel>/auth, symmetric with client_secrets.json
    expect(tokenJsonPath()).toBe(join(dir, "auth", "token.json"));
  });
});

// --- getYouTubeClient happy path -----------------------------------------

describe("getYouTubeClient happy path", () => {
  test("builds a client from a still-valid stored token without spawning op", async () => {
    // Given client secrets supplied via env and a non-expired token on disk
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    process.env.CLIENT_SECRETS_JSON = JSON.stringify({
      installed: { client_id: "cid", client_secret: "cs" },
    });
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
    reset();
    const spawnSpy = spyOn(Bun, "spawn");

    // When fetching the client while the stored token is still valid
    const client = await getYouTubeClient();

    // Then a googleapis client is returned via the pure build path, and op was
    // never consulted (env supplied the secrets, the token was still valid so no
    // refresh / interactive flow ran)
    expect(client).toBeDefined();
    expect(typeof client.videos).toBe("object");
    expect(spawnSpy).not.toHaveBeenCalled();

    spawnSpy.mockRestore();
  });
});

// --- getYouTubeAnalyticsClient happy path --------------------------------
//
// Symmetric to getYouTubeClient (#993 AC): the same env -> secrets -> token read
// dance builds the Analytics API v2 client instead of the Data API v3 one. The
// network-free happy path (env-supplied secrets + a still-valid stored token)
// must build the client without consulting op or running any refresh /
// interactive round trip. The refresh / interactive branches are not re-tested
// here: both helpers share the one token-resolution dance, already covered by
// the getYouTubeClient cases above.

describe("getYouTubeAnalyticsClient happy path", () => {
  test("builds an analytics client from a still-valid stored token without spawning op", async () => {
    // Given client secrets supplied via env and a non-expired token on disk
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    process.env.CLIENT_SECRETS_JSON = JSON.stringify({
      installed: { client_id: "cid", client_secret: "cs" },
    });
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
    reset();
    const spawnSpy = spyOn(Bun, "spawn");

    // When fetching the analytics client while the stored token is still valid
    const client = await getYouTubeAnalyticsClient();

    // Then a youtubeAnalytics_v2 client is returned (exposing `reports`) via the
    // pure build path, and op was never consulted (env supplied the secrets, the
    // token was still valid so no refresh / interactive flow ran)
    expect(client).toBeDefined();
    expect(typeof client.reports).toBe("object");
    expect(spawnSpy).not.toHaveBeenCalled();

    spawnSpy.mockRestore();
  });
});

// --- getYouTubeClient refresh / interactive glue --------------------------
//
// The interactive / refresh OAuth services need a real Google round trip
// (order.md), so they are injected here via the deps seam and faked. These
// cases cover the CLI glue around them — token-absent -> interactive and
// token-expired -> refresh — asserting each result is written back to
// token.json at 0o600 before the client is built. The services themselves are
// unit-tested at the core level (oauth-refresh.test.ts / oauth-interactive.test.ts).

type Deps = NonNullable<Parameters<typeof getYouTubeClient>[0]>;
type InteractiveInput = Parameters<Deps["interactive"]>[0];
type RefreshInput = Parameters<Deps["refresh"]>[0];

// year 2100, far past any real expiry so ensureFresh treats the token as valid.
const futureExpiry = 4_102_444_800_000;
const failIfCalled = (name: string) => (): never => {
  throw new Error(`${name} must not be called in this branch`);
};

const seedSecretsEnv = (dir: string): void => {
  process.env.CHANNEL_DIR = dir;
  process.env.CLIENT_SECRETS_JSON = JSON.stringify({
    installed: { client_id: "cid", client_secret: "cs" },
  });
  reset();
};

describe("getYouTubeClient interactive branch", () => {
  test("authenticates, writes the issued token at 0o600, then builds the client", async () => {
    // Given no token on disk and a fake interactive service that issues one
    const dir = makeChannelDir();
    seedSecretsEnv(dir);
    const issued = JSON.stringify({
      access_token: "issued",
      expiry_date: futureExpiry,
      refresh_token: "r",
    });
    const calls: InteractiveInput[] = [];
    const deps: Deps = {
      interactive: (input) => {
        calls.push(input);
        return Promise.resolve({ ok: true, value: { tokenJson: issued } });
      },
      refresh: failIfCalled("refresh"),
    };

    // When fetching the client with no stored token
    const client = await getYouTubeClient(deps);

    // Then the interactive service got the resolved secrets + full SCOPES ...
    expect(calls).toHaveLength(1);
    expect(calls[0]?.scopes).toEqual([...SCOPES]);
    expect(JSON.parse(calls[0]?.clientSecretsJson ?? "{}")).toEqual({
      installed: { client_id: "cid", client_secret: "cs" },
    });
    // ... the issued token was persisted at 0o600 ...
    const tokenPath = join(dir, "auth", "token.json");
    expect(readFileSync(tokenPath, "utf-8")).toBe(issued);
    expect(permissionBits(tokenPath)).toBe(0o600);
    // ... and a client was built
    expect(typeof client.videos).toBe("object");
  });
});

describe("getYouTubeClient refresh branch", () => {
  test("refreshes an expired token, writes it back at 0o600, then builds the client", async () => {
    // Given an expired token on disk and a fake refresh service
    const dir = makeChannelDir();
    seedSecretsEnv(dir);
    const expired = JSON.stringify({
      access_token: "stale",
      expiry_date: 1000,
      refresh_token: "r",
    });
    mkdirSync(join(dir, "auth"), { recursive: true });
    writeFileSync(join(dir, "auth", "token.json"), expired, "utf-8");
    reset();
    const refreshed = JSON.stringify({
      access_token: "fresh",
      expiry_date: futureExpiry,
      refresh_token: "r",
    });
    const calls: RefreshInput[] = [];
    const deps: Deps = {
      interactive: failIfCalled("interactive"),
      refresh: (input) => {
        calls.push(input);
        return Promise.resolve({ ok: true, value: { tokenJson: refreshed } });
      },
    };

    // When fetching the client while the stored token is expired
    const client = await getYouTubeClient(deps);

    // Then refresh received the stored (expired) token + resolved secrets ...
    expect(calls).toHaveLength(1);
    expect(calls[0]?.tokenJson).toBe(expired);
    expect(JSON.parse(calls[0]?.clientSecretsJson ?? "{}")).toEqual({
      installed: { client_id: "cid", client_secret: "cs" },
    });
    // ... the refreshed token was written back at 0o600 ...
    const tokenPath = join(dir, "auth", "token.json");
    expect(readFileSync(tokenPath, "utf-8")).toBe(refreshed);
    expect(permissionBits(tokenPath)).toBe(0o600);
    // ... and a client was built
    expect(typeof client.videos).toBe("object");
  });
});
