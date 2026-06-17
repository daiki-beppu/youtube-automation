import process from "node:process";

import { err, toServiceError } from "@youtube-automation/core";
import type { CollectionServeOutput } from "@youtube-automation/core/collection-serve";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const collectionServeEntry = REGISTRY["collection.serve"];

const renderText = (output: CollectionServeOutput): string =>
  [
    `url: ${output.url}`,
    `mode: ${output.mode}`,
    `playlist_capture: ${output.playlistCaptureEnabled}`,
    `distrokid: ${output.distrokidEnabled}`,
    `routes: ${output.routes.join(", ")}`,
  ].join("\n");

export const collectionServeCommand = defineCommand({
  args: {
    "allow-origin": {
      description: "CORS で許可する Origin を完全一致で指定する",
      type: "string",
    },
    "distrokid-source": {
      description:
        "DistroKid single mode で配信する collection root 相対の disc source",
      type: "string",
    },
    "distrokid-state-root": {
      description: "DistroKid released state を記録する channel root",
      type: "string",
    },
    json: {
      default: false,
      description: "JSON で出力する",
      type: "boolean",
    },
    path: {
      description: "collection directory または collections root",
      required: false,
      type: "positional",
    },
    "playlist-capture-prefix": {
      description: "Suno playlist capture の channel prefix",
      type: "string",
    },
    "playlist-capture-root": {
      description: "Suno playlist capture の channel root",
      type: "string",
    },
    port: {
      description: "HTTP server port",
      type: "string",
    },
  },
  meta: {
    description: collectionServeEntry.description,
    name: "collection-serve",
  },
  async run({ args }) {
    const result = await (async () => {
      try {
        const input = collectionServeEntry.inputSchema.parse({
          allow_origin: args["allow-origin"],
          distrokid_source: args["distrokid-source"],
          distrokid_state_root: args["distrokid-state-root"],
          path: typeof args.path === "string" ? args.path : process.cwd(),
          playlist_capture_prefix: args["playlist-capture-prefix"],
          playlist_capture_root: args["playlist-capture-root"],
          port: typeof args.port === "string" ? Number(args.port) : undefined,
        });
        const deps = await resolveDeps(collectionServeEntry.deps);
        return await collectionServeEntry.run(input, deps);
      } catch (error) {
        return err(toServiceError(error));
      }
    })();
    emitResult(result, { json: args.json, renderText });
  },
});
