// Tests for `generateImageService` over the OpenAI provider — the ADR-0003
// Result boundary that wraps `OpenAIImageProvider.generate` (Issue #823).
//
// The generate-path tests now call `generateImageService(input, { provider })`
// and assert on the Result discriminant (`r.ok` / `r.value` / `r.error`). The
// provider is still constructed directly with injected deps (SDK client /
// backoff sleep / image-persist), so its orchestration — aspect-ratio → size
// mapping, b64 decode, edit-vs-generate dispatch, retry — is still exercised
// against in-memory fakes, but observed through the boundary:
//   - provider success                 → ok(value.savedPath)
//   - provider `{ success: false }`    → err(domain "io")     (unprefixed)
//   - provider `config:`-prefixed throw→ err(domain "config")
// Because `createClient` is injected, the default factory's
// `process.env.OPENAI_API_KEY` + `new OpenAI(...)` path is bypassed — no env
// setup is needed. (#822 moved op-based secret resolution to the cli layer.)
//
// Faithful SDK shape (verified against openai-node docs): the client exposes
// `images.generate(params)` and `images.edit(params)`, each returning
//   { data: [ { b64_json: <base64 string> }, ... ] }
// The provider decodes the first item carrying `b64_json` (openai.py:137-144),
// maps aspect ratio → size (16:9→1536x1024, 9:16→1024x1536, openai.py:34-37),
// and rejects unmapped ratios with a `config:`-prefixed Error WITHOUT retrying.

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  generateImageService,
  OpenAIImageProvider,
} from "@youtube-automation/core/image";
import type { GenerateImageInput } from "@youtube-automation/core/image";

type OpenAIDeps = NonNullable<
  ConstructorParameters<typeof OpenAIImageProvider>[1]
>;

// --- fakes ----------------------------------------------------------------

type Behavior = () => unknown;

// Consume the next behavior from a queue; the last entry repeats so a single
// "always fails" behavior covers every retry attempt.
const nextBehavior = (queue: Behavior[] | undefined, i: number): unknown => {
  if (!queue || queue.length === 0) {
    throw new Error("fake openai client: no behavior queued");
  }
  const behavior = queue[Math.min(i, queue.length - 1)];
  if (!behavior) {
    throw new Error("fake openai client: behavior index out of range");
  }
  return behavior();
};

// A fake `openai` client tracking generate/edit calls separately. A throwing
// behavior surfaces synchronously, which the provider's try/catch handles
// identically to a rejected promise.
const makeOpenAIClient = (behaviors: {
  generate?: Behavior[];
  edit?: Behavior[];
}) => {
  const generateCalls: unknown[] = [];
  const editCalls: unknown[] = [];
  let gi = 0;
  let ei = 0;
  const client = {
    images: {
      edit: (params: unknown): Promise<unknown> => {
        editCalls.push(params);
        const i = ei;
        ei += 1;
        return Promise.resolve(nextBehavior(behaviors.edit, i));
      },
      generate: (params: unknown): Promise<unknown> => {
        generateCalls.push(params);
        const i = gi;
        gi += 1;
        return Promise.resolve(nextBehavior(behaviors.generate, i));
      },
    },
  };
  return { client, editCalls, generateCalls };
};

const imageResponse = (...b64s: (string | null)[]) => ({
  data: b64s.map((b64) => (b64 === null ? {} : { b64_json: b64 })),
});

