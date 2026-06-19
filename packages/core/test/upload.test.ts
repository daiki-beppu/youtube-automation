// Tests for uploadVideoService (issue #837) — the single atomic upload service
// that ports the Python video-upload core (utils/upload_core.py +
// agents/youtube_auto_uploader.py) to an ADR-0003 Result boundary.
//
// The service returns Promise<Result<UploadOutput, ServiceError>>: it never
// throws across its boundary and maps every failure to a ServiceError. The
// googleapis YouTube Data API client (youtube_v3.Youtube) is reached through a
// `deps` injection seam (mirroring analytics/video/service.ts and
// image/service.ts), so these unit tests run with a fake client and never touch
// the network or perform a real upload.
//
// Seam contract (documented here so the implementation matches the fakes):
//   deps.youtube.videos.insert(params) -> { data: { id?: string } }
//     params: { part, requestBody: { snippet, status, localizations? },
//               media: { body: <video stream> } }
//   deps.youtube.thumbnails.set(params) -> { data: ... }
//     params: { videoId, media: { body: <thumbnail bytes/stream> } }
//   deps.sleep?: a backoff injection point (no-op in tests) so the 5xx retry
//     path resolves instantly instead of waiting the real 10s/30s.
// On a 429 the insert rejects with a gaxios-shaped error
//   { response: { status: 429, headers: { "retry-after": "<seconds>" } } }
// which the service promotes to a quota ServiceError (retryAfterSeconds parsed
// from the Retry-After header) — non-retryable per the ADR-0003 retry規約 (#959).
//
// Atomicity: a successful call performs videos.insert (media + metadata) then,
// only when a thumbnail is supplied, thumbnails.set — in that order, within one
// service call. The metadata→requestBody mapping (snippet/status/localizations,
// publishAt UTC normalization, AI-disclosure defaults) ports
// youtube_auto_uploader.py:144-198 and is asserted directly on the captured
// insert params.

