import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SERVER_SOURCES, DISCOVERY_REGISTRY_URL, DISCOVERY_REQUEST_TIMEOUT_MS } from "../../shared/constants";
import { discoverServerSources, parseDiscoveryResponse } from "../../shared/server-discovery";

const DEFAULT_URL = "http://youtube-automation.localhost:7873";
const LIVE_URL = "http://live.localhost:49152";
const DEAD_URL = "http://dead.localhost:49153";

function response(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => structuredClone(body),
  } as Response;
}

function serverInfo(baseUrl: string, label: string) {
  const parsed = new URL(baseUrl);
  return {
    channel_name: label,
    channel_short: label.toLowerCase(),
    hostname: parsed.hostname,
    port: Number(parsed.port),
    base_url: baseUrl,
    label,
  };
}

function registryEntry(baseUrl: string, instanceId: string) {
  return {
    instance_id: instanceId,
    expires_at: 130,
    server_info: serverInfo(baseUrl, instanceId),
  };
}

function registry(servers: unknown[]) {
  return { schema_version: 1, ttl_seconds: 30, servers };
}

describe("discovery schema v1", () => {
  it("should accept the Python producer golden fixture without mutating it", () => {
    const fixturePath = fileURLToPath(
      new URL("../../../tests/fixtures/collection_serve_discovery_v1.json", import.meta.url),
    );
    const input: unknown = JSON.parse(readFileSync(fixturePath, "utf8"));
    const before = structuredClone(input);

    const parsed = parseDiscoveryResponse(input);

    expect(parsed).toEqual(before);
    expect(input).toEqual(before);
  });

  it.each([
    { schema_version: 2, ttl_seconds: 30, servers: [] },
    { schema_version: 1, ttl_seconds: "30", servers: [] },
    { schema_version: 1, ttl_seconds: 30, servers: {} },
    registry([{ instance_id: "x", expires_at: 130 }]),
    registry([{ ...registryEntry(LIVE_URL, "x"), expires_at: "130" }]),
    registry([{ ...registryEntry(LIVE_URL, "x"), expires_at: -1 }]),
    registry([{ ...registryEntry(LIVE_URL, "x"), server_info: { ...serverInfo(LIVE_URL, "x"), port: 0 } }]),
    registry([
      {
        ...registryEntry(LIVE_URL, "x"),
        server_info: { ...serverInfo(LIVE_URL, "x"), hostname: "other.localhost" },
      },
    ]),
    registry([registryEntry("https://live.localhost:49152", "x")]),
    registry([registryEntry("http://example.com:49152", "x")]),
    registry([registryEntry(LIVE_URL, "x".repeat(129))]),
    registry(Array.from({ length: 129 }, (_, index) => registryEntry(LIVE_URL, `instance-${index}`))),
  ])("should reject unsupported or malformed producer shapes", (input) => {
    expect(() => parseDiscoveryResponse(input)).toThrow();
  });
});