const makeRecorders = () => {
  const sleeps: number[] = [];
  const persisted: { path: string; bytes: Uint8Array }[] = [];
  let clientCreated = 0;
  return {
    clientCreatedCount: () => clientCreated,
    countClient: () => {
      clientCreated += 1;
    },
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
): OpenAIDeps =>
  ({
    createClient: () => {
      recorders.countClient();
      return client;
    },
    persist: recorders.persist,
    sleep: recorders.sleep,
  }) as unknown as OpenAIDeps;

const openaiConfig = {
  aspectRatio: "16:9" as const,
  batch: 1,
  model: "gpt-image-2",
  quality: "high",
};

const request = (
  outputPath: string,
  aspectRatio: string,
  references?: string[]
): GenerateImageInput => ({
  aspectRatio,
  imageSize: "",
  outputPath,
  prompt: "warm acoustic cafe afternoon",
  ...(references ? { references } : {}),
});

let workdir: string;

beforeAll(() => {
  workdir = mkdtempSync(join(tmpdir(), "img-openai-"));
});

afterAll(() => {
  rmSync(workdir, { force: true, recursive: true });
});

// --- identity -------------------------------------------------------------

describe("OpenAIImageProvider identity", () => {
  test("reports its name and the two supported aspect ratios", () => {
    // Given a constructed openai provider (openai.py:43-44)
    const provider = new OpenAIImageProvider(openaiConfig);
    // When reading its metadata
    // Then it identifies as openai with the restricted ratio set
    expect(provider.name).toBe("openai");
    expect([...provider.supportedAspectRatios]).toEqual(["16:9", "9:16"]);
  });
});

// --- success path ---------------------------------------------------------

describe("generateImageService (openai) success", () => {
  test("maps 16:9 → 1536x1024 and persists the decoded b64 image", async () => {
    // Given a generate response with a single b64 image
    const original = new Uint8Array([0xff, 0xd8, 0xff, 5, 6, 7]);
    const base64 = Buffer.from(original).toString("base64");
    const { client, generateCalls } = makeOpenAIClient({
      generate: [() => imageResponse(base64)],
    });
    const recorders = makeRecorders();
    const provider = new OpenAIImageProvider(
      openaiConfig,
      makeDeps(client, recorders)
    );
    const outputPath = join(workdir, "wide.png");

    // When generating at 16:9 through the service
    const r = await generateImageService(request(outputPath, "16:9"), {
      provider,
    });

    // Then the result is ok, the size maps to landscape, bytes decode, and the
    // path is carried in `value`
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.savedPath).toBe(outputPath);
    const [persisted] = recorders.persisted;
    if (!persisted) {
      throw new Error("expected a persisted image");
    }
    expect([...persisted.bytes]).toEqual([...original]);
    const params = generateCalls[0] as {
      size?: unknown;
      model?: unknown;
      n?: unknown;
    };
    expect(params.size).toBe("1536x1024");
    expect(params.model).toBe("gpt-image-2");
    expect(params.n).toBe(1);
    expect(recorders.sleeps).toEqual([]);
  });

  test("maps 9:16 → 1024x1536 for the portrait request", async () => {
    // Given a portrait request and a valid response
    const base64 = Buffer.from(new Uint8Array([1, 2])).toString("base64");
    const { client, generateCalls } = makeOpenAIClient({
      generate: [() => imageResponse(base64)],
    });
    const recorders = makeRecorders();
    const provider = new OpenAIImageProvider(
      { ...openaiConfig, aspectRatio: "9:16" },
      makeDeps(client, recorders)
    );

    // When generating at 9:16 through the service
    const r = await generateImageService(
      request(join(workdir, "tall.png"), "9:16"),
      { provider }
    );

    // Then it succeeds and the size maps to portrait (openai.py:36)
    expect(r.ok).toBe(true);
    const params = generateCalls[0] as { size?: unknown };
    expect(params.size).toBe("1024x1536");
  });

  test("skips response items without b64_json and decodes the first that has it", async () => {
    // Given a response whose first item lacks b64_json (openai.py:140-143)
    const original = new Uint8Array([4, 2]);
    const base64 = Buffer.from(original).toString("base64");
    const { client } = makeOpenAIClient({
      generate: [() => imageResponse(null, base64)],
    });
    const recorders = makeRecorders();
    const provider = new OpenAIImageProvider(
      openaiConfig,
      makeDeps(client, recorders)
    );

    // When generating through the service
    const r = await generateImageService(
      request(join(workdir, "first.png"), "16:9"),
      { provider }
    );

    // Then the second item supplies the decoded bytes
    expect(r.ok).toBe(true);
    const [persisted] = recorders.persisted;
    if (!persisted) {
      throw new Error("expected a persisted image");
    }
    expect([...persisted.bytes]).toEqual([...original]);
  });

  test("uses images.edit (not generate) when references are supplied", async () => {
    // Given a reference image on disk (openai.py:86-96)
    const refPath = join(workdir, "ref.png");
    writeFileSync(refPath, new Uint8Array([0x50, 0x4b]));
    const base64 = Buffer.from(new Uint8Array([8, 8])).toString("base64");
    const { client, editCalls, generateCalls } = makeOpenAIClient({
      edit: [() => imageResponse(base64)],
    });
    const recorders = makeRecorders();
    const provider = new OpenAIImageProvider(
      openaiConfig,
      makeDeps(client, recorders)
    );

    // When generating with a reference image through the service
    const r = await generateImageService(
      request(join(workdir, "edit-out.png"), "16:9", [refPath]),
      { provider }
    );

    // Then it succeeds via the edit endpoint and the generate endpoint is unused
    expect(r.ok).toBe(true);
    expect(editCalls).toHaveLength(1);
    expect(generateCalls).toHaveLength(0);
  });
});

