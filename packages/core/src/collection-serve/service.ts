import type { ChannelConfig } from "../config/index.ts";
import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import { resolveCollectionServeMode } from "./collections.ts";
import {
  CollectionServeInputSchema,
  CollectionServeOutputSchema,
} from "./schema.ts";
import type { CollectionServeInput, CollectionServeOutput } from "./schema.ts";
import {
  buildCollectionServeRoutes,
  createCollectionServeFetchHandler,
} from "./server.ts";

interface CollectionServeDeps {
  readonly config: ChannelConfig;
}

export const collectionServeService = async (
  input: CollectionServeInput,
  deps: CollectionServeDeps
): Promise<Result<CollectionServeOutput, ServiceError>> => {
  try {
    const request = CollectionServeInputSchema.parse(input);
    const mode = await resolveCollectionServeMode(request.path);
    const distrokidEnabled = deps.config.integrations.distrokid.enabled;
    const server = Bun.serve({
      fetch: createCollectionServeFetchHandler(request, deps.config, mode),
      hostname: "localhost",
      port: request.port,
    });
    return ok(
      CollectionServeOutputSchema.parse({
        distrokidEnabled,
        mode,
        playlistCaptureEnabled: request.playlistCaptureRoot !== undefined,
        routes: buildCollectionServeRoutes(request, distrokidEnabled, mode),
        url: server.url.toString().replace(/\/$/u, ""),
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
