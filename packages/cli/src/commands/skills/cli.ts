import { REGISTRY } from "@youtube-automation/core/registry";
import type { SkillListOutput } from "@youtube-automation/core/skills-sync";
import { defineCommand } from "citty";

import { resolveDeps } from "../../../lib/resolve-deps.ts";
import { emitResult } from "../../../lib/run-command.ts";

// ADR-0004 §4: CLI flags は per-command 手書き (positional / alias / UX は schema に
// 乗らないため)。service 呼び出しは core registry entry 経由、entry.deps の解決は
// lib/resolve-deps.ts、出力整形と exit code は lib/run-command.ts の共通 helper に集約する。

const skillsListEntry = REGISTRY["skills.list"];

const renderText = (output: SkillListOutput): string => {
  const header = `同梱スキル ${output.skills.length} 件 (source: ${output.source})`;
  const bullets = output.skills.map((name) => `  - ${name}`);
  return [header, ...bullets].join("\n");
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
    emitResult(result, { json: args.json, renderText });
  },
});

export const skillsCommand = defineCommand({
  meta: { description: "同梱スキル資産の操作", name: "skills" },
  subCommands: { list: listCommand },
});