import { afterAll, beforeAll, describe, expect, spyOn, test } from "bun:test";
import { randomFillSync } from "node:crypto";
import {
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { uploadVideoService } from "@youtube-automation/core/upload";

// Derive input / deps shapes from the service signature so the test does not
// hard-code the exported type names (analytics-video.test.ts:33-36).
type UploadInput = Parameters<typeof uploadVideoService>[0];
type UploadDeps = NonNullable<Parameters<typeof uploadVideoService>[1]>;

// YouTube's hard cap on thumbnail size; the service must compress above it and
// pass smaller files through untouched (upload_policy.py:11).
const MAX_THUMBNAIL_BYTES = 2_097_152;

// --- fakes ----------------------------------------------------------------

type Behavior = () => unknown;

// A fake youtube_v3 client. `videos.insert` runs the supplied behavior (a
// value-returning or throwing thunk) and records every params bag; the same
// behavior repeats so a single "always 500" thunk covers every retry attempt.
// `thumbnails.set` defaults to success because most tests do not exercise its
// failure mode. `order` records the call sequence so the atomic insert→thumbnail
// ordering is assertable.
const makeYouTubeClient = (opts: {
  insert: Behavior;
  thumbnails?: Behavior;
}) => {
  const insertCalls: unknown[] = [];
  const thumbnailCalls: unknown[] = [];
  const order: string[] = [];
  const thumbnailBehavior = opts.thumbnails ?? (() => ({ data: {} }));
  const client = {
    thumbnails: {
      set: (params: unknown) => {
        thumbnailCalls.push(params);
        order.push("thumbnails.set");
        return Promise.resolve().then(thumbnailBehavior);
      },
    },
    videos: {
      insert: (params: unknown) => {
        insertCalls.push(params);
        order.push("videos.insert");
        return Promise.resolve().then(opts.insert);
      },
    },
  };
  return { client, insertCalls, order, thumbnailCalls };
};

// A successful insert response carrying the new video id.
const insertSuccess = (id: string) => () => ({ data: { id } });

// A gaxios-shaped 429 carrying a Retry-After hint, mirroring the rate-limit
// surface the service promotes to a quota ServiceError.
const quotaError = (): Error =>
  Object.assign(new Error("videos.insert: quota exceeded"), {
    response: { headers: { "retry-after": "30" }, status: 429 },
  });

// A 429 whose Retry-After header is empty — there is no usable hint, so the
// service must leave retryAfterSeconds undefined (not coerce "" to 0).
const quotaErrorEmptyRetryAfter = (): Error =>
  Object.assign(new Error("videos.insert: quota exceeded"), {
    response: { headers: { "retry-after": "" }, status: 429 },
  });

// A gaxios-shaped non-429 server error. defaultShouldRetry classifies it as
// retryable, so the service maps the exhausted failure to domain "api".
const serverError = (): Error =>
  Object.assign(new Error("internal server error"), {
    response: { status: 500 },
  });

// A no-op backoff sleep so the retry path resolves instantly instead of waiting
// the real 10s/30s (analytics-video.test.ts:60).
const noSleep = (): Promise<void> => Promise.resolve();

const makeDeps = (client: unknown, sleep?: () => Promise<void>): UploadDeps =>
  ({
    youtube: client,
    ...(sleep === undefined ? {} : { sleep }),
  }) as unknown as UploadDeps;

// Reads the bytes the service handed to videos.insert / thumbnails.set as
// media.body. A stream (fs.ReadStream / Readable) is drained the same way the
// real resumable upload would consume it; a Buffer/Uint8Array is also accepted
// so the assertion pins the byte content, not the container type.
const collectMediaBytes = async (params: unknown): Promise<Uint8Array> => {
  const { media } = params as { media?: { body?: unknown } };
  const body = media?.body;
  if (body === undefined || body === null) {
    throw new Error("media.body was missing");
  }
  if (Buffer.isBuffer(body)) {
    return new Uint8Array(body);
  }
  if (body instanceof Uint8Array) {
    return body;
  }
  if (
    typeof (body as AsyncIterable<unknown>)[Symbol.asyncIterator] === "function"
  ) {
    const chunks: Buffer[] = [];
    for await (const chunk of body as AsyncIterable<Uint8Array>) {
      chunks.push(Buffer.from(chunk));
    }
    return new Uint8Array(Buffer.concat(chunks));
  }
  throw new Error("unsupported media.body shape");
};

// Reads the requestBody (snippet/status/localizations) off a captured insert
// call so the metadata→body mapping can be asserted directly.
const insertBody = (insertCalls: readonly unknown[]) => {
  const params = insertCalls[0] as { part?: unknown; requestBody?: unknown };
  const requestBody = (params.requestBody ?? {}) as {
    localizations?: unknown;
    snippet?: Record<string, unknown>;
    status?: Record<string, unknown>;
  };
  // `part` may be an array (plan: [...Object.keys(body)]) or a comma string
  // (Python parity); normalize so the assertion tolerates both.
  const part = Array.isArray(params.part)
    ? params.part.join(",")
    : String(params.part ?? "");
  return {
    localizations: requestBody.localizations,
    part,
    snippet: requestBody.snippet ?? {},
    status: requestBody.status ?? {},
  };
};

// --- fixtures (real temp files; no read seam, per plan) --------------------

let workdir: string;
let videoPath: string;
let smallThumbPath: string;
let smallThumbBytes: Uint8Array;

beforeAll(() => {
  workdir = mkdtempSync(join(tmpdir(), "upload-"));

  // A real (tiny) video file so the service's existence check passes; the fake
  // insert never consumes its bytes.
  videoPath = join(workdir, "complete.mp4");
  writeFileSync(videoPath, Buffer.from("fake-mp4-bytes"));

  // A thumbnail comfortably under 2MB: the service must pass it through without
  // re-encoding (upload_policy.py:33-34 needs_compression=False).
  smallThumbPath = join(workdir, "thumb-small.jpg");
  smallThumbBytes = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4, 5]);
  writeFileSync(smallThumbPath, smallThumbBytes);
});

afterAll(() => {
  rmSync(workdir, { force: true, recursive: true });
});

// A minimal valid metadata bag. Values stay well within YouTube's length caps,
// so the over-limit handling (title rejects; description/tags truncate to the
// YouTube cap — see schema.ts:37-40) is pinned by the dedicated truncation tests
// below, never by these.
const baseMetadata = {
  description: "calm lo-fi beats for late-night study",
  tags: ["lofi", "study", "chill"],
  title: "Late Night Lo-Fi Study Mix",
};

const baseInput = (overrides?: Partial<UploadInput>): UploadInput =>
  ({
    file: videoPath,
    metadata: baseMetadata,
    ...overrides,
  }) as UploadInput;

