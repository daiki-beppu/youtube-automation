import process from "node:process";

import type { GenerateMasterInput } from "@youtube-automation/core/generate-master";
import type { DepsMap } from "@youtube-automation/core/registry";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";
import {
  parseGenerateMasterInput,
  renderGenerateMasterQuietText,
  renderGenerateMasterText,
} from "./args.ts";

const generateMasterEntry = REGISTRY["masterup.generate-master"];

type GenerateMasterDeps = Pick<
  DepsMap,
  (typeof generateMasterEntry.deps)[number]
>;

const resolveGenerateMasterDeps = async (
  input: GenerateMasterInput
): Promise<GenerateMasterDeps> => {
  if (input.channelDir !== undefined) {
    return { channelDir: input.channelDir };
  }
  try {
    return await resolveDeps(generateMasterEntry.deps);
  } catch (error) {
    if (input.collection !== undefined) {
      return { channelDir: process.cwd() };
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
    const parsedInput = parseGenerateMasterInput(rawArgs, {
      defaultCollection: process.cwd(),
    });
    if (!parsedInput.ok) {
      emitResult<GenerateMasterInput>(parsedInput, {
        json: args.json === true,
        renderText: () => "",
      });
      return;
    }
    const input = parsedInput.value;
    const deps = await resolveGenerateMasterDeps(input);
    const result = await generateMasterEntry.run(input, deps);
    emitResult(result, {
      json: args.json === true,
      renderText: input.quiet
        ? renderGenerateMasterQuietText
        : renderGenerateMasterText,
    });
  },
});
