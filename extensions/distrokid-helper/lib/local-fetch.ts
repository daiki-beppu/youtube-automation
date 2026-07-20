import { encodeAsset, type SerializedAsset } from "./asset-transfer";

export interface LocalFetchRequest {
  url: string;
}

export interface LocalFetchTextResponse {
  body: string;
  contentType: string;
  status: number;
  statusText: string;
}

export interface LocalFetchAssetRequest extends LocalFetchRequest {
  filename: string;
}

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

export async function fetchLocalAsset(
  request: LocalFetchAssetRequest
): Promise<SerializedAsset> {
  const response = await fetchLoopback(request.url);
  if (!response.ok) {
    throw new Error(`asset fetch failed: HTTP ${response.status}`);
  }
  return encodeAsset(request.filename, await response.blob());
}