// --- fail-fast on aspect ratio -------------------------------------------

describe("generateImageService (openai) aspect-ratio guard", () => {
  test("maps the unmapped-ratio config error to a config ServiceError without calling the SDK", async () => {
    // Given a request whose ratio is not 16:9 or 9:16 (openai.py:63-67)
    const { client, generateCalls } = makeOpenAIClient({
      generate: [() => imageResponse("ignored")],
    });
    const recorders = makeRecorders();
    const provider = new OpenAIImageProvider(
      openaiConfig,
      makeDeps(client, recorders)
    );

    // When generating at an unsupported ratio through the service
    const r = await generateImageService(
      request(join(workdir, "square.png"), "1:1"),
      { provider }
    );

    // Then the provider's `config:`-prefixed throw becomes a config
    // ServiceError, and it fails fast: no client, no SDK call, no retry wait
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("config");
    expect(r.error.message).toMatch(/^config:/u);
    expect(recorders.clientCreatedCount()).toBe(0);
    expect(generateCalls).toHaveLength(0);
    expect(recorders.sleeps).toEqual([]);
  });
});

// --- retry path -----------------------------------------------------------

describe("generateImageService (openai) retry", () => {
  test("retries on an image-less response and fails after RETRY_MAX attempts", async () => {
    // Given a response with no decodable image (openai.py:106-108)
    const { client, generateCalls } = makeOpenAIClient({
      generate: [() => imageResponse()],
    });
    const recorders = makeRecorders();
    const provider = new OpenAIImageProvider(
      openaiConfig,
      makeDeps(client, recorders)
    );

    // When generating through the service
    const r = await generateImageService(
      request(join(workdir, "empty.png"), "16:9"),
      { provider }
    );

    // Then the unprefixed provider failure maps to an `io` ServiceError after
    // all 3 attempts and two backoff waits
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("io");
    expect(generateCalls).toHaveLength(3);
    expect(recorders.sleeps).toEqual([10_000, 30_000]);
    expect(recorders.persisted).toEqual([]);
  });

  test("retries a transient SDK error then succeeds", async () => {
    // Given one thrown error followed by a valid image (openai.py:125-127)
    const base64 = Buffer.from(new Uint8Array([3, 3, 3])).toString("base64");
    const { client, generateCalls } = makeOpenAIClient({
      generate: [
        () => {
          throw new Error("429 rate limited");
        },
        () => imageResponse(base64),
      ],
    });
    const recorders = makeRecorders();
    const provider = new OpenAIImageProvider(
      openaiConfig,
      makeDeps(client, recorders)
    );

    // When generating through the service
    const r = await generateImageService(
      request(join(workdir, "retry-ok.png"), "16:9"),
      { provider }
    );

    // Then the second attempt wins after a single backoff wait
    expect(r.ok).toBe(true);
    expect(generateCalls).toHaveLength(2);
    expect(recorders.sleeps).toEqual([10_000]);
  });
});
