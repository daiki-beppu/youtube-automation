// Tests for `generateImageService` over the Gemini provider — the ADR-0003
// Result boundary that wraps `GeminiImageProvider.generate` (Issue #823).
//
// The generate-path tests now call `generateImageService(input, { provider })`
// and assert on the Result discriminant (`r.ok` / `r.value` / `r.error`) instead
// of the provider's raw `ImageGenerationResult`. The provider is still
// constructed directly with injected deps (SDK client / backoff sleep /
// image-persist), so these tests still exercise its orchestration — retry,
// SAFETY/RECITATION short-circuit, base64 decode, reference-image inlining —
// against in-memory fakes, but observe it through the service boundary:
//   - provider success            → ok(value.savedPath)
//   - provider `{ success: false }`→ err(domain "io")  (unprefixed failure)
//   - schema violation            → err(domain "validation")
// The identity test reads provider metadata the service does not expose, so it
// keeps talking to the provider directly.
//
// Faithful SDK shape (verified against @google/genai docs): the client exposes
// `models.generateContent(params)` and returns
//   { candidates: [{ content: { parts: [ <part>, ... ] } }] }
// where an image part is `{ inlineData: { data: <base64 string>, mimeType } }`
// and a text part is `{ text: string }`. The provider base64-decodes
// `inlineData.data` before persisting, mirroring the OpenAI b64 path.

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
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

// Captures injected sleeps and persists so retries never wait on real timers
// and saves never touch disk.
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

const makeDeps = (
  client: unknown,
  recorders: ReturnType<typeof makeRecorders>
): GeminiDeps =>
  ({
    createClient: () => client,
    persist: recorders.persist,
    sleep: recorders.sleep,
  }) as unknown as GeminiDeps;

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

// --- temp dir for reference-image fixtures -------------------------------

let workdir: string;

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

// --- success path ---------------------------------------------------------

describe("generateImageService (gemini) success", () => {
  test("decodes the base64 image part and persists the raw bytes", async () => {
    // Given a client that returns one inline image part
    const original = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3, 4]);
    const base64 = Buffer.from(original).toString("base64");
    const { client } = makeGeminiClient([() => imageResponse(base64)]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(
      geminiConfig,
      makeDeps(client, recorders)
    );
    const outputPath = join(workdir, "out.png");

    // When generating through the service boundary
    const r = await generateImageService(baseRequest(outputPath), { provider });

    // Then the result is ok, the decoded bytes are persisted, and the saved
    // path is carried in `value`
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.savedPath).toBe(outputPath);
    expect(recorders.persisted).toHaveLength(1);
    const [persisted] = recorders.persisted;
    if (!persisted) {
      throw new Error("expected a persisted image");
    }
    expect([...persisted.bytes]).toEqual([...original]);
    expect(persisted.path).toBe(outputPath);
    expect(recorders.sleeps).toEqual([]);
  });

  test("forwards the configured model and request aspect ratio to the SDK", async () => {
    // Given a successful single-image response
    const base64 = Buffer.from(new Uint8Array([1, 2, 3])).toString("base64");
    const { calls, client } = makeGeminiClient([() => imageResponse(base64)]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(
      geminiConfig,
      makeDeps(client, recorders)
    );

    // When generating with aspect ratio 16:9 through the service
    const r = await generateImageService(
      baseRequest(join(workdir, "fwd.png")),
      { provider }
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
    const refBytes = new Uint8Array([0x10, 0x20, 0x30, 0x40]);
    const refPath = join(workdir, "ref.png");
    writeFileSync(refPath, refBytes);
    const base64 = Buffer.from(new Uint8Array([9, 9, 9])).toString("base64");
    const { calls, client } = makeGeminiClient([() => imageResponse(base64)]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(
      geminiConfig,
      makeDeps(client, recorders)
    );

    // When generating with a reference image (gemini.py:45-51)
    const r = await generateImageService(
      { ...baseRequest(join(workdir, "ref-out.png")), references: [refPath] },
      { provider }
    );

    // Then it still succeeds and the reference bytes are sent as base64 inlineData
    expect(r.ok).toBe(true);
    const refBase64 = Buffer.from(refBytes).toString("base64");
    expect(JSON.stringify(calls[0])).toContain(refBase64);
  });
});

// --- retry path -----------------------------------------------------------

describe("generateImageService (gemini) retry", () => {
  test("retries on an image-less response and fails after RETRY_MAX attempts", async () => {
    // Given a client that only ever returns text (no image part) (gemini.py:94-96)
    const { calls, client } = makeGeminiClient([
      () => textOnlyResponse("no image in response"),
    ]);
    const recorders = makeRecorders();
    const provider = new GeminiImageProvider(
      geminiConfig,
      makeDeps(client, recorders)
    );

    // When generating through the service
    const r = await generateImageService(
      baseRequest(join(workdir, "miss.png")),
      { provider }
    );

    // Then the unprefixed provider failure maps to an `io` ServiceError after
    // all 3 attempts and two backoff waits
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("io");
    expect(calls).toHaveLength(3);
    // Two waits (between attempt 1→2 and 2→3), in ms = RETRY_BACKOFF seconds × 1000
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
    const provider = new GeminiImageProvider(
      geminiConfig,
      makeDeps(client, recorders)
    );

    // When generating through the service
    const r = await generateImageService(
      baseRequest(join(workdir, "late.png")),
      { provider }
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
    const provider = new GeminiImageProvider(
      geminiConfig,
      makeDeps(client, recorders)
    );

    // When generating through the service
    const r = await generateImageService(
      baseRequest(join(workdir, "safety.png")),
      { provider }
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
    const provider = new GeminiImageProvider(
      geminiConfig,
      makeDeps(client, recorders)
    );

    // When generating through the service
    const r = await generateImageService(
      baseRequest(join(workdir, "recite.png")),
      { provider }
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
    const provider = new GeminiImageProvider(
      geminiConfig,
      makeDeps(client, recorders)
    );

    // When the input carries an unexpected key the `.strict()` schema rejects
    const malformed = {
      ...baseRequest(join(workdir, "bad.png")),
      unexpected: true,
    } as unknown as GenerateImageInput;
    const r = await generateImageService(malformed, { provider });

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
