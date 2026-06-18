import process from "node:process";

import { err, toServiceError } from "@tayk/core";
import { REGISTRY } from "@tayk/core/registry";
import type { GenerateSunoOutput } from "@tayk/core/suno-prompts";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const generateSunoEntry = REGISTRY["suno.generate"];

const renderText = (output: GenerateSunoOutput): string =>
  [
    `generated: ${output.entryCount}`,
    `markdown: ${output.markdownPath}`,
    `json: ${output.jsonPath}`,
    ...output.warnings.map((warning) => `[WARN] ${warning}`),
  ].join("\n");

export const generateSunoCommand = defineCommand({
  args: {
    json: {
      default: false,
      description: "JSON で出力する",
      type: "boolean",
    },
    path: {
      description:
        "collection directory または suno-patterns.yaml。省略時は CLI adapter が CWD に解決する",
      required: false,
      type: "positional",
    },
  },
  meta: {
    description: generateSunoEntry.description,
    name: "generate-suno",
  },
  async run({ args }) {
    const rawPath = typeof args.path === "string" ? args.path : undefined;
    const json = args.json === true || rawPath === "--json";
    const path =
      rawPath === "--json" ? process.cwd() : (rawPath ?? process.cwd());
    const result = await (async () => {
      try {
        const input = generateSunoEntry.inputSchema.parse({ path });
        const deps = await resolveDeps(generateSunoEntry.deps);
        return await generateSunoEntry.run(input, deps);
      } catch (error) {
        return err(toServiceError(error));
      }
    })();
    emitResult(result, { json, renderText });
  },
});
