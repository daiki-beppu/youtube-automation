import { err, ok, toServiceError } from "@youtube-automation/core";

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

const VALUE_FLAGS = [
  "--bitrate",
  "--channel-dir",
  "--crossfade-duration",
  "--loop",
  "--pin-first-count",
  "--shuffle-seed",
  "--target-duration",
] as const;

const DASH_PREFIX_VALUE_FLAGS = [
  "--crossfade-duration",
  "--loop",
  "--pin-first-count",
  "--shuffle-seed",
  "--target-duration",
] as const;

const isValueFlag = (flag: string): boolean =>
  (VALUE_FLAGS as readonly string[]).includes(flag);

const parseValueFlag = (
  arg: string
): { flag: string; inlineValue: string | undefined } | undefined => {
  const separatorIndex = arg.indexOf("=");
  const flag = separatorIndex === -1 ? arg : arg.slice(0, separatorIndex);
  if (!isValueFlag(flag)) {
    return undefined;
  }
  if (separatorIndex === -1) {
    return { flag, inlineValue: undefined };
  }
  const inlineValue = arg.slice(separatorIndex + 1);
  if (inlineValue.length === 0) {
    throw new Error(`validation: ${flag} requires a value`);
  }
  return { flag, inlineValue };
};

const acceptsDashPrefixedValue = (flag: string): boolean =>
  (DASH_PREFIX_VALUE_FLAGS as readonly string[]).includes(flag);

const parseValueFlagPatch = (
  flag: string,
  value: string
): Partial<GenerateMasterRawInput> => {
  switch (flag) {
    case "--bitrate": {
      return { bitrate: value };
    }
    case "--channel-dir": {
      return { channel_dir: value };
    }
    case "--crossfade-duration": {
      return { crossfade_duration: parseNumberFlag(flag, value) };
    }
    case "--loop": {
      return { loop: parseNumberFlag(flag, value) };
    }
    case "--pin-first-count": {
      return { pin_first_count: parseNumberFlag(flag, value) };
    }
    case "--shuffle-seed": {
      return { shuffle_seed: parseNumberFlag(flag, value) };
    }
    case "--target-duration": {
      return { target_duration_min: parseNumberFlag(flag, value) };
    }
    default: {
      throw new Error(`validation: unknown option: ${flag}`);
    }
  }
};

const requireValue = (
  rawArgs: string[],
  index: number,
  flag: string,
  allowDashPrefixedValue: boolean
): string => {
  const value = rawArgs.at(index + 1);
  if (
    value === undefined ||
    (!allowDashPrefixedValue && value.startsWith("-"))
  ) {
    throw new Error(`validation: ${flag} requires a value`);
  }
  return value;
};

const parseBooleanFlag = (
  arg: string
): Partial<GenerateMasterRawInput> | undefined => {
  if (arg === "--quiet") {
    return { quiet: true };
  }
  if (arg === "--no-loop") {
    return { no_loop: true };
  }
  if (arg === "--shuffle") {
    return { shuffle: true };
  }
  return arg === "--json" ? {} : undefined;
};

const collectPinFirstValues = (
  rawArgs: string[],
  startIndex: number
): { endIndex: number; values: string[] } => {
  let index = startIndex;
  while (rawArgs.at(index + 1) !== undefined) {
    const next = rawArgs.at(index + 1);
    if (next === undefined || next.startsWith("-")) {
      break;
    }
    index += 1;
  }
  return {
    endIndex: index,
    values: rawArgs.slice(startIndex + 1, index + 1),
  };
};

const collectInlinePinFirstValues = (
  rawArgs: string[],
  index: number,
  arg: string
): { endIndex: number; values: string[] } | undefined => {
  const prefix = "--pin-first=";
  if (!arg.startsWith(prefix)) {
    return undefined;
  }
  const firstValue = arg.slice(prefix.length);
  if (firstValue.length === 0) {
    throw new Error("validation: --pin-first requires a value");
  }
  const collected = collectPinFirstValues(rawArgs, index);
  return {
    endIndex: collected.endIndex,
    values: [firstValue, ...collected.values],
  };
};

