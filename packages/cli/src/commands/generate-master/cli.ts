import { statSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import process from "node:process";

import { err, ok, toServiceError } from "@youtube-automation/core";
import type {
  GenerateMasterInput,
  GenerateMasterOutput,
} from "@youtube-automation/core/generate-master";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const generateMasterEntry = REGISTRY["masterup.generate-master"];

interface GenerateMasterRawInput {
  bitrate?: string;
  channel_dir?: string;
  collection?: string;
  crossfade_duration?: number;
  loop?: number;
  no_loop?: boolean;
  pin_first?: string[];
  pin_first_count?: number;
  quiet?: boolean;
  shuffle?: boolean;
  shuffle_seed?: number;
  target_duration_min?: number;
}

type ValueFlagHandler = (
  input: GenerateMasterRawInput,
  value: string,
  flag: string
) => void;

interface ValueFlagSpec {
  acceptsDashPrefixedValue: boolean;
  apply: ValueFlagHandler;
}

const parseNumberFlag = (flag: string, value: string): number => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    throw new TypeError(`validation: ${flag} must be a number`);
  }
  return parsed;
};

const VALUE_FLAG_SPECS: Record<string, ValueFlagSpec> = {
  "--bitrate": {
    acceptsDashPrefixedValue: false,
    apply: (input, value) => {
      input.bitrate = value;
    },
  },
  "--channel-dir": {
    acceptsDashPrefixedValue: false,
    apply: (input, value) => {
      input.channel_dir = value;
    },
  },
  "--crossfade-duration": {
    acceptsDashPrefixedValue: true,
    apply: (input, value, flag) => {
      input.crossfade_duration = parseNumberFlag(flag, value);
    },
  },
  "--loop": {
    acceptsDashPrefixedValue: true,
    apply: (input, value, flag) => {
      input.loop = parseNumberFlag(flag, value);
    },
  },
  "--pin-first-count": {
    acceptsDashPrefixedValue: true,
    apply: (input, value, flag) => {
      input.pin_first_count = parseNumberFlag(flag, value);
    },
  },
  "--shuffle-seed": {
    acceptsDashPrefixedValue: true,
    apply: (input, value, flag) => {
      input.shuffle_seed = parseNumberFlag(flag, value);
    },
  },
  "--target-duration": {
    acceptsDashPrefixedValue: true,
    apply: (input, value, flag) => {
      input.target_duration_min = parseNumberFlag(flag, value);
    },
  },
};

const parseValueFlag = (
  arg: string
):
  | { flag: string; inlineValue: string | undefined; spec: ValueFlagSpec }
  | undefined => {
  const separatorIndex = arg.indexOf("=");
  const flag = separatorIndex === -1 ? arg : arg.slice(0, separatorIndex);
  const spec = VALUE_FLAG_SPECS[flag];
  if (spec === undefined) {
    return undefined;
  }
  if (separatorIndex === -1) {
    return { flag, inlineValue: undefined, spec };
  }
  const inlineValue = arg.slice(separatorIndex + 1);
  if (inlineValue.length === 0) {
    throw new Error(`validation: ${flag} requires a value`);
  }
  return { flag, inlineValue, spec };
};

const requireValue = (
  rawArgs: string[],
  index: number,
  flag: string,
  spec: ValueFlagSpec
): string => {
  const value = rawArgs.at(index + 1);
  if (
    value === undefined ||
    (!spec.acceptsDashPrefixedValue && value.startsWith("-"))
  ) {
    throw new Error(`validation: ${flag} requires a value`);
  }
  return value;
};

const applyBooleanFlag = (
  input: GenerateMasterRawInput,
  arg: string
): boolean => {
  if (arg === "--quiet") {
    input.quiet = true;
    return true;
  }
  if (arg === "--no-loop") {
    input.no_loop = true;
    return true;
  }
  if (arg === "--shuffle") {
    input.shuffle = true;
    return true;
  }
  return arg === "--json";
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isNodeErrorCode = (error: unknown, code: string): boolean =>
  isRecord(error) && error.code === code;

const isDirectory = (path: string): boolean => {
  try {
    return statSync(path).isDirectory();
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) {
      return false;
    }
    throw error;
  }
};

const resolveCollectionCandidate = (
  input: GenerateMasterRawInput,
  value: string
): string | undefined => {
  if (isAbsolute(value)) {
    return resolve(value);
  }
  if (input.channel_dir !== undefined) {
    return resolve(input.channel_dir, value);
  }
  const channelDir = process.env.CHANNEL_DIR;
  return channelDir === undefined || channelDir.length === 0
    ? undefined
    : resolve(channelDir, value);
};

const isCollectionCandidate = (
  input: GenerateMasterRawInput,
  value: string
): boolean => {
  const candidate = resolveCollectionCandidate(input, value);
  return candidate !== undefined && isDirectory(candidate);
};

const collectPinFirstValues = (
  rawArgs: string[],
  startIndex: number,
  pendingPinFirst: string[]
): number => {
  let index = startIndex;
  while (rawArgs.at(index + 1) !== undefined) {
    const next = rawArgs.at(index + 1);
    if (next === undefined || next.startsWith("-")) {
      break;
    }
    pendingPinFirst.push(next);
    index += 1;
  }
  return index;
};

