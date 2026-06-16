import process from "node:process";

import { REGISTRY } from "@youtube-automation/core/registry";
import { SYNC_ASSETS } from "@youtube-automation/core/skills-sync";
import type {
  SkillListOutput,
  SkillSyncOutput,
} from "@youtube-automation/core/skills-sync";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

// ADR-0004 §4: CLI flags は per-command 手書き (positional / alias / UX は schema に
// 乗らないため)。service 呼び出しは core registry entry 経由、entry.deps の解決は
// lib/resolve-deps.ts、出力整形と exit code は lib/run-command.ts の共通 helper に集約する。

const skillsListEntry = REGISTRY["skills.list"];
const skillsSyncEntry = REGISTRY["skills.sync"];

// CLI 限定 sugar。全資産を既定ターゲットへ配布する (service enum には載らない / #742)。
const ASSET_ALL = "all";
// usage error の終了コード (sysexits EX_USAGE)。Result→exit の共通 helper とは別系統。
const EXIT_USAGE = 2;

const renderListText = (output: SkillListOutput): string => {
  const header = `同梱スキル ${output.skills.length} 件 (source: ${output.source})`;
  const bullets = output.skills.map((name) => `  - ${name}`);
  return [header, ...bullets].join("\n");
};

const renderSyncText = (output: SkillSyncOutput): string => {
  const lines = [`[${output.asset}] → ${output.target}`];
  for (const entry of output.entries) {
    lines.push(`  ${entry.result}: ${entry.name}`);
  }
  if (output.agentsSkillsLink !== null) {
    lines.push(`  .agents/skills: ${output.agentsSkillsLink}`);
  }
  return lines.join("\n");
};

const listCommand = defineCommand({
  args: {
    json: {
      default: false,
      description: "JSON で出力する",
      type: "boolean",
    },
    "skills-dir": {
      description: "同梱 _skills の代わりに読む skills ディレクトリ",
      type: "string",
    },
  },
  meta: { description: skillsListEntry.description, name: "list" },
  async run({ args }) {
    const input = skillsListEntry.inputSchema.parse({
      skillsDir: args["skills-dir"],
    });
    const deps = await resolveDeps(skillsListEntry.deps);
    const result = await skillsListEntry.run(input, deps);
    emitResult(result, { json: args.json, renderText: renderListText });
  },
});

// 1 資産を配布する。target は省略時 service が資産ごとの既定を埋める。
const syncOneAsset = async (
  asset: string,
  target: string | undefined,
  force: boolean,
  json: boolean
): Promise<void> => {
  const input = skillsSyncEntry.inputSchema.parse({ asset, force, target });
  const deps = await resolveDeps(skillsSyncEntry.deps);
  const result = await skillsSyncEntry.run(input, deps);
  emitResult(result, { json, renderText: renderSyncText });
};

const syncCommand = defineCommand({
  args: {
    asset: {
      default: ASSET_ALL,
      description: "配布する資産 (skills | claude-md | all)",
      type: "string",
    },
    force: {
      default: false,
      description: "既存ファイル/シンボリックリンクを上書きする",
      type: "boolean",
    },
    json: {
      default: false,
      description: "JSON で出力する",
      type: "boolean",
    },
    target: {
      description: "配布先パス (省略時は資産ごとの既定)",
      type: "string",
    },
  },
  meta: { description: skillsSyncEntry.description, name: "sync" },
  async run({ args }) {
    const { asset, force, json, target } = args;

    if (asset === ASSET_ALL) {
      // 資産ごとに既定ターゲットが異なるため、単一 --target との併用は誤配置を招く。
      // 書き込み前に弾く (usage error)。
      if (target !== undefined) {
        process.stderr.write(
          "--asset all は --target と併用できません (資産ごとに既定ターゲットが異なります)\n"
        );
        process.exit(EXIT_USAGE);
      }
      for (const one of SYNC_ASSETS) {
        await syncOneAsset(one, undefined, force, json);
      }
      return;
    }

    if (!(SYNC_ASSETS as readonly string[]).includes(asset)) {
      process.stderr.write(
        `未知の --asset: ${asset} (${SYNC_ASSETS.join(" | ")} | ${ASSET_ALL})\n`
      );
      process.exit(EXIT_USAGE);
    }

    await syncOneAsset(asset, target, force, json);
  },
});

export const skillsCommand = defineCommand({
  meta: { description: "同梱スキル資産の操作", name: "skills" },
  subCommands: { list: listCommand, sync: syncCommand },
});
