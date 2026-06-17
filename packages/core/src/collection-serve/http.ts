import type { CollectionServeInput } from "./schema.ts";

const DEFAULT_ALLOWED_WEB_ORIGINS = new Set([
  "https://suno.com",
  "https://www.suno.com",
  "https://distrokid.com",
  "https://www.distrokid.com",
]);

export type FetchHandler = (request: Request) => Promise<Response> | Response;

export const allowedOrigin = (
  request: Request,
  allowOrigin: string | undefined
): string | undefined => {
  const origin = request.headers.get("origin");
  if (origin === null) {
    return undefined;
  }
  if (allowOrigin !== undefined) {
    return origin === allowOrigin ? origin : undefined;
  }
  if (origin.startsWith("chrome-extension://")) {
    return origin;
  }
  return DEFAULT_ALLOWED_WEB_ORIGINS.has(origin) ? origin : undefined;
};

export const responseHeaders = (
  request: Request,
  allowOrigin: string | undefined,
  contentType?: string
): Headers => {
  const headers = new Headers();
  if (contentType !== undefined) {
    headers.set("content-type", contentType);
  }
  const origin = allowedOrigin(request, allowOrigin);
  if (origin !== undefined) {
    headers.set("access-control-allow-origin", origin);
    headers.set("vary", "Origin");
  }
  return headers;
};

export const preflightHeaders = (
  request: Request,
  allowOrigin: string | undefined
): Headers => {
  const headers = responseHeaders(request, allowOrigin);
  headers.set("access-control-allow-methods", "GET, POST, OPTIONS");
  headers.set("access-control-allow-headers", "Content-Type");
  return headers;
};

export const jsonResponse = (
  body: unknown,
  status: number,
  request: Request,
  allowOrigin: string | undefined
): Response =>
  Response.json(body, {
    headers: responseHeaders(request, allowOrigin, "application/json"),
    status,
  });

export const notFoundResponse = (
  request: Request,
  input: CollectionServeInput
): Response =>
  jsonResponse({ error: "Not Found" }, 404, request, input.allowOrigin);

export const forbiddenPostResponse = (
  request: Request,
  input: CollectionServeInput
): Response =>
  jsonResponse({ error: "Forbidden" }, 403, request, input.allowOrigin);