const collectInlinePinFirstValues = (
  rawArgs: string[],
  index: number,
  arg: string,
  pendingPinFirst: string[]
): number | undefined => {
  const prefix = "--pin-first=";
  if (!arg.startsWith(prefix)) {
    return undefined;
  }
  const firstValue = arg.slice(prefix.length);
  if (firstValue.length === 0) {
    throw new Error("validation: --pin-first requires a value");
  }
  pendingPinFirst.push(firstValue);
  return collectPinFirstValues(rawArgs, index, pendingPinFirst);
};

const applyCollectionAndPinFirst = (
  input: GenerateMasterRawInput,
  positionals: string[],
  pendingPinFirst: string[]
): void => {
  if (positionals.length > 0) {
    input.collection = positionals.at(-1);
  } else {
    const trailingPinFirst = pendingPinFirst.at(-1);
    if (
      trailingPinFirst !== undefined &&
      isCollectionCandidate(input, trailingPinFirst)
    ) {
      input.collection = trailingPinFirst;
      pendingPinFirst.pop();
    }
  }
  input.pin_first = pendingPinFirst;
};

const parseGenerateMasterArgs = (rawArgs: string[]): GenerateMasterRawInput => {
  const input: GenerateMasterRawInput = { pin_first: [] };
  const pendingPinFirst: string[] = [];
  const positionals: string[] = [];
  for (let index = 0; index < rawArgs.length; index += 1) {
    const arg = rawArgs[index];
    if (arg === undefined) {
      continue;
    }
    if (applyBooleanFlag(input, arg)) {
      continue;
    }
    if (arg === "--pin-first") {
      index = collectPinFirstValues(rawArgs, index, pendingPinFirst);
      continue;
    }
    const inlinePinFirstEndIndex = collectInlinePinFirstValues(
      rawArgs,
      index,
      arg,
      pendingPinFirst
    );
    if (inlinePinFirstEndIndex !== undefined) {
      index = inlinePinFirstEndIndex;
      continue;
    }
    const valueFlag = parseValueFlag(arg);
    if (valueFlag !== undefined) {
      const value =
        valueFlag.inlineValue ??
        requireValue(rawArgs, index, valueFlag.flag, valueFlag.spec);
      valueFlag.spec.apply(input, value, valueFlag.flag);
      if (valueFlag.inlineValue === undefined) {
        index += 1;
      }
      continue;
    }
    if (arg.startsWith("-")) {
      throw new Error(`validation: unknown option: ${arg}`);
    }
    positionals.push(arg);
  }

  applyCollectionAndPinFirst(input, positionals, pendingPinFirst);
  return input;
};

const parseGenerateMasterInput = (rawArgs: string[]) => {
  try {
    return ok(
      generateMasterEntry.inputSchema.parse(parseGenerateMasterArgs(rawArgs))
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};

const renderGenerateMasterText = (output: GenerateMasterOutput): string => {
  const lines = [
    `Output: ${output.outputPath}`,
    `Input files: ${output.inputCount}`,
    `Segments: ${output.segmentCount}`,
    `Loop count: ${output.loopCount}`,
    `Crossfade: ${output.crossfadeDuration}`,
    `Bitrate: ${output.bitrate}`,
  ];
  return [...output.messages, ...lines].join("\n");
};

export const generateMasterCommand = defineCommand({
  args: {
    bitrate: {
      description: "出力 MP3 bitrate",
      type: "string",
    },
    "channel-dir": {
      description: "CHANNEL_DIR として扱うチャンネル root",
      type: "string",
    },
    "crossfade-duration": {
      description: "acrossfade 秒数",
      type: "string",
    },
    json: {
      default: false,
      description: "JSON で出力する",
      type: "boolean",
    },
    loop: {
      description: "入力リストの繰り返し回数",
      type: "string",
    },
    "no-loop": {
      default: false,
      description: "目標尺指定を使わず 1 pass で生成する",
      type: "boolean",
    },
    "pin-first": {
      description: "先頭固定するファイル名リスト",
      type: "string",
    },
    "pin-first-count": {
      description: "ソート済み先頭 N 件を固定する",
      type: "string",
    },
    quiet: {
      default: false,
      description: "進捗表示を抑制する",
      type: "boolean",
    },
    shuffle: {
      default: false,
      description: "先頭固定分以外をシャッフルする",
      type: "boolean",
    },
    "shuffle-seed": {
      description: "シャッフル seed",
      type: "string",
    },
    "target-duration": {
      description: "目標尺（分）以上になる loop 数を算出する",
      type: "string",
    },
  },
  meta: {
    description: generateMasterEntry.description,
    name: "generate-master",
  },
  async run({ args, rawArgs }) {
    const parsedInput = parseGenerateMasterInput(rawArgs);
    if (!parsedInput.ok) {
      emitResult<GenerateMasterInput>(parsedInput, {
        json: args.json === true,
        renderText: () => "",
      });
      return;
    }
    const input = parsedInput.value;
    const deps = await resolveDeps(generateMasterEntry.deps);
    const result = await generateMasterEntry.run(input, deps);
    emitResult(result, {
      json: args.json === true,
      renderText: renderGenerateMasterText,
    });
  },
});
