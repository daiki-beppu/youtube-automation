import { err, toServiceError } from "@youtube-automation/core";
import type { FinalizeMasterOutput } from "@youtube-automation/core/finalize-master";
import { resolveCollectionDir } from "@youtube-automation/core/paths";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const finalizeMasterEntry = REGISTRY["finalize.master"];

const renderText = (output: FinalizeMasterOutput): string => {
  const status = output.passThrough
    ? "pass-through"
    : `layers applied: ${output.layersApplied}`;
  return [
    status,
    `loudnorm: ${output.loudnormApplied ? "applied" : "skipped"}`,
    `master: ${output.masterPath}`,
    ...output.warnings.map((warning) => `[WARN] ${warning}`),
  ].join("\n");
};

export const finalizeMasterCommand = defineCommand({
  args: {
    collection: {
      description: "collection directory。省略時は CWD",
      required: false,
      type: "positional",
    },
    json: {
      default: false,
      description: "JSON で出力する",
      type: "boolean",
    },
  },
  meta: {
    description: finalizeMasterEntry.description,
    name: "finalize-master",
  },
  async run({ args }) {
    const rawCollection =
      typeof args.collection === "string" ? args.collection : undefined;
    const json = args.json === true || rawCollection === "--json";
    const collectionArg =
      rawCollection === "--json" ? undefined : rawCollection;
    const result = await (async () => {
      try {
        const deps = await resolveDeps(finalizeMasterEntry.deps);
        const input = finalizeMasterEntry.inputSchema.parse({
          collectionDir: resolveCollectionDir(collectionArg ?? null),
        });
        return await finalizeMasterEntry.run(input, deps);
      } catch (error) {
        return err(toServiceError(error));
      }
    })();
    emitResult(result, { json, renderText });
  },
});
