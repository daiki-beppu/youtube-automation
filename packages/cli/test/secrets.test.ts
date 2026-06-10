import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// `reset()` clears the channelDir singleton between cases so a per-test
// CHANNEL_DIR actually takes effect (channelDir() memoizes its first resolve).
import { reset } from "@youtube-automation/core/config";

// Relative import of the cli's own module (#822 move target). The acceptance
// criteria require cli callsites to reach secrets via the relative path, not a
// re-export from @youtube-automation/core. `ConfigError` was retired in #821
// (5 名前タグ class 撤廃) — the `config:` prefix on plain Error is now the
// single source of domain truth, routed by toServiceError.
import {
  resolveClientSecretsJson,
  resolveSecret,
  SECRET_REFS,
} from "../lib/secrets.ts";

// --- helpers -------------------------------------------------------------

type FakeProc = ReturnType<typeof Bun.spawn>;

// Builds a fake `Bun.spawn` subprocess. A fresh ReadableStream is created per
// call because `new Response(stream).text()` consumes the stream once.
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

// Snapshot + restore every SECRET_REFS-managed env var so a value that happens
// to live in the real CI environment cannot leak into the op-path/throw tests.
const managedKeys = Object.keys(SECRET_REFS);
let savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  savedEnv = {};
  for (const key of managedKeys) {
    savedEnv[key] = process.env[key];
    Reflect.deleteProperty(process.env, key);
  }
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
});

// --- SECRET_REFS constant ------------------------------------------------

describe("SECRET_REFS", () => {
  test("exposes the six ported secret names mapped to op:// URIs", () => {
    // Given the ported _SECRET_REFS table
    // When inspecting the exported constant
    // Then it carries exactly the six registered names
    expect(Object.keys(SECRET_REFS).toSorted()).toEqual(
      [
        "CLIENT_SECRETS_JSON",
        "DISCORD_WEBHOOK_URL",
        "OPENAI_API_KEY",
        "STREAM_WEBHOOK_URL",
        "VULTR_API_KEY",
        "YOUTUBE_STREAM_KEY",
      ].toSorted()
    );
  });

  test("keeps the default CLIENT_SECRETS_JSON op reference", () => {
    // Given the OAuth client-secrets default from secrets.py:27
    // When reading the mapped URI
    // Then it matches the canonical 1Password reference
    expect(SECRET_REFS.CLIENT_SECRETS_JSON).toBe(
      "op://Personal/YouTube_OAuth_Client_Secrets/credential"
    );
  });
});

// --- env path ------------------------------------------------------------

describe("resolveSecret env path", () => {
  test("returns the value from process.env when present", async () => {
    // Given an env var set for a registered name
    process.env.OPENAI_API_KEY = "env-openai-value";
    // When resolving that name
    const value = await resolveSecret("OPENAI_API_KEY");
    // Then the env value is returned verbatim
    expect(value).toBe("env-openai-value");
  });

  test("prefers env over the op CLI (op is never spawned)", async () => {
    // Given both an env var and an available op CLI
    process.env.VULTR_API_KEY = "env-vultr-value";
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(
      fakeProc("op-vultr-value\n", 0)
    );

    // When resolving the name
    const value = await resolveSecret("VULTR_API_KEY");

    // Then the env value wins and op is not consulted
    expect(value).toBe("env-vultr-value");
    expect(spawnSpy).not.toHaveBeenCalled();

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });

  test("ignores an empty env value and falls through to op", async () => {
    // Given an env var set to an empty string (falsy, like secrets.py:56)
    process.env.OPENAI_API_KEY = "";
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(
      fakeProc("op-openai-value\n", 0)
    );

    // When resolving the name
    const value = await resolveSecret("OPENAI_API_KEY");

    // Then the empty env is skipped and op supplies the value
    expect(value).toBe("op-openai-value");

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });
});

// --- op CLI path ---------------------------------------------------------

describe("resolveSecret op path", () => {
  test("returns the trimmed op read output", async () => {
    // Given no env var but an available op CLI returning a value
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(
      fakeProc("  op-secret-value  \n", 0)
    );

    // When resolving the name
    const value = await resolveSecret("YOUTUBE_STREAM_KEY");

    // Then surrounding whitespace is stripped (secrets.py:69)
    expect(value).toBe("op-secret-value");

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });

  test("invokes `op read` with the mapped reference URI, not the name", async () => {
    // Given an available op CLI
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(
      fakeProc("value\n", 0)
    );

    // When resolving a registered name
    await resolveSecret("DISCORD_WEBHOOK_URL");

    // Then the subprocess reads the op:// reference, not the bare name
    const argvs = spawnSpy.mock.calls.map((call) => call[0]);
    expect(argvs).toContainEqual([
      "op",
      "read",
      SECRET_REFS.DISCORD_WEBHOOK_URL,
    ]);

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });

  test("throws a config:-prefixed error when op exits non-zero", async () => {
    // Given an available op CLI that fails (e.g. not signed in)
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc("", 1));

    // When resolving with no env fallback
    // Then resolution fails fast (secrets.py:72 swallow → :75 raise)
    await expect(resolveSecret("STREAM_WEBHOOK_URL")).rejects.toThrow(
      /^config:/u
    );

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });

  test("throws a config:-prefixed error when op succeeds but output is blank", async () => {
    // Given op exits 0 but yields only whitespace
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc("   \n", 0));

    // When resolving with no env fallback
    // Then the blank value is rejected (secrets.py:70 `if value`)
    await expect(resolveSecret("STREAM_WEBHOOK_URL")).rejects.toThrow(
      /^config:/u
    );

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });
});

