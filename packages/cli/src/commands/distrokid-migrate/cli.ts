import { err, toServiceError } from "@youtube-automation/core";
import type { DistrokidMigrateOutput } from "@youtube-automation/core/distrokid-migrate";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";
import {
  distrokidMigrateCommandArgs,
  distrokidMigrateCommandMeta,
} from "./definition.ts";

const distrokidMigrateEntry = REGISTRY["distrokid.migrate"];

const renderText = (output: DistrokidMigrateOutput): string => {
  const lines = [
    output.applied ? "[apply]" : "[dry-run]",
    `path: ${output.path}`,
  ];
  if (output.backupPath !== null) {
    lines.push(`backup: ${output.backupPath}`);
  }
  return lines.join("\n");
};

export const distrokidMigrateCommand = defineCommand({
  args: distrokidMigrateCommandArgs,
  meta: distrokidMigrateCommandMeta,
  async run({ args }) {
    const result = await (async () => {
      try {
        const input = distrokidMigrateEntry.inputSchema.parse({
          apply: args.apply,
          backup: args.backup,
          target: args.target,
        });
        const deps = await resolveDeps(distrokidMigrateEntry.deps);
        return await distrokidMigrateEntry.run(input, deps);
      } catch (error) {
        return err(toServiceError(error));
      }
    })();
    emitResult(result, { json: args.json, renderText });
  },
});