// --- success: video only ---------------------------------------------------

describe("uploadVideoService success (no thumbnail)", () => {
  test("inserts the video and returns ok with the new id and thumbnailSet false", async () => {
    // Given an insert that returns a fresh video id and no thumbnail in the input
    const { client, insertCalls, thumbnailCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_abc123"),
    });

    // When uploading
    const r = await uploadVideoService(baseInput(), makeDeps(client));

    // Then it succeeds, carries the id, and reports no thumbnail was set
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.videoId).toBe("vid_abc123");
    expect(r.value.thumbnailSet).toBe(false);

    // And the upload is one insert with no thumbnail call (thumbnail optional)
    expect(insertCalls).toHaveLength(1);
    expect(thumbnailCalls).toEqual([]);
  });

  test("maps metadata into the insert requestBody snippet/status and part", async () => {
    // Given a successful insert
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_1"),
    });

    // When uploading with the base metadata
    const r = await uploadVideoService(baseInput(), makeDeps(client));

    // Then it succeeds and the metadata lands on snippet/status (parity with
    // youtube_auto_uploader.py:176-186)
    expect(r.ok).toBe(true);
    const { part, snippet, status } = insertBody(insertCalls);
    expect(snippet.title).toBe("Late Night Lo-Fi Study Mix");
    expect(snippet.description).toBe("calm lo-fi beats for late-night study");
    expect(snippet.tags).toEqual(["lofi", "study", "chill"]);

    // And part declares the body sections being written
    expect(part).toContain("snippet");
    expect(part).toContain("status");

    // And the upload is not scheduled, so no publishAt is emitted
    expect(status.publishAt).toBeUndefined();
  });

  test("applies the current-behavior defaults when metadata omits them", async () => {
    // Given a successful insert and metadata with only the required fields
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_def"),
    });

    // When uploading
    const r = await uploadVideoService(baseInput(), makeDeps(client));

    // Then the music category, language and privacy defaults apply
    // (youtube_auto_uploader.py:156,181-183)
    expect(r.ok).toBe(true);
    const { snippet, status } = insertBody(insertCalls);
    expect(snippet.categoryId).toBe("10");
    expect(snippet.defaultLanguage).toBe("en");
    expect(snippet.defaultAudioLanguage).toBe("en");
    expect(status.privacyStatus).toBe("private");

    // And the AI-disclosure defaults reproduce today's behavior: synthetic media
    // declared true, made-for-kids false (channel_settings.py:176,185-186 / #603)
    expect(status.containsSyntheticMedia).toBe(true);
    expect(status.selfDeclaredMadeForKids).toBe(false);
  });

  test("carries localizations into the insert body when supplied", async () => {
    // Given metadata that includes per-locale title/description overrides
    const localizations = {
      ja: { description: "夜の勉強用 lo-fi", title: "深夜の Lo-Fi" },
    };
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_loc"),
    });

    // When uploading
    const r = await uploadVideoService(
      baseInput({
        metadata: { ...baseMetadata, localizations },
      } as Partial<UploadInput>),
      makeDeps(client)
    );

    // Then the localizations ride along on the request body
    // (youtube_auto_uploader.py:188-189)
    expect(r.ok).toBe(true);
    const { localizations: sent, part } = insertBody(insertCalls);
    expect(sent).toEqual(localizations);
    expect(part).toContain("localizations");
  });
});

// --- over-limit truncation (description / tags) -----------------------------

describe("uploadVideoService over-limit truncation", () => {
  test("truncates a description longer than 5000 chars to the YouTube cap", async () => {
    // Given a description that exceeds YouTube's 5000-char snippet cap
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_desc_trunc"),
    });
    const input = baseInput({
      metadata: { ...baseMetadata, description: "d".repeat(5001) },
    } as Partial<UploadInput>);

    // When uploading
    const r = await uploadVideoService(input, makeDeps(client));

    // Then it succeeds and the description is truncated to exactly 5000 chars
    // (truncate, not reject — schema.ts:37-40 / youtube_auto_uploader.py parity)
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    const { snippet } = insertBody(insertCalls);
    expect(String(snippet.description)).toHaveLength(5000);
  });

  test("truncates a tag list longer than 50 items to the first 50", async () => {
    // Given more tags than YouTube's 50-tag cap allows
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_tags_trunc"),
    });
    const tags = Array.from({ length: 60 }, (_, i) => `tag${i}`);
    const input = baseInput({
      metadata: { ...baseMetadata, tags },
    } as Partial<UploadInput>);

    // When uploading
    const r = await uploadVideoService(input, makeDeps(client));

    // Then it succeeds and only the first 50 tags reach the insert body
    // (truncate, not reject — schema.ts:37-40)
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    const { snippet } = insertBody(insertCalls);
    expect(snippet.tags).toEqual(tags.slice(0, 50));
  });
});

