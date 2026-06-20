import process from "node:process";

import { err, toServiceError } from "@youtube-automation/core";
import type { Result, ServiceError } from "@youtube-automation/core";
import { REGISTRY } from "@youtube-automation/core/registry";
import type { DepsMap } from "@youtube-automation/core/registry";
import type { GenerateSunoOutput } from "@youtube-automation/core/suno-prompts";
import { defineCommand } from "citty";

import { resolveDeps as defaultResolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult as defaultEmitResult } from "../../../lib/run-command.ts";

const generateSunoEntry = REGISTRY["suno.generate"];

const renderText = (output: GenerateSunoOutput): string =>
  [
    `generated: ${output.entryCount}`,
    `markdown: ${output.markdownPath}`,
    `json: ${output.jsonPath}`,
    ...output.warnings.map((warning) => `[WARN] ${warning}`),
  ].join("\n");

type GenerateSunoEntry = typeof generateSunoEntry;
type GenerateSunoDeps = Pick<DepsMap, GenerateSunoEntry["deps"][number]>;

interface GenerateSunoCommandDeps {
  emitResult: GenerateSunoEmitResult;
  entry: GenerateSunoEntry;
  getCwd: () => string;
  resolveDeps: (deps: GenerateSunoEntry["deps"]) => Promise<GenerateSunoDeps>;
}

type GenerateSunoCommand = ReturnType<typeof defineCommand> & {
  run(context: { args: { json?: boolean; path?: unknown } }): Promise<void>;
};

type GenerateSunoEmitResult = (
  result: Result<GenerateSunoOutput, ServiceError>,
  options: {
    json: boolean;
    renderText: (value: GenerateSunoOutput) => string;
  }
) => void;

export const createGenerateSunoCommand = ({
  emitResult,
  entry,
  getCwd,
  resolveDeps,
}: GenerateSunoCommandDeps) =>
  defineCommand({
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
      description: entry.description,
      name: "generate-suno",
    },
    async run({ args }) {
      const rawPath = typeof args.path === "string" ? args.path : undefined;
      const json = args.json === true || rawPath === "--json";
      const cwd = getCwd();
      const path = rawPath === "--json" ? cwd : (rawPath ?? cwd);
      const result = await (async () => {
        try {
          const input = entry.inputSchema.parse({ path });
          const deps = await resolveDeps(entry.deps);
          return await entry.run(input, deps);
        } catch (error) {
          return err(toServiceError(error));
        }
      })();
      emitResult(result, { json, renderText });
    },
  }) as GenerateSunoCommand;

export const generateSunoCommand = createGenerateSunoCommand({
  emitResult: defaultEmitResult,
  entry: generateSunoEntry,
  getCwd: () => process.cwd(),
  resolveDeps: defaultResolveDeps,
});