// --- failure modes -------------------------------------------------------

describe("resolveSecret failures", () => {
  test("throws a config:-prefixed error for an unregistered name", async () => {
    // Given a name absent from SECRET_REFS (secrets.py:52)
    // When resolving it
    // Then it fails fast before any lookup, tagged via the config prefix
    await expect(resolveSecret("NOT_A_REAL_SECRET")).rejects.toThrow(
      /^config:/u
    );
  });

  test("throws a config:-prefixed error when env is unset and op is unavailable", async () => {
    // Given no env var and no op CLI on PATH (secrets.py:60 false branch)
    const whichSpy = spyOn(Bun, "which").mockReturnValue(null);

    // When resolving the name
    // Then resolution fails with the config prefix and guidance naming the secret
    const promise = resolveSecret("OPENAI_API_KEY");
    await expect(promise).rejects.toThrow(/^config:/u);
    await expect(promise).rejects.toThrow(/OPENAI_API_KEY/u);

    whichSpy.mockRestore();
  });

  test("the thrown failure is a plain Error tagged by the config: prefix", async () => {
    // Given a guaranteed failure (unregistered name)
    // When catching the thrown error
    let caught: unknown;
    try {
      await resolveSecret("NOT_A_REAL_SECRET");
    } catch (error) {
      caught = error;
    }
    // Then it is a plain Error whose message carries the config domain prefix
    // (the named tag class is removed; the `config:` prefix convention
    // is the single source of domain truth, routed by toServiceError)
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toMatch(/^config:/u);
  });
});

// --- resolveClientSecretsJson (#822 new helper) --------------------------

// Mirrors the ADR-0003 §4 fallback chain:
//   1. CLIENT_SECRETS_JSON env  →  2. <channel>/auth/client_secrets.json
//   →  3. op read SECRET_REFS.CLIENT_SECRETS_JSON
// The return value is the JSON *content* string (not a path), per the
// `clientSecretsJson: string` contract.
describe("resolveClientSecretsJson", () => {
  let savedChannelDir: string | undefined;
  const tmpDirs: string[] = [];

  beforeEach(() => {
    savedChannelDir = process.env.CHANNEL_DIR;
    Reflect.deleteProperty(process.env, "CHANNEL_DIR");
    reset();
  });

  afterEach(() => {
    if (savedChannelDir === undefined) {
      Reflect.deleteProperty(process.env, "CHANNEL_DIR");
    } else {
      process.env.CHANNEL_DIR = savedChannelDir;
    }
    reset();
    while (tmpDirs.length > 0) {
      const dir = tmpDirs.pop();
      if (dir !== undefined) {
        rmSync(dir, { force: true, recursive: true });
      }
    }
  });

  // Creates a throwaway channel root and registers it for teardown.
  const makeChannelDir = (): string => {
    const dir = mkdtempSync(join(tmpdir(), "cli-secrets-"));
    tmpDirs.push(dir);
    return dir;
  };

  test("returns the CLIENT_SECRETS_JSON env content without reading file or op", async () => {
    // Given the JSON content supplied directly via env (step 1)
    const json = '{"installed":{"client_id":"from-env"}}';
    process.env.CLIENT_SECRETS_JSON = json;
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(
      fakeProc("op-json\n", 0)
    );

    // When resolving the client secrets
    const result = await resolveClientSecretsJson();

    // Then the env content wins and op is never spawned
    expect(result).toBe(json);
    expect(spawnSpy).not.toHaveBeenCalled();

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });

  test("reads <channel>/auth/client_secrets.json when env is unset", async () => {
    // Given a channel dir holding the auth file (step 2)
    const dir = makeChannelDir();
    const json = '{"installed":{"client_id":"from-file"}}';
    mkdirSync(join(dir, "auth"), { recursive: true });
    writeFileSync(join(dir, "auth", "client_secrets.json"), json, "utf-8");
    process.env.CHANNEL_DIR = dir;
    reset();
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(
      fakeProc("op-json\n", 0)
    );

    // When resolving with no env override
    const result = await resolveClientSecretsJson();

    // Then the file content is returned and op is not consulted
    expect(result).toBe(json);
    expect(spawnSpy).not.toHaveBeenCalled();

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });

  test("falls back to op read when env and the channel file are absent", async () => {
    // Given a channel dir without an auth/client_secrets.json file (step 3)
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    reset();
    const opJson = '{"installed":{"client_id":"from-op"}}';
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(
      fakeProc(`${opJson}\n`, 0)
    );

    // When resolving with neither env nor file present
    const result = await resolveClientSecretsJson();

    // Then op supplies the value via the mapped op:// reference
    expect(result).toBe(opJson);
    const argvs = spawnSpy.mock.calls.map((call) => call[0]);
    expect(argvs).toContainEqual([
      "op",
      "read",
      SECRET_REFS.CLIENT_SECRETS_JSON,
    ]);

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });

  test("throws a config:-prefixed error when env, file, and op all fail", async () => {
    // Given no env, a channel dir without the file, and no op CLI on PATH
    const dir = makeChannelDir();
    process.env.CHANNEL_DIR = dir;
    reset();
    const whichSpy = spyOn(Bun, "which").mockReturnValue(null);

    // When resolving with every source exhausted
    // Then resolution fails fast with a plain Error tagged by the config prefix
    // (named ConfigError class was retired in #821; `config:` prefix is the
    // single source of domain truth, routed by toServiceError)
    await expect(resolveClientSecretsJson()).rejects.toThrow(/^config:/u);

    whichSpy.mockRestore();
  });
});