// --- scheduled publish (publishAt normalization) ---------------------------

describe("uploadVideoService scheduled publish", () => {
  test("normalizes a TZ-offset publishAt to a UTC Z instant and forces privacy private", async () => {
    // Given a publishAt with a +09:00 offset and an explicit public privacy
    // status the scheduler must override (youtube_auto_uploader.py:164-167)
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_sched"),
    });
    const input = baseInput({
      metadata: {
        ...baseMetadata,
        privacyStatus: "public",
        publishAt: "2026-06-15T20:00:00+09:00",
      },
    } as Partial<UploadInput>);

    // When uploading
    const r = await uploadVideoService(input, makeDeps(client));

    // Then privacy is forced to private (scheduled publish requirement)
    expect(r.ok).toBe(true);
    const { status } = insertBody(insertCalls);
    expect(status.privacyStatus).toBe("private");

    // And publishAt is the same instant expressed as UTC, Z-terminated (#647)
    const publishAt = String(status.publishAt);
    expect(publishAt.endsWith("Z")).toBe(true);
    expect(new Date(publishAt).getTime()).toBe(
      new Date("2026-06-15T11:00:00Z").getTime()
    );
  });

  test("keeps a Z-terminated publishAt as a UTC Z instant", async () => {
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_sched_z"),
    });
    const input = baseInput({
      metadata: {
        ...baseMetadata,
        publishAt: "2025-06-19T06:30:00Z",
      },
    } as Partial<UploadInput>);

    const r = await uploadVideoService(input, makeDeps(client));

    expect(r.ok).toBe(true);
    const { status } = insertBody(insertCalls);
    expect(status.publishAt).toBe("2025-06-19T06:30:00Z");
  });

  test("keeps an invalid timezone-offset publishAt unchanged", async () => {
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_sched_invalid_offset"),
    });
    const dateParseSpy = spyOn(Date, "parse");
    const publishAt = "2025-06-19T15:30:00+25:99";
    const input = baseInput({
      metadata: {
        ...baseMetadata,
        publishAt,
      },
    } as Partial<UploadInput>);

    try {
      const r = await uploadVideoService(input, makeDeps(client));

      expect(r.ok).toBe(true);
      const { status } = insertBody(insertCalls);
      expect(status.publishAt).toBe(publishAt);
      expect(dateParseSpy).not.toHaveBeenCalled();
    } finally {
      dateParseSpy.mockRestore();
    }
  });

  test("keeps a naive datetime publishAt unchanged", async () => {
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_sched_naive"),
    });
    const publishAt = "2025-06-19T15:30:00";
    const input = baseInput({
      metadata: {
        ...baseMetadata,
        publishAt,
      },
    } as Partial<UploadInput>);

    const r = await uploadVideoService(input, makeDeps(client));

    expect(r.ok).toBe(true);
    const { status } = insertBody(insertCalls);
    expect(status.publishAt).toBe(publishAt);
  });

  test("publishes immediately (public, no publishAt) when no schedule is given", async () => {
    // Given a public privacy status and no publishAt
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_now"),
    });
    const input = baseInput({
      metadata: { ...baseMetadata, privacyStatus: "public" },
    } as Partial<UploadInput>);

    // When uploading
    const r = await uploadVideoService(input, makeDeps(client));

    // Then public is preserved and no publishAt is added (immediate publish)
    expect(r.ok).toBe(true);
    const { status } = insertBody(insertCalls);
    expect(status.privacyStatus).toBe("public");
    expect(status.publishAt).toBeUndefined();
  });
});

// --- success: with thumbnail ------------------------------------------------

