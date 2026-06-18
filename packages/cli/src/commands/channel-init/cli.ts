import { existsSync, realpathSync, statSync } from "node:fs";
import process from "node:process";

import { err, toServiceError } from "@youtube-automation/core";
import type { ChannelInitOutput } from "@youtube-automation/core/channel-init";
import { REGISTRY } from "@youtube-automation/core/registry";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

const channelInitEntry = REGISTRY["channel.init"];

const resolveTarget = (target: string | undefined): string => {
  if (target !== undefined) {
    return target;
  }
  const env = process.env.CHANNEL_DIR;
  if (env !== undefined && env !== "") {
    return env;
  }
  return process.cwd();
};

const assertDirectory = (path: string): string => {
  if (!existsSync(path) || !statSync(path).isDirectory()) {
    throw new Error(`config: channel-init target が存在しません: ${path}`);
  }
  return realpathSync(path);
};

const renderText = (output: ChannelInitOutput): string => {
  if (output.diff !== "") {
    process.stderr.write(output.diff);
  }
  return output.summary;
};

export const channelInitCommand = defineCommand({
  args: {
    context: {
      default: "TBD",
      description: '利用コンテキスト placeholder (default: "TBD")',
      type: "string",
    },
    force: {
      default: false,
      description: "既存ファイルを上書きする",
      type: "boolean",
    },
    genre: {
      default: "TBD",
      description: 'ジャンル placeholder (default: "TBD")',
      type: "string",
    },
    name: {
      description: "仮チャンネル名",
      required: true,
      type: "string",
    },
    short: {
      description: "仮チャンネルの短縮シンボル",
      required: true,
      type: "string",
    },
    style: {
      default: "TBD",
      description: 'スタイル placeholder (default: "TBD")',
      type: "string",
    },
    target: {
      description:
        "ターゲットチャンネルディレクトリ (default: CHANNEL_DIR → CWD)",
      type: "string",
    },
  },
  meta: {
    description: channelInitEntry.description,
    name: "channel-init",
  },
  async run({ args }) {
    const result = await (async () => {
      try {
        const input = channelInitEntry.inputSchema.parse({
          context: args.context,
          force: args.force,
          genre: args.genre,
          name: args.name,
          short: args.short,
          style: args.style,
        });
        const channelDir = assertDirectory(resolveTarget(args.target));
        const deps = await resolveDeps(channelInitEntry.deps, { channelDir });
        return await channelInitEntry.run(input, deps);
      } catch (error) {
        return err(toServiceError(error));
      }
    })();
    emitResult(result, { json: false, renderText });
  },
});
