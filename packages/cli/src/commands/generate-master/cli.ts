import process from "node:process";

import { err, toServiceError } from "@youtube-automation/core";
import type { GenerateMasterOutput } from "@youtube-automation/core/generate-master";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const generateMasterEntry = REGISTRY["master.generate"];

const VALUE_FLAGS = new Set([
  "--loop",
  "--pin-first-count",
  "--shuffle-seed",
  "--target-duration",
]);

const BOOLEAN_FLAGS = new Set(["--json", "--shuffle"]);

const renderText = (output: GenerateMasterOutput): string =>
  [
    `output: ${output.outputPath}`,
    `format: ${output.audioExt}`,
    `tracks: ${output.inputCount}`,
    `segments: ${output.segmentCount}`,
    output.shuffleSeed === undefined
      ? undefined
      : `shuffleSeed: ${output.shuffleSeed}`,
  ]
    .filter((line): line is string => line !== undefined)
    .join("\n");

const commandArgv = (): readonly string[] => {
  const index = process.argv.indexOf("generate-master");
  if (index === -1) {
    return process.argv.slice(2);
  }
  return process.argv.slice(index + 1);
};

const appendPinFirst = (
  current: readonly string[],
  value: string
): readonly string[] => [...current, value];

const isValueFlagAssignment = (token: string): boolean => {
  const [flag] = token.split("=");
  return (
    flag !== undefined && VALUE_FLAGS.has(flag) && token.startsWith(`${flag}=`)
  );
};

const parseRawArgs = (
  argv: readonly string[]
): { readonly collection?: string; readonly pinFirst?: readonly string[] } => {
  let collection: string | undefined;
  let pinFirst: readonly string[] = [];
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === undefined) {
      continue;
    }
    if (token === "--pin-first") {
      const value = argv[index + 1];
      if (value === undefined || value.startsWith("--")) {
        throw new Error(`validation: missing value for ${token}`);
      }
      pinFirst = appendPinFirst(pinFirst, value);
      index += 1;
      continue;
    }
    if (token.startsWith("--pin-first=")) {
      pinFirst = appendPinFirst(pinFirst, token.slice("--pin-first=".length));
      continue;
    }
    if (isValueFlagAssignment(token)) {
      continue;
    }
    if (VALUE_FLAGS.has(token)) {
      const value = argv[index + 1];
      if (value === undefined || value.startsWith("--")) {
        throw new Error(`validation: missing value for ${token}`);
      }
      index += 1;
      continue;
    }
    if (BOOLEAN_FLAGS.has(token)) {
      continue;
    }
    if (token.startsWith("--")) {
      throw new Error(`validation: unknown option ${token}`);
    }
    if (collection === undefined) {
      collection = token;
      continue;
    }
    throw new Error(`validation: unexpected argument ${token}`);
  }
  return {
    collection,
    pinFirst: pinFirst.length > 0 ? pinFirst : undefined,
  };
};

export const generateMasterCommand = defineCommand({
  args: {
    collection: {
      description: "collection directory。省略時は CWD を使う",
      required: false,
      type: "positional",
    },
    json: {
      default: false,
      description: "JSON で出力する",
      type: "boolean",
    },
    loop: {
      description: "入力トラック列を N 回繰り返してクロスフェード結合する",
      required: false,
      type: "string",
    },
    "pin-first": {
      description: "先頭に固定するファイル名",
      required: false,
      type: "string",
    },
    "pin-first-count": {
      description: "ソート済み先頭 N 件を固定する",
      required: false,
      type: "string",
    },
    shuffle: {
      default: false,
      description: "入力トラックを seed 付きで並べ替える",
      type: "boolean",
    },
    "shuffle-seed": {
      description: "shuffle 用 seed",
      required: false,
      type: "string",
    },
    "target-duration": {
      description: "目標分数に届くまで入力トラック列を繰り返す",
      required: false,
      type: "string",
    },
  },
  meta: {
    description: generateMasterEntry.description,
    name: "generate-master",
  },
  async run({ args }) {
    const result = await (async () => {
      try {
        const raw = parseRawArgs(commandArgv());
        const input = generateMasterEntry.inputSchema.parse({
          collection: raw.collection ?? process.cwd(),
          loop: typeof args.loop === "string" ? Number(args.loop) : undefined,
          pin_first: raw.pinFirst,
          pin_first_count:
            typeof args["pin-first-count"] === "string"
              ? Number(args["pin-first-count"])
              : undefined,
          shuffle:
            args.shuffle === true || typeof args["shuffle-seed"] === "string",
          shuffle_seed:
            typeof args["shuffle-seed"] === "string"
              ? Number(args["shuffle-seed"])
              : undefined,
          target_duration:
            typeof args["target-duration"] === "string"
              ? Number(args["target-duration"])
              : undefined,
        });
        const deps = await resolveDeps(generateMasterEntry.deps);
        return await generateMasterEntry.run(input, deps);
      } catch (error) {
        return err(toServiceError(error));
      }
    })();
    emitResult(result, { json: args.json === true, renderText });
  },
});