const withCollectionAndPinFirst = (
  input: GenerateMasterRawInput,
  positionals: string[],
  pendingPinFirst: string[],
  options: ParseOptions
): GenerateMasterRawInput => {
  if (positionals.length > 1) {
    throw new Error(
      "validation: generate-master accepts at most one collection positional"
    );
  }
  if (positionals.length === 1) {
    const [collection] = positionals;
    return { ...input, collection, pin_first: pendingPinFirst };
  }
  const trailingPinFirst = pendingPinFirst.at(-1);
  if (
    trailingPinFirst !== undefined &&
    (isCollectionCandidate(input, trailingPinFirst, options) ||
      isPathLikeCollectionToken(trailingPinFirst))
  ) {
    return {
      ...input,
      collection: trailingPinFirst,
      pin_first: pendingPinFirst.slice(0, -1),
    };
  }
  return {
    ...input,
    collection: input.collection ?? options.defaultCollection,
    pin_first: pendingPinFirst,
  };
};

interface ParseState {
  input: GenerateMasterRawInput;
  pendingPinFirst: string[];
  positionals: string[];
}

const appendPinFirstValues = (
  state: ParseState,
  values: string[]
): ParseState => ({
  ...state,
  pendingPinFirst: [...state.pendingPinFirst, ...values],
});

const appendPositional = (state: ParseState, value: string): ParseState => ({
  ...state,
  positionals: [...state.positionals, value],
});

const mergeInput = (
  state: ParseState,
  patch: Partial<GenerateMasterRawInput>
): ParseState => ({
  ...state,
  input: { ...state.input, ...patch },
});

const emptyParseState = (): ParseState => ({
  input: { pin_first: [] },
  pendingPinFirst: [],
  positionals: [],
});

const parseGenerateMasterArgs = (
  rawArgs: string[],
  options: ParseOptions
): GenerateMasterRawInput => {
  let state = emptyParseState();
  for (let index = 0; index < rawArgs.length; index += 1) {
    const arg = rawArgs[index];
    if (arg === undefined) {
      continue;
    }
    const booleanPatch = parseBooleanFlag(arg);
    if (booleanPatch !== undefined) {
      state = mergeInput(state, booleanPatch);
      continue;
    }
    if (arg === "--pin-first") {
      const collected = collectPinFirstValues(rawArgs, index);
      if (collected.values.length === 0) {
        throw new Error("validation: --pin-first requires a value");
      }
      state = appendPinFirstValues(state, collected.values);
      index = collected.endIndex;
      continue;
    }
    const inlinePinFirst = collectInlinePinFirstValues(rawArgs, index, arg);
    if (inlinePinFirst !== undefined) {
      state = appendPinFirstValues(state, inlinePinFirst.values);
      index = inlinePinFirst.endIndex;
      continue;
    }
    const valueFlag = parseValueFlag(arg);
    if (valueFlag !== undefined) {
      const value =
        valueFlag.inlineValue ??
        requireValue(
          rawArgs,
          index,
          valueFlag.flag,
          acceptsDashPrefixedValue(valueFlag.flag)
        );
      state = mergeInput(state, parseValueFlagPatch(valueFlag.flag, value));
      if (valueFlag.inlineValue === undefined) {
        index += 1;
      }
      continue;
    }
    if (arg.startsWith("-")) {
      throw new Error(`validation: unknown option: ${arg}`);
    }
    state = appendPositional(state, arg);
  }

  return withCollectionAndPinFirst(
    state.input,
    state.positionals,
    state.pendingPinFirst,
    options
  );
};

export const parseGenerateMasterInput = (
  rawArgs: string[],
  options: ParseOptions = {}
) => {
  try {
    const { quiet = false, ...serviceInput } = parseGenerateMasterArgs(
      rawArgs,
      options
    );
    return ok({
      input: serviceInput,
      quiet,
    });
  } catch (error) {
    return err(toServiceError(error));
  }
};