describe("uploadVideoService thumbnail handling", () => {
  test("sets a sub-2MB thumbnail after the insert and passes its bytes through unchanged", async () => {
    // Given a successful insert and a small (sub-2MB) thumbnail on disk
    const { client, insertCalls, order, thumbnailCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_thumb"),
    });

    // When uploading with that thumbnail
    const r = await uploadVideoService(
      baseInput({ thumbnail: smallThumbPath }),
      makeDeps(client)
    );

    // Then it succeeds and reports the thumbnail was set
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.thumbnailSet).toBe(true);

    // And the atomic order is insert first, then thumbnails.set
    expect(insertCalls).toHaveLength(1);
    expect(thumbnailCalls).toHaveLength(1);
    expect(order).toEqual(["videos.insert", "thumbnails.set"]);

    // And, being under 2MB, the file is forwarded untouched (no re-encode)
    const sent = await collectMediaBytes(thumbnailCalls[0]);
    expect([...sent]).toEqual([...smallThumbBytes]);
  });

  test("targets the freshly created video id when setting the thumbnail", async () => {
    // Given an insert that returns a specific id
    const { client, thumbnailCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_target"),
    });

    // When uploading with a thumbnail
    const r = await uploadVideoService(
      baseInput({ thumbnail: smallThumbPath }),
      makeDeps(client)
    );

    // Then thumbnails.set is scoped to that same video id
    expect(r.ok).toBe(true);
    const params = thumbnailCalls[0] as { videoId?: unknown };
    expect(params.videoId).toBe("vid_target");
  });

  test("compresses an over-2MB thumbnail below the cap before uploading", async () => {
    // Given a real >2MB image fixture (sharp is a core dep added by this issue).
    // High-entropy noise keeps the PNG large while a low-quality JPEG re-encode
    // brings it well under the cap.
    const sharpModule = await import("sharp");
    const sharp = sharpModule.default;
    const width = 1100;
    const height = 1100;
    const raw = Buffer.allocUnsafe(width * height * 3);
    randomFillSync(raw);
    const bigPng = await sharp(raw, { raw: { channels: 3, height, width } })
      .png()
      .toBuffer();
    const bigThumbPath = join(workdir, "thumb-big.png");
    writeFileSync(bigThumbPath, bigPng);

    // Sanity: the source genuinely exceeds the cap, so compression must run
    expect(statSync(bigThumbPath).size).toBeGreaterThan(MAX_THUMBNAIL_BYTES);

    const { client, thumbnailCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_big"),
    });

    // When uploading with the oversized thumbnail
    const r = await uploadVideoService(
      baseInput({ thumbnail: bigThumbPath }),
      makeDeps(client)
    );

    // Then it succeeds and the bytes handed to thumbnails.set are compressed:
    // at or under the cap, and smaller than the source (compression happened)
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.thumbnailSet).toBe(true);
    const sent = await collectMediaBytes(thumbnailCalls[0]);
    expect(sent.byteLength).toBeLessThanOrEqual(MAX_THUMBNAIL_BYTES);
    expect(sent.byteLength).toBeLessThan(statSync(bigThumbPath).size);
  });
});

// --- thumbnail failure is best-effort (insert already succeeded) ------------

describe("uploadVideoService thumbnail failure is best-effort", () => {
  test("keeps the created video (ok, thumbnailSet false) when thumbnails.set fails, without re-inserting", async () => {
    // Given an insert that succeeds but a thumbnails.set that rejects (the video
    // already exists on YouTube once insert returned an id)
    const { client, insertCalls, order, thumbnailCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_thumb_fail"),
      thumbnails: () => {
        throw serverError();
      },
    });

    // When uploading with a thumbnail
    const r = await uploadVideoService(
      baseInput({ thumbnail: smallThumbPath }),
      makeDeps(client)
    );

    // Then the upload still succeeds: the created video id is preserved (never
    // discarded) and thumbnailSet reports the thumbnail did not take
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.videoId).toBe("vid_thumb_fail");
    expect(r.value.thumbnailSet).toBe(false);

    // And the video was inserted exactly once — the failed thumbnail must not
    // trigger a re-insert (which would duplicate the upload)
    expect(insertCalls).toHaveLength(1);
    expect(thumbnailCalls).toHaveLength(1);
    expect(order).toEqual(["videos.insert", "thumbnails.set"]);
  });

  test("keeps the created video (ok, thumbnailSet false) when the thumbnail cannot be compressed", async () => {
    // Given an over-2MB thumbnail whose bytes are not a decodable image, so the
    // sharp compression pass throws before any thumbnails.set call (圧縮不能)
    const undecodableThumbPath = join(workdir, "thumb-undecodable.bin");
    writeFileSync(
      undecodableThumbPath,
      Buffer.alloc(MAX_THUMBNAIL_BYTES + 1024, 0x7f)
    );
    expect(statSync(undecodableThumbPath).size).toBeGreaterThan(
      MAX_THUMBNAIL_BYTES
    );

    const { client, insertCalls, thumbnailCalls } = makeYouTubeClient({
      insert: insertSuccess("vid_compress_fail"),
    });

    // When uploading with that thumbnail
    const r = await uploadVideoService(
      baseInput({ thumbnail: undecodableThumbPath }),
      makeDeps(client)
    );

    // Then the video upload still succeeds with the id preserved and the
    // thumbnail left unset (compression failure is absorbed, not propagated)
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.videoId).toBe("vid_compress_fail");
    expect(r.value.thumbnailSet).toBe(false);

    // And the failure happened during compression, before thumbnails.set, with
    // a single insert
    expect(insertCalls).toHaveLength(1);
    expect(thumbnailCalls).toEqual([]);
  });
});

