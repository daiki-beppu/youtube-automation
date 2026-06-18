// Tests for the Gemini provider's 1-attempt contract and for
// `generateImageService` — the ADR-0003 Result boundary that owns retry and
// persistence since #959.
//
// The provider unit tests construct `GeminiImageProvider` with an injected fake
// SDK client and assert the new contract directly: `generate(req)` returns the
// decoded image bytes on success and throws on failure (image-less response →
// unprefixed Error; SDK errors — SAFETY/RECITATION included — propagate as-is).
// Retry, backoff and persist now live in the service, so those behaviors are
// observed through `generateImageService(input, { provider, persist, sleep })`
// with fake sleep/persist recorders:
//   - retryable failures           → 3 attempts, [10s, 30s] backoff, err(domain "io")
//   - SAFETY / RECITATION          → no retry, err(domain "io")
//   - schema violation             → err(domain "validation"), provider untouched
// The identity test reads provider metadata the service does not expose, so it
// keeps talking to the provider directly.
//
// Faithful SDK shape (verified against @google/genai docs): the client exposes
// `models.generateContent(params)` and returns
//   { candidates: [{ content: { parts: [ <part>, ... ] } }] }
// where an image part is `{ inlineData: { data: <base64 string>, mimeType } }`
// and a text part is `{ text: string }`. The provider base64-decodes
// `inlineData.data` and returns the raw bytes, mirroring the OpenAI b64 path.

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import {
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  GeminiImageProvider,
  generateImageService,
} from "@youtube-automation/core/image";
import type { GenerateImageInput } from "@youtube-automation/core/image";

// Constructor deps type, derived from the provider itself so the test does not
// hard-code an exported name for the injection bag.
type GeminiDeps = NonNullable<
  ConstructorParameters<typeof GeminiImageProvider>[1]
>;

// --- fakes ----------------------------------------------------------------

type Behavior = () => unknown;

// A fake `@google/genai` client. Each generateContent call consumes the next
// behavior (a value-returning or throwing thunk); the last one repeats so a
// single "always fails" behavior covers every retry attempt.
const makeGeminiClient = (behaviors: Behavior[]) => {
  const calls: unknown[] = [];
  let index = 0;
  const client = {
    models: {
      generateContent: (params: unknown) => {
        calls.push(params);
        const behavior = behaviors[Math.min(index, behaviors.length - 1)];
        index += 1;
        return Promise.resolve().then(behavior);
      },
    },
  };
  return { calls, client };
};

const imageResponse = (base64: string) => ({
  candidates: [
    {
      content: {
        parts: [{ inlineData: { data: base64, mimeType: "image/png" } }],
      },
    },
  ],
});

const textOnlyResponse = (text: string) => ({
  candidates: [{ content: { parts: [{ text }] } }],
});

// Captures the sleeps and persists injected into the SERVICE (#959 moved both
// out of the provider) so retries never wait on real timers and saves never
// touch disk.
const makeRecorders = () => {
  const sleeps: number[] = [];
  const persisted: { path: string; bytes: Uint8Array }[] = [];
  return {
    persist: (outputPath: string, bytes: Uint8Array): Promise<string> => {
      persisted.push({ bytes, path: outputPath });
      return Promise.resolve(outputPath);
    },
    persisted,
    sleep: (ms: number): Promise<void> => {
      sleeps.push(ms);
      return Promise.resolve();
    },
    sleeps,
  };
};

const makeDeps = (client: unknown): GeminiDeps =>
  ({ createClient: () => client }) as unknown as GeminiDeps;

let workdir: string;

const channelPath = (path: string): string => join(realpathSync(workdir), path);

// Service deps bundling the provider with the fake sleep/persist recorders.
const serviceDeps = (
  provider: GeminiImageProvider,
  recorders: ReturnType<typeof makeRecorders>
) => ({
  channelDir: workdir,
  persist: recorders.persist,
  provider,
  sleep: recorders.sleep,
});

const geminiConfig = {
  imageSize: "2K",
  model: "gemini-3.1-flash-image-preview",
};

const baseRequest = (outputPath: string): GenerateImageInput => ({
  aspectRatio: "16:9",
  imageSize: "2K",
  outputPath,
  prompt: "a calm lo-fi study room at night",
});

beforeAll(() => {
  workdir = mkdtempSync(join(tmpdir(), "img-gemini-"));
});

afterAll(() => {
  rmSync(workdir, { force: true, recursive: true });
});

// --- identity -------------------------------------------------------------

