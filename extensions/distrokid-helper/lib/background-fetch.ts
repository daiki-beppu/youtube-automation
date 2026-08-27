import { sendMessage } from "./messaging";

export async function backgroundFetch(
  input: string | URL | Request,
  init?: RequestInit
): Promise<Response> {
  const method =
    init?.method ?? (input instanceof Request ? input.method : "GET");
  if (method.toUpperCase() !== "GET") {
    throw new Error("background local fetch only supports GET");
  }
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  const wire = await sendMessage("fetchLocalText", { url });
  return new Response(wire.body, {
    headers: wire.contentType
      ? { "Content-Type": wire.contentType }
      : undefined,
    status: wire.status,
    statusText: wire.statusText,
  });
}

export async function backgroundFetchAsset(url: string, filename: string) {
  const parts: ArrayBuffer[] = [];
  let offset = 0;
  let contentType = "";
  do {
    const chunk = await sendMessage("fetchLocalAssetChunk", { url, offset });
    const binary = atob(chunk.base64);
    const bytes = Uint8Array.from(binary, (character) =>
      character.charCodeAt(0)
    );
    parts.push(bytes.buffer);
    offset += bytes.byteLength;
    contentType = chunk.contentType;
    if (offset >= chunk.totalSize) break;
    if (bytes.byteLength === 0)
      throw new Error("asset chunk fetch made no progress");
  } while (offset >= 0);

  const blobUrl = URL.createObjectURL(new Blob(parts, { type: contentType }));
  return { filename, blobUrl, revoke: () => URL.revokeObjectURL(blobUrl) };
}
