import { statSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import process from "node:process";

import { err, toServiceError } from "@youtube-automation/core";
import type { GenerateMasterInput } from "@youtube-automation/core/generate-master";
import type { DepsMap } from "@youtube-automation/core/registry";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";
import { parseGenerateMasterInput } from "./args.ts";
import {
  renderGenerateMasterQuietText,
  renderGenerateMasterText,
} from "./render.ts";

const generateMasterEntry = REGISTRY["masterup.generate-master"];

type GenerateMasterDeps = Pick<
  DepsMap,
  (typeof generateMasterEntry.deps)[number]
>;

const isMissingChannelDirError = (error: unknown): boolean =>
  error instanceof Error &&
  error.message.startsWith("config: CHANNEL_DIR 環境変数を設定するか");

const isDirectory = (path: string): boolean => {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
};

const findChannelRootForCollection = (
  collection: string
): string | undefined => {
  let current = resolve(collection);
  for (;;) {
    if (isDirectory(join(current, "config", "channel"))) {
      return current;
    }
    const parent = dirname(current);
    if (parent === current) {
      return undefined;
    }
    current = parent;
  }
};

const resolveGenerateMasterDeps = (
  input: Pick<Partial<GenerateMasterInput>, "channelDir" | "collection">,
  channelDir: string | undefined
): GenerateMasterDeps => {
  if (input.channelDir !== undefined) {
    return { channelDir: input.channelDir };
  }
  if (channelDir !== undefined) {
    return { channelDir };
  }
  if (input.collection !== undefined && isAbsolute(input.collection)) {
    const collectionChannelDir = findChannelRootForCollection(input.collection);
    if (collectionChannelDir !== undefined) {
      return { channelDir: collectionChannelDir };
    }
    throw new Error(
      "validation: absolute collection requires --channel-dir, CHANNEL_DIR, or config/channel ancestor"
    );
  }
  throw new Error(
    "validation: relative collection requires channel_dir or CHANNEL_DIR"
  );
};

const parseExplicitChannelDir = (rawArgs: string[]): string | undefined => {
  for (let index = 0; index < rawArgs.length; index += 1) {
    const arg = rawArgs[index];
    if (arg === undefined) {
      continue;
    }
    if (arg.startsWith("--channel-dir=")) {
      const value = arg.slice("--channel-dir=".length);
      if (value.length === 0) {
        throw new Error("validation: --channel-dir requires a value");
      }
      return value;
    }
    if (arg === "--channel-dir") {
      const value = rawArgs[index + 1];
      if (value === undefined || value.startsWith("-")) {
        throw new Error("validation: --channel-dir requires a value");
      }
      return value;
    }
  }
  return undefined;
};

const resolveContextChannelDir = async (
  rawArgs: string[]
): Promise<string | undefined> => {
  const explicit = parseExplicitChannelDir(rawArgs);
  if (explicit !== undefined) {
    return explicit;
  }
  try {
    const deps = await resolveDeps(generateMasterEntry.deps);
    return deps.channelDir;
  } catch (error) {
    if (isMissingChannelDirError(error)) {
      return undefined;
    }
    throw error;
  }
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
    let quiet = false;
    const result = await (async () => {
      try {
        const channelDir = await resolveContextChannelDir(rawArgs);
        const parsedInput = parseGenerateMasterInput(rawArgs, {
          channelDir,
          defaultCollection: process.cwd(),
        });
        if (!parsedInput.ok) {
          return err(parsedInput.error);
        }
        const { input, quiet: inputQuiet } = parsedInput.value;
        quiet = inputQuiet;
        const deps = resolveGenerateMasterDeps(
          {
            channelDir: input.channel_dir,
            collection: input.collection,
          },
          channelDir
        );
        return await generateMasterEntry.run(
          input as GenerateMasterInput,
          deps
        );
      } catch (error) {
        return err(toServiceError(error));
      }
    })();
    emitResult(result, {
      json: args.json === true,
      renderText: quiet
        ? renderGenerateMasterQuietText
        : renderGenerateMasterText,
    });
  },
});
