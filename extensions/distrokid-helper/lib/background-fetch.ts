import { sendMessage } from "./messaging";

export async function backgroundFetch(
  input: string | URL | Request,
  init?: RequestInit
): Promise<Response> {
  if (init?.method !== undefined && init.method !== "GET") {
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
  return sendMessage("fetchLocalAsset", { url, filename });
}