describe("GeminiImageProvider identity", () => {
  test("reports its name and unrestricted aspect ratios", () => {
    // Given a constructed gemini provider (gemini.py:27-29)
    const provider = new GeminiImageProvider(geminiConfig);
    // When reading its metadata
    // Then it identifies as gemini with no ratio restriction
    expect(provider.name).toBe("gemini");
    expect([...provider.supportedAspectRatios]).toEqual([]);
  });
});

// --- provider 1-attempt contract -------------------------------------------

describe("GeminiImageProvider 1-attempt contract", () => {
  test("returns the decoded base64 image bytes on success", async () => {
    // Given a client that returns one inline image part
    const original = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3, 4]);
    const base64 = Buffer.from(original).toString("base64");
    const { calls, client } = makeGeminiClient([() => imageResponse(base64)]);
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When calling the provider directly
    const bytes = await provider.generate(
      baseRequest("collections/planning/demo/u.png")
    );

    // Then the decoded bytes come back from a single SDK call — no retry, no
    // persistence side effect inside the provider
    expect([...bytes]).toEqual([...original]);
    expect(calls).toHaveLength(1);
  });

  test("throws an unprefixed Error on an image-less response (single attempt)", async () => {
    // Given a client that only returns text (no image part)
    const { calls, client } = makeGeminiClient([
      () => textOnlyResponse("no image in response"),
    ]);
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When calling the provider directly
    // Then it throws once without retrying internally; the message carries no
    // domain prefix so the service-side withRetry treats it as retryable
    await expect(
      provider.generate(baseRequest("collections/planning/demo/miss-unit.png"))
    ).rejects.toThrow("gemini が画像なしレスポンスを返しました");
    expect(calls).toHaveLength(1);
  });

  test("propagates SDK errors as-is (SAFETY included)", async () => {
    // Given an SDK error carrying a SAFETY content-policy message
    const sdkError = new Error("blocked due to SAFETY filters");
    const { calls, client } = makeGeminiClient([
      () => {
        throw sdkError;
      },
    ]);
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When calling the provider directly
    let caught: unknown;
    try {
      await provider.generate(
        baseRequest("collections/planning/demo/safety-unit.png")
      );
    } catch (error) {
      caught = error;
    }

    // Then the very same error instance surfaces — the non-retryable
    // classification is the service's job, not the provider's
    expect(caught).toBe(sdkError);
    expect(calls).toHaveLength(1);
  });
});

// --- service success path ---------------------------------------------------

describe("generateImageService (gemini) success", () => {
  test("decodes the base64 image part and persists the raw bytes", async () => {
    // Given a client that returns one inline image part
    const original = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3, 4]);
    const base64 = Buffer.from(original).toString("base64");
    const { client } = makeGeminiClient([() => imageResponse(base64)]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));
    const outputPath = "collections/planning/demo/out.png";

    // When generating through the service boundary
    const r = await generateImageService(
      baseRequest(outputPath),
      serviceDeps(provider, recorders)
    );

    // Then the result is ok, the decoded bytes are persisted by the SERVICE,
    // and the saved path is carried in `value`
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.savedPath).toBe(channelPath(outputPath));
    expect(recorders.persisted).toHaveLength(1);
    const [persisted] = recorders.persisted;
    if (!persisted) {
      throw new Error("expected a persisted image");
    }
    expect([...persisted.bytes]).toEqual([...original]);
    expect(persisted.path).toBe(channelPath(outputPath));
    expect(recorders.sleeps).toEqual([]);
  });

  test("forwards the configured model and request aspect ratio to the SDK", async () => {
    // Given a successful single-image response
    const base64 = Buffer.from(new Uint8Array([1, 2, 3])).toString("base64");
    const { calls, client } = makeGeminiClient([() => imageResponse(base64)]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When generating with aspect ratio 16:9 through the service
    const r = await generateImageService(
      baseRequest("collections/planning/demo/fwd.png"),
      serviceDeps(provider, recorders)
    );

    // Then it succeeds, the model is passed through, and the aspect ratio
    // reaches the SDK call
    expect(r.ok).toBe(true);
    expect(calls).toHaveLength(1);
    const params = calls[0] as { model?: unknown };
    expect(params.model).toBe("gemini-3.1-flash-image-preview");
    expect(JSON.stringify(calls[0])).toContain("16:9");
  });

  test("inlines reference image bytes as base64 into the request", async () => {
    // Given a reference image on disk and a successful response
    const refBytes = new Uint8Array([
      0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
    ]);
    const refPath = "collections/planning/demo/ref.png";
    mkdirSync(channelPath("collections/planning/demo"), { recursive: true });
    writeFileSync(channelPath(refPath), refBytes);
    const base64 = Buffer.from(new Uint8Array([9, 9, 9])).toString("base64");
    const { calls, client } = makeGeminiClient([() => imageResponse(base64)]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When generating with a reference image (gemini.py:45-51)
    const r = await generateImageService(
      {
        ...baseRequest("collections/planning/demo/ref-out.png"),
        references: [refPath],
      },
      serviceDeps(provider, recorders)
    );

    // Then it still succeeds and the reference bytes are sent as base64 inlineData
    expect(r.ok).toBe(true);
    const refBase64 = Buffer.from(refBytes).toString("base64");
    expect(JSON.stringify(calls[0])).toContain(refBase64);
  });
});

