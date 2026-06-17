import { readFile } from "node:fs/promises";

import type { NodeError } from "./collections.ts";
import { notFoundResponse, responseHeaders } from "./http.ts";
import type { CollectionServeInput } from "./schema.ts";

export const fileResponse = async (
  request: Request,
  input: CollectionServeInput,
  path: string,
  contentType: string
): Promise<Response> => {
  try {
    const body = await readFile(path);
    return new Response(body, {
      headers: responseHeaders(request, input.allowOrigin, contentType),
      status: 200,
    });
  } catch (error) {
    if ((error as NodeError).code === "ENOENT") {
      return notFoundResponse(request, input);
    }
    throw error;
  }
};
