import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";

// Imports by the published package name (not a relative path) so the test
// exercises the package `exports` map, mirroring index.test.ts. A missing
// re-export from src/index.ts would fail resolution here.
import {
  ConfigError,
  resolveSecret,
  SECRET_REFS,
} from "@youtube-automation/core";

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

  test("throws ConfigError when op exits non-zero", async () => {
    // Given an available op CLI that fails (e.g. not signed in)
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc("", 1));

    // When resolving with no env fallback
    // Then resolution fails fast (secrets.py:72 swallow → :75 raise)
    await expect(resolveSecret("STREAM_WEBHOOK_URL")).rejects.toThrow(
      ConfigError
    );

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });

  test("throws ConfigError when op succeeds but output is blank", async () => {
    // Given op exits 0 but yields only whitespace
    const whichSpy = spyOn(Bun, "which").mockReturnValue("/usr/bin/op");
    const spawnSpy = spyOn(Bun, "spawn").mockReturnValue(fakeProc("   \n", 0));

    // When resolving with no env fallback
    // Then the blank value is rejected (secrets.py:70 `if value`)
    await expect(resolveSecret("STREAM_WEBHOOK_URL")).rejects.toThrow(
      ConfigError
    );

    whichSpy.mockRestore();
    spawnSpy.mockRestore();
  });
});

// --- failure modes -------------------------------------------------------

describe("resolveSecret failures", () => {
  test("throws ConfigError for an unregistered name", async () => {
    // Given a name absent from SECRET_REFS (secrets.py:52)
    // When resolving it
    // Then a ConfigError is raised before any lookup
    await expect(resolveSecret("NOT_A_REAL_SECRET")).rejects.toThrow(
      ConfigError
    );
  });

  test("throws ConfigError when env is unset and op is unavailable", async () => {
    // Given no env var and no op CLI on PATH (secrets.py:60 false branch)
    const whichSpy = spyOn(Bun, "which").mockReturnValue(null);

    // When resolving the name
    // Then resolution fails with guidance naming the secret
    const promise = resolveSecret("OPENAI_API_KEY");
    await expect(promise).rejects.toThrow(ConfigError);
    await expect(promise).rejects.toThrow(/OPENAI_API_KEY/u);

    whichSpy.mockRestore();
  });

  test("ConfigError is an Error subclass with a named tag", async () => {
    // Given a guaranteed failure (unregistered name)
    // When catching the thrown error
    let caught: unknown;
    try {
      await resolveSecret("NOT_A_REAL_SECRET");
    } catch (error) {
      caught = error;
    }
    // Then it is a proper Error subclass identifiable by name
    expect(caught).toBeInstanceOf(Error);
    expect(caught).toBeInstanceOf(ConfigError);
    expect((caught as ConfigError).name).toBe("ConfigError");
  });
});