// --- service retry path -----------------------------------------------------

describe("generateImageService (gemini) retry", () => {
  test("retries on an image-less response and fails after 3 attempts", async () => {
    // Given a client that only ever returns text (no image part)
    const { calls, client } = makeGeminiClient([
      () => textOnlyResponse("no image in response"),
    ]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When generating through the service
    const r = await generateImageService(
      baseRequest("collections/planning/demo/miss.png"),
      serviceDeps(provider, recorders)
    );

    // Then the unprefixed provider failure maps to an `io` ServiceError after
    // all 3 attempts and two backoff waits owned by the service's withRetry
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("io");
    expect(calls).toHaveLength(3);
    // Two waits (between attempt 1→2 and 2→3), in ms = backoff seconds × 1000
    expect(recorders.sleeps).toEqual([10_000, 30_000]);
    expect(recorders.persisted).toEqual([]);
  });

  test("succeeds on a later attempt after transient SDK errors", async () => {
    // Given two thrown errors followed by a good image response
    const base64 = Buffer.from(new Uint8Array([7, 7])).toString("base64");
    const { calls, client } = makeGeminiClient([
      () => {
        throw new Error("503 backend unavailable");
      },
      () => {
        throw new Error("deadline exceeded");
      },
      () => imageResponse(base64),
    ]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When generating through the service
    const r = await generateImageService(
      baseRequest("collections/planning/demo/late.png"),
      serviceDeps(provider, recorders)
    );

    // Then the third attempt wins after two backoff waits
    expect(r.ok).toBe(true);
    expect(calls).toHaveLength(3);
    expect(recorders.sleeps).toEqual([10_000, 30_000]);
  });
});

// --- content-policy short-circuit ----------------------------------------

describe("generateImageService (gemini) content policy", () => {
  test("does not retry when the SDK reports a SAFETY violation", async () => {
    // Given an error whose message contains SAFETY (gemini.py:100-102)
    const { calls, client } = makeGeminiClient([
      () => {
        throw new Error("blocked due to SAFETY filters");
      },
    ]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When generating through the service
    const r = await generateImageService(
      baseRequest("collections/planning/demo/safety.png"),
      serviceDeps(provider, recorders)
    );

    // Then it fails (domain "io") immediately with no retry and no backoff wait
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("io");
    expect(calls).toHaveLength(1);
    expect(recorders.sleeps).toEqual([]);
  });

  test("does not retry when the SDK reports a RECITATION block", async () => {
    // Given an error whose message contains RECITATION (gemini.py:100-102)
    const { calls, client } = makeGeminiClient([
      () => {
        throw new Error("output halted: RECITATION");
      },
    ]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When generating through the service
    const r = await generateImageService(
      baseRequest("collections/planning/demo/recite.png"),
      serviceDeps(provider, recorders)
    );

    // Then it short-circuits to failure without retrying
    expect(r.ok).toBe(false);
    expect(calls).toHaveLength(1);
    expect(recorders.sleeps).toEqual([]);
  });
});

// --- schema boundary ------------------------------------------------------

describe("generateImageService input validation", () => {
  test("maps a strict-schema violation to a validation error without calling the provider", async () => {
    // Given a provider whose generate would succeed if it were ever reached
    const base64 = Buffer.from(new Uint8Array([1])).toString("base64");
    const { calls, client } = makeGeminiClient([() => imageResponse(base64)]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(geminiConfig, makeDeps(client));

    // When the input carries an unexpected key the `.strict()` schema rejects
    const malformed = {
      ...baseRequest("collections/planning/demo/bad.png"),
      unexpected: true,
    } as unknown as GenerateImageInput;
    const r = await generateImageService(
      malformed,
      serviceDeps(provider, recorders)
    );

    // Then the boundary parses first: a validation ServiceError, and the
    // provider is never invoked
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(calls).toEqual([]);
    expect(recorders.persisted).toEqual([]);
  });
});
