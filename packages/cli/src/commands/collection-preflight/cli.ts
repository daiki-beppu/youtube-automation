import process from "node:process";

import { defineCommand } from "citty";

interface SpawnResult {
  exitCode: number | null;
  signalCode?: string | null;
}

interface CollectionPreflightCommandDeps {
  exit: (code: number) => never;
  spawnSync: (
    command: string[],
    options: {
      stderr: "inherit";
      stdin: "inherit";
      stdout: "inherit";
    }
  ) => SpawnResult;
}

type CollectionPreflightCommand = ReturnType<typeof defineCommand> & {
  run(context: { rawArgs?: string[] }): void;
};

export const createCollectionPreflightCommand = ({
  exit,
  spawnSync,
}: CollectionPreflightCommandDeps) =>
  defineCommand({
    args: {
      collections: {
        description:
          "対象コレクション（ディレクトリ名 or パス）。未指定時は planning 配下の全コレクション",
        required: false,
        type: "positional",
      },
      fix: {
        default: false,
        description: "欠落サブディレクトリを冪等に作成する（非破壊）",
        type: "boolean",
      },
      "planning-root": {
        description:
          "planning ディレクトリの明示指定（デフォルト: <CHANNEL_DIR>/collections/planning）",
        type: "string",
      },
    },
    meta: {
      description: "コレクションの標準ディレクトリ骨格を検証・補完する",
      name: "collection-preflight",
    },
    run({ rawArgs = [] }) {
      const proc = spawnSync(
        ["uv", "run", "yt-collection-preflight", ...rawArgs],
        {
          stderr: "inherit",
          stdin: "inherit",
          stdout: "inherit",
        }
      );
      const code = proc.exitCode ?? (proc.signalCode ? 128 : 1);
      if (code !== 0) {
        exit(code);
      }
    },
  }) as CollectionPreflightCommand;

export const collectionPreflightCommand = createCollectionPreflightCommand({
  exit: process.exit,
  spawnSync: Bun.spawnSync,
});
