import { err, ok, toServiceError } from "@youtube-automation/core";
import { GenerateMasterInputSchema } from "@youtube-automation/core/generate-master";

import {
  isCollectionCandidate,
  isPathLikeCollectionToken,
} from "./collection-candidate.ts";

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

interface ParseOptions {
  channelDir?: string;
  defaultCollection?: string;
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
  pendingPinFirst: string[],
  options: ParseOptions
): void => {
  if (positionals.length > 1) {
    throw new Error(
      "validation: generate-master accepts at most one collection positional"
    );
  }
  if (positionals.length === 1) {
    const [collection] = positionals;
    input.collection = collection;
  } else {
    const trailingPinFirst = pendingPinFirst.at(-1);
    if (
      trailingPinFirst !== undefined &&
      (isCollectionCandidate(input, trailingPinFirst, options) ||
        isPathLikeCollectionToken(trailingPinFirst))
    ) {
      input.collection = trailingPinFirst;
      pendingPinFirst.pop();
    }
  }
  input.collection ??= options.defaultCollection;
  input.pin_first = pendingPinFirst;
};

const parseGenerateMasterArgs = (
  rawArgs: string[],
  options: ParseOptions
): GenerateMasterRawInput => {
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
      const previousLength = pendingPinFirst.length;
      index = collectPinFirstValues(rawArgs, index, pendingPinFirst);
      if (pendingPinFirst.length === previousLength) {
        throw new Error("validation: --pin-first requires a value");
      }
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

  applyCollectionAndPinFirst(input, positionals, pendingPinFirst, options);
  return input;
};

export const parseGenerateMasterInput = (
  rawArgs: string[],
  options: ParseOptions = {}
) => {
  try {
    return ok(
      GenerateMasterInputSchema.parse(parseGenerateMasterArgs(rawArgs, options))
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
