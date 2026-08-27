export interface LocalFetchRequest {
  url: string;
}

export interface LocalFetchTextResponse {
  body: string;
  contentType: string;
  status: number;
  statusText: string;
}

export interface LocalFetchAssetChunkRequest extends LocalFetchRequest {
  offset: number;
}

export interface LocalFetchAssetChunkResponse {
  base64: string;
  contentType: string;
  totalSize: number;
}

export const ASSET_CHUNK_SIZE = 4 * 1024 * 1024;
const assetCache = new Map<string, Promise<Blob>>();

function assertLoopbackHttpUrl(value: string): URL {
  const url = new URL(value);
  if (
    url.protocol !== "http:" ||
    url.username.length > 0 ||
    url.password.length > 0 ||
    !(
      url.hostname === "localhost" ||
      url.hostname === "127.0.0.1" ||
      url.hostname.endsWith(".localhost")
    )
  ) {
    throw new Error("local fetch URL must use a loopback HTTP host");
  }
  return url;
}

async function fetchLoopback(url: string): Promise<Response> {
  return fetch(assertLoopbackHttpUrl(url), {
    method: "GET",
    redirect: "error",
  });
}

export async function fetchLocalText(
  request: LocalFetchRequest
): Promise<LocalFetchTextResponse> {
  const response = await fetchLoopback(request.url);
  return {
    body: await response.text(),
    contentType: response.headers.get("content-type") ?? "",
    status: response.status,
    statusText: response.statusText,
  };
}

function bytesToBase64(bytes: Uint8Array): string {
  const chunks: string[] = [];
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    chunks.push(
      String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
    );
  }
  return btoa(chunks.join(""));
}

async function loadAsset(url: string): Promise<Blob> {
  const response = await fetchLoopback(url);
  if (!response.ok)
    throw new Error(`asset fetch failed: HTTP ${response.status}`);
  return response.blob();
}

export async function fetchLocalAssetChunk(
  request: LocalFetchAssetChunkRequest
): Promise<LocalFetchAssetChunkResponse> {
  if (!Number.isSafeInteger(request.offset) || request.offset < 0) {
    throw new Error("asset chunk offset must be a non-negative integer");
  }
  const key = assertLoopbackHttpUrl(request.url).href;
  const pending = assetCache.get(key) ?? loadAsset(key);
  assetCache.set(key, pending);
  try {
    const blob = await pending;
    if (request.offset > blob.size)
      throw new Error("asset chunk offset exceeds asset size");
    const end = Math.min(request.offset + ASSET_CHUNK_SIZE, blob.size);
    const bytes = new Uint8Array(
      await blob.slice(request.offset, end).arrayBuffer()
    );
    if (end >= blob.size) assetCache.delete(key);
    return {
      base64: bytesToBase64(bytes),
      contentType: blob.type,
      totalSize: blob.size,
    };
  } catch (error) {
    assetCache.delete(key);
    throw error;
  }
}
