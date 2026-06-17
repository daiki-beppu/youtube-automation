import { err, toServiceError } from "@youtube-automation/core";
import type { GenerateImageOutput } from "@youtube-automation/core/image";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const generateImageEntry = REGISTRY["image.generate"];
const DEFAULT_IMAGE_SIZE = "2K";

const renderText = (output: GenerateImageOutput): string =>
  `saved: ${output.savedPath}`;

export const referencesFromArg = (value: unknown): string[] | undefined => {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value === "string") {
    return [value];
  }
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value;
  }
  throw new Error("validation: --reference は文字列で指定してください");
};

export const generateImageCommand = defineCommand({
  args: {
    "aspect-ratio": {
      default: "16:9",
      description: "生成画像のアスペクト比",
      type: "string",
    },
    "image-size": {
      default: DEFAULT_IMAGE_SIZE,
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
      description: "参照画像パス。複数指定可",
      type: "string",
    },
  },
  meta: {
    description: generateImageEntry.description,
    name: "generate-image",
  },
  async run({ args }) {
    const result = await (async () => {
      try {
        const input = generateImageEntry.inputSchema.parse({
          aspect_ratio: args["aspect-ratio"],
          image_size: args["image-size"],
          output_path: args.output,
          prompt: args.prompt,
          references: referencesFromArg(args.reference),
        });
        const deps = await resolveDeps(generateImageEntry.deps);
        return await generateImageEntry.run(input, deps);
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
