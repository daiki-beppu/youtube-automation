import { parseServerInfo, type ServerInfo } from "./api";
import {
  DEFAULT_SERVER_SOURCES,
  DISCOVERY_REGISTRY_URL,
  DISCOVERY_REQUEST_TIMEOUT_MS,
  DISCOVERY_SCHEMA_VERSION,
  type LocalServerSource,
  normalizeServerUrl,
  SERVER_INFO_ROUTE,
  serverSourceIdFromUrl,
} from "./constants";

export interface DiscoveryEntry {
  instance_id: string;
  expires_at: number;
  server_info: ServerInfo;
}

export interface DiscoveryResponse {
  schema_version: number;
  ttl_seconds: number;
  servers: DiscoveryEntry[];
}

const MAX_INSTANCE_ID_LENGTH = 128;
const MAX_REGISTRY_ENTRIES = 128;

function record(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new Error(`${name} must be object`);
  return value as Record<string, unknown>;
}

function nonEmptyString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0)
    throw new Error(`${name} must be non-empty string`);
  if (value.length > MAX_INSTANCE_ID_LENGTH)
    throw new Error(
      `${name} must be at most ${MAX_INSTANCE_ID_LENGTH} characters`
    );
  return value;
}

function validateLoopbackUrl(value: string): string {
  const parsed = new URL(value);
  if (
    parsed.protocol !== "http:" ||
    parsed.username ||
    parsed.password ||
    !parsed.port ||
    !(
      parsed.hostname === "localhost" ||
      parsed.hostname === "127.0.0.1" ||
      parsed.hostname.endsWith(".localhost")
    ) ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("base_url must be loopback HTTP");
  }
  return normalizeServerUrl(value);
}

export function parseDiscoveryResponse(value: unknown): DiscoveryResponse {
  const source = record(value, "discovery response");
  if (source.schema_version !== DISCOVERY_SCHEMA_VERSION)
    throw new Error("unsupported discovery schema");
  if (
    typeof source.ttl_seconds !== "number" ||
    !Number.isFinite(source.ttl_seconds) ||
    source.ttl_seconds <= 0
  ) {
    throw new Error("ttl_seconds must be positive number");
  }
  if (!Array.isArray(source.servers)) throw new Error("servers must be array");
  if (source.servers.length > MAX_REGISTRY_ENTRIES)
    throw new Error(
      `servers must contain at most ${MAX_REGISTRY_ENTRIES} entries`
    );
  const servers = source.servers.map((value, index) => {
    const entry = record(value, `servers[${index}]`);
    if (
      typeof entry.expires_at !== "number" ||
      !Number.isFinite(entry.expires_at)
    ) {
      throw new Error(`servers[${index}].expires_at must be number`);
    }
    const info = parseServerInfo(entry.server_info);
    const baseUrl = validateLoopbackUrl(info.base_url);
    const parsedUrl = new URL(baseUrl);
    if (entry.expires_at <= 0) {
      throw new Error(`servers[${index}].expires_at must be positive number`);
    }
    if (
      info.hostname !== parsedUrl.hostname ||
      info.port !== Number(parsedUrl.port)
    ) {
      throw new Error(`servers[${index}].server_info must match base_url`);
    }
    return {
      instance_id: nonEmptyString(
        entry.instance_id,
        `servers[${index}].instance_id`
      ),
      expires_at: entry.expires_at,
      server_info: info,
    };
  });
  return {
    schema_version: DISCOVERY_SCHEMA_VERSION,
    ttl_seconds: source.ttl_seconds,
    servers,
  };
}

type Fetch = (
  input: string | URL | Request,
  init?: RequestInit
) => Promise<Response>;

async function fetchJsonWithTimeout(
  fetcher: Fetch,
  url: string
): Promise<{ response: Response; body: unknown }> {
  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_, reject) => {
    timeout = setTimeout(() => {
      controller.abort();
      reject(new Error("discovery request timed out"));
    }, DISCOVERY_REQUEST_TIMEOUT_MS);
  });
  try {
    return await Promise.race([
      fetcher(url, { signal: controller.signal }).then(async (response) => ({
        response,
        body: await response.json(),
      })),
      expired,
    ]);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

async function validatedSource(
  fetcher: Fetch,
  entry: DiscoveryEntry
): Promise<LocalServerSource | undefined> {
  const registeredUrl = normalizeServerUrl(entry.server_info.base_url);
  try {
    const { response, body } = await fetchJsonWithTimeout(
      fetcher,
      `${registeredUrl}${SERVER_INFO_ROUTE}`
    );
    if (!response.ok) return undefined;
    const info = parseServerInfo(body);
    if (normalizeServerUrl(info.base_url) !== registeredUrl) return undefined;
    return {
      id: serverSourceIdFromUrl(registeredUrl),
      label: info.label,
      url: registeredUrl,
    };
  } catch {
    return undefined;
  }
}

export async function discoverServerSources(
  options: { fetch?: Fetch } = {}
): Promise<LocalServerSource[]> {
  const fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  try {
    const { response, body } = await fetchJsonWithTimeout(
      fetcher,
      DISCOVERY_REGISTRY_URL
    );
    if (!response.ok) return [...DEFAULT_SERVER_SOURCES];
    const registry = parseDiscoveryResponse(body);
    const probed = await Promise.all(
      registry.servers.map((entry) => validatedSource(fetcher, entry))
    );
    const byUrl = new Map(
      DEFAULT_SERVER_SOURCES.map((source) => [
        normalizeServerUrl(source.url),
        source,
      ])
    );
    for (const source of probed.filter(
      (source): source is LocalServerSource => source !== undefined
    )) {
      byUrl.set(source.url, source);
    }
    const [defaultSource, ...dynamic] = [...byUrl.values()];
    return [
      defaultSource,
      ...dynamic.sort((left, right) => left.url.localeCompare(right.url)),
    ];
  } catch {
    return [...DEFAULT_SERVER_SOURCES];
  }
}