// --- quota path -------------------------------------------------------------

describe("uploadVideoService quota", () => {
  test("maps a 429 to a quota ServiceError carrying retryAfterSeconds without retrying", async () => {
    // Given an insert that rejects with a gaxios-shaped 429 + Retry-After header
    const { client, insertCalls, thumbnailCalls } = makeYouTubeClient({
      insert: () => {
        throw quotaError();
      },
    });

    // When uploading
    const r = await uploadVideoService(
      baseInput({ thumbnail: smallThumbPath }),
      makeDeps(client)
    );

    // Then the boundary returns err(domain "quota") — it never throws across itself
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a quota failure");
    }
    expect(r.error.domain).toBe("quota");
    if (r.error.domain === "quota") {
      expect(r.error.httpStatus).toBe(429);
      expect(r.error.retryAfterSeconds).toBe(30);
    }

    // And quota is non-retryable: insert ran exactly once and the thumbnail
    // (which would have followed a successful insert) was never attempted
    expect(insertCalls).toHaveLength(1);
    expect(thumbnailCalls).toEqual([]);
  });

  test("leaves retryAfterSeconds undefined when the Retry-After header is empty", async () => {
    // Given a 429 whose Retry-After header is an empty string (no usable hint)
    const { client } = makeYouTubeClient({
      insert: () => {
        throw quotaErrorEmptyRetryAfter();
      },
    });

    // When uploading
    const r = await uploadVideoService(baseInput(), makeDeps(client));

    // Then it is still a quota error, but "" is not coerced to 0 seconds
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a quota failure");
    }
    expect(r.error.domain).toBe("quota");
    if (r.error.domain === "quota") {
      expect(r.error.retryAfterSeconds).toBeUndefined();
    }
  });
});

// --- api error path (5xx with retry) ---------------------------------------

describe("uploadVideoService api error", () => {
  test('maps a persistent 5xx to domain "api" after exhausting the default 3 attempts', async () => {
    // Given an insert that always rejects with a gaxios-shaped 500
    const { client, insertCalls } = makeYouTubeClient({
      insert: () => {
        throw serverError();
      },
    });

    // When uploading with a no-op backoff sleep injected
    const r = await uploadVideoService(baseInput(), makeDeps(client, noSleep));

    // Then the boundary returns err(domain "api") carrying the HTTP status
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected an api failure");
    }
    expect(r.error.domain).toBe("api");
    if (r.error.domain === "api") {
      expect(r.error.httpStatus).toBe(500);
    }

    // And unlike quota, a 5xx is retryable: insert ran the default 3 attempts
    // (withRetry is the single retry owner — no self-rolled backoff loop)
    expect(insertCalls).toHaveLength(3);
  });

  test("re-sends the full video body on a 5xx retry instead of an exhausted stream", async () => {
    // The default upload is resumable=true, so media.body is a one-shot
    // fs.ReadStream that a real resumable upload consumes on each attempt.
    // Reusing one stream across retries would re-send an empty body on attempt
    // 2. This fake drains the body exactly as the real client would and records
    // the bytes seen per attempt, so a once-consumed stream surfaces as a short
    // body on the retry rather than hiding behind a fake that never reads it.
    const videoBytes = new Uint8Array(readFileSync(videoPath));
    const drainedPerAttempt: Uint8Array[] = [];
    let attempt = 0;
    const client = {
      thumbnails: { set: () => Promise.resolve({ data: {} }) },
      videos: {
        insert: async (params: unknown) => {
          drainedPerAttempt.push(await collectMediaBytes(params));
          attempt += 1;
          if (attempt === 1) {
            throw serverError();
          }
          return { data: { id: "vid_retry_body" } };
        },
      },
    };

    // When uploading (5xx on attempt 1, success on attempt 2)
    const r = await uploadVideoService(baseInput(), makeDeps(client, noSleep));

    // Then the upload retries past the 500 and succeeds
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.videoId).toBe("vid_retry_body");

    // And BOTH attempts received the complete file: the retry is a fresh stream,
    // not an exhausted one re-sending an empty body
    expect(drainedPerAttempt).toHaveLength(2);
    for (const sent of drainedPerAttempt) {
      expect([...sent]).toEqual([...videoBytes]);
    }
  });
});