describe("shared live server discovery", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("should probe only registry entries and keep only validated canonical matches in URL order", async () => {
    const mismatchUrl = "http://mismatch.localhost:49154";
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url === DISCOVERY_REGISTRY_URL) {
        return response(
          200,
          registry([
            registryEntry(DEAD_URL, "dead"),
            registryEntry(LIVE_URL, "live"),
            registryEntry(mismatchUrl, "mismatch"),
            registryEntry(`${DEFAULT_URL}/`, "default-duplicate"),
          ]),
        );
      }
      if (url === `${LIVE_URL}/server-info`) {
        await Promise.resolve();
        return response(200, serverInfo(LIVE_URL, "Live"));
      }
      if (url === `${DEAD_URL}/server-info`) {
        return response(503, {});
      }
      if (url === `${mismatchUrl}/server-info`) {
        return response(200, serverInfo("http://other.localhost:49155", "Other"));
      }
      if (url === `${DEFAULT_URL}/server-info`) {
        return response(200, serverInfo(DEFAULT_URL, "Default"));
      }
      throw new Error(`registry-external URL was fetched: ${url}`);
    });

    const sources = await discoverServerSources({ fetch: fetchMock });

    expect(sources.map(({ url }: { url: string }) => url)).toEqual([DEFAULT_URL, LIVE_URL]);
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      DISCOVERY_REGISTRY_URL,
      `${DEAD_URL}/server-info`,
      `${LIVE_URL}/server-info`,
      `${mismatchUrl}/server-info`,
      `${DEFAULT_URL}/server-info`,
    ]);
  });

  it.each([
    ["HTTP failure", () => Promise.resolve(response(503, {}))],
    ["network failure", () => Promise.reject(new TypeError("connection refused"))],
    ["invalid schema", () => Promise.resolve(response(200, { schema_version: 1, servers: {} }))],
  ])("should return only the permanent default after a registry %s", async (_label, registryFetch) => {
    const fetchMock = vi.fn(registryFetch);

    await expect(discoverServerSources({ fetch: fetchMock })).resolves.toEqual(DEFAULT_SERVER_SOURCES);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("should fall back without probing when the registry exceeds its entry limit", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        response(
          200,
          registry(Array.from({ length: 129 }, (_, index) => registryEntry(LIVE_URL, `instance-${index}`))),
        ),
      ),
    );

    await expect(discoverServerSources({ fetch: fetchMock })).resolves.toEqual(DEFAULT_SERVER_SOURCES);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("should produce deterministic URL order when probes complete in reverse order", async () => {
    const firstUrl = "http://alpha.localhost:49152";
    const secondUrl = "http://zeta.localhost:49153";
    let resolveFirst!: (value: Response) => void;
    let resolveSecond!: (value: Response) => void;
    const firstProbe = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const secondProbe = new Promise<Response>((resolve) => {
      resolveSecond = resolve;
    });
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = String(input);
      if (url === DISCOVERY_REGISTRY_URL) {
        return Promise.resolve(
          response(200, registry([registryEntry(firstUrl, "alpha"), registryEntry(secondUrl, "zeta")])),
        );
      }
      if (url === `${firstUrl}/server-info`) return firstProbe;
      if (url === `${secondUrl}/server-info`) return secondProbe;
      throw new Error(`unexpected fetch: ${url}`);
    });

    const pending = discoverServerSources({ fetch: fetchMock });
    resolveSecond(response(200, serverInfo(secondUrl, "Zeta")));
    await Promise.resolve();
    resolveFirst(response(200, serverInfo(firstUrl, "Alpha")));

    await expect(pending).resolves.toEqual([
      DEFAULT_SERVER_SOURCES[0],
      expect.objectContaining({ url: firstUrl }),
      expect.objectContaining({ url: secondUrl }),
    ]);
  });

  it("should exclude network failures, malformed probes, and unresolved probes at the timeout boundary", async () => {
    vi.useFakeTimers();
    const malformedUrl = "http://malformed.localhost:49154";
    const hangingUrl = "http://hanging.localhost:49155";
    const signals: AbortSignal[] = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url === DISCOVERY_REGISTRY_URL) {
        return Promise.resolve(
          response(
            200,
            registry([
              registryEntry(DEAD_URL, "dead"),
              registryEntry(malformedUrl, "malformed"),
              registryEntry(hangingUrl, "hanging"),
            ]),
          ),
        );
      }
      if (url === `${DEAD_URL}/server-info`) {
        return Promise.reject(new TypeError("connection refused"));
      }
      if (url === `${malformedUrl}/server-info`) {
        return Promise.resolve(response(200, { base_url: malformedUrl }));
      }
      if (url === `${hangingUrl}/server-info`) {
        if (init?.signal) signals.push(init.signal);
        return new Promise<Response>(() => undefined);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    const pending = discoverServerSources({ fetch: fetchMock });
    await vi.advanceTimersByTimeAsync(DISCOVERY_REQUEST_TIMEOUT_MS);

    await expect(pending).resolves.toEqual(DEFAULT_SERVER_SOURCES);
    expect(signals).toHaveLength(1);
    expect(signals[0].aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("should abort an unresolved registry request and ignore its late response", async () => {
    vi.useFakeTimers();
    let resolveRegistry!: (value: Response) => void;
    const registryPromise = new Promise<Response>((resolve) => {
      resolveRegistry = resolve;
    });
    let registrySignal: AbortSignal | undefined;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      if (String(input) !== DISCOVERY_REGISTRY_URL) {
        throw new Error("late registry response started a probe");
      }
      registrySignal = init?.signal ?? undefined;
      return registryPromise;
    });

    const pending = discoverServerSources({ fetch: fetchMock });
    await vi.advanceTimersByTimeAsync(DISCOVERY_REQUEST_TIMEOUT_MS);
    await expect(pending).resolves.toEqual(DEFAULT_SERVER_SOURCES);

    expect(registrySignal?.aborted).toBe(true);
    resolveRegistry(response(200, registry([registryEntry(LIVE_URL, "late")])));
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("should abort a response whose JSON body never arrives", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    const fetchMock = vi.fn((_input: string | URL | Request, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => new Promise<unknown>(() => undefined),
      } as Response);
    });

    const pending = discoverServerSources({ fetch: fetchMock });
    await vi.advanceTimersByTimeAsync(DISCOVERY_REQUEST_TIMEOUT_MS);

    await expect(pending).resolves.toEqual(DEFAULT_SERVER_SOURCES);
    expect(signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
