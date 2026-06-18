import { err, toServiceError } from "@youtube-automation/core";
import type { GenerateImageOutput } from "@youtube-automation/core/image";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const generateImageEntry = REGISTRY["image.generate"];
type GenerateImageEntry = typeof generateImageEntry;
type ResolveGenerateImageDeps = (
  entryDeps: GenerateImageEntry["deps"]
) => Promise<Parameters<GenerateImageEntry["run"]>[1]>;

const renderText = (output: GenerateImageOutput): string =>
  `saved: ${output.savedPath}`;

export const referencesFromArg = (
  value: string | undefined
): string[] | undefined => (value === undefined ? undefined : [value]);

export const createGenerateImageCommand = (
  deps: {
    entry?: GenerateImageEntry;
    resolveDeps?: ResolveGenerateImageDeps;
  } = {}
) => {
  const entry = deps.entry ?? generateImageEntry;
  const resolveCommandDeps =
    deps.resolveDeps ??
    ((entryDeps: GenerateImageEntry["deps"]) => resolveDeps(entryDeps));

  return defineCommand({
    args: {
      "aspect-ratio": {
        description: "生成画像のアスペクト比",
        type: "string",
      },
      "image-size": {
        description: "Provider に渡す解像度ヒント",
        type: "string",
      },
      json: {
        default: false,
        description: "JSON で出力する",
        type: "boolean",
      },
      output: {
        description: "画像の保存先パス",
        required: true,
        type: "string",
      },
      prompt: {
        description: "画像生成プロンプト",
        required: true,
        type: "string",
      },
      reference: {
        description: "参照画像パス",
        type: "string",
      },
    },
    meta: {
      description: entry.description,
      name: "generate-image",
    },
    async run({ args }) {
      const result = await (async () => {
        try {
          const input = entry.inputSchema.parse({
            aspect_ratio: args["aspect-ratio"],
            image_size: args["image-size"],
            output_path: args.output,
            prompt: args.prompt,
            references: referencesFromArg(args.reference),
          });
          const entryDeps = await resolveCommandDeps(entry.deps);
          return await entry.run(input, entryDeps);
        } catch (error) {
          return err(toServiceError(error));
        }
      })();
      emitResult(result, {
        json: args.json === true,
        renderText,
      });
    },
  });
};

export const generateImageCommand = createGenerateImageCommand();