// --- io errors --------------------------------------------------------------

describe("uploadVideoService io errors", () => {
  test('maps a missing video file to domain "io" without calling insert', async () => {
    // Given a file path that does not exist on disk
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("never"),
    });
    const input = baseInput({ file: join(workdir, "does-not-exist.mp4") });

    // When uploading
    const r = await uploadVideoService(input, makeDeps(client));

    // Then the existence check fails fast as an io error and insert is untouched
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected an io failure");
    }
    expect(r.error.domain).toBe("io");
    expect(insertCalls).toEqual([]);
  });

  test('maps an insert response missing the video id to domain "io"', async () => {
    // Given an insert that resolves successfully but without an id
    // (upload_core.py:216-219 treats a missing id as a failure)
    const { client } = makeYouTubeClient({
      insert: () => ({ data: {} }),
    });

    // When uploading
    const r = await uploadVideoService(baseInput(), makeDeps(client));

    // Then the unprefixed throw surfaces as an io error
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected an io failure");
    }
    expect(r.error.domain).toBe("io");
  });
});

// --- input validation -------------------------------------------------------

describe("uploadVideoService input validation", () => {
  test("rejects an unknown input key via the strict schema without uploading", async () => {
    // Given a client that would succeed if it were ever reached
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("never"),
    });
    // And an input carrying an extra key the `.strict()` schema must reject
    const malformed = {
      ...baseInput(),
      unexpected: true,
    } as unknown as UploadInput;

    // When uploading the malformed input
    const r = await uploadVideoService(malformed, makeDeps(client));

    // Then the boundary parses first: a validation error, insert never invoked
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(insertCalls).toEqual([]);
  });

  test("rejects a title longer than 100 characters", async () => {
    // Given a title that exceeds YouTube's 100-char cap
    // (youtube_auto_uploader.py:146-147 raises ValueError)
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("never"),
    });
    const input = baseInput({
      metadata: { ...baseMetadata, title: "x".repeat(101) },
    } as Partial<UploadInput>);

    // When uploading
    const r = await uploadVideoService(input, makeDeps(client));

    // Then the over-long title fails validation before any upload
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(insertCalls).toEqual([]);
  });

  test("rejects an unknown privacyStatus value", async () => {
    // Given a privacyStatus outside the allowed enum
    const { client, insertCalls } = makeYouTubeClient({
      insert: insertSuccess("never"),
    });
    const input = baseInput({
      metadata: { ...baseMetadata, privacyStatus: "semi-public" },
    } as unknown as Partial<UploadInput>);

    // When uploading
    const r = await uploadVideoService(input, makeDeps(client));

    // Then the enum constraint fails validation before any upload
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(insertCalls).toEqual([]);
  });

  test("accepts resumable: false and still uploads", async () => {
    // Given a valid input that opts out of resumable upload
    const { client } = makeYouTubeClient({
      insert: insertSuccess("vid_nonresumable"),
    });

    // When uploading with resumable disabled
    const r = await uploadVideoService(
      baseInput({ resumable: false }),
      makeDeps(client)
    );

    // Then the schema accepts the option and the upload succeeds
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.videoId).toBe("vid_nonresumable");
  });
});
