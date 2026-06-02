import process from "node:process";

import { listSkillsService } from "@youtube-automation/core/skills-sync";
import type { SkillListOutput } from "@youtube-automation/core/skills-sync";

// ADR 0002 thin wrapper: 引数 parse → service 呼び出し → 整形出力 のみ。
// business logic と重い依存は packages/core 側に置く。

type OutputFormat = "json" | "text";

const parseFormat = (flags: string[]): OutputFormat => {
  let format: OutputFormat = "text";
  for (const flag of flags) {
    if (flag === "--json") {
      format = "json";
    } else {
      throw new Error(`Unknown option: ${flag}`);
    }
  }
  return format;
};

const renderText = (output: SkillListOutput): string => {
  const header = `同梱スキル ${output.skills.length} 件 (source: ${output.source})`;
  const bullets = output.skills.map((name) => `  - ${name}`);
  return [header, ...bullets].join("\n");
};

export const runSkillsCli = async (argv: string[]): Promise<void> => {
  const [subcommand, ...flags] = argv;
  if (subcommand !== "list") {
    throw new Error(
      `Unknown subcommand: ${subcommand ?? "(none)"}. Supported: list`
    );
  }

  const format = parseFormat(flags);
  const output = await listSkillsService({});

  const rendered =
    format === "json" ? JSON.stringify(output) : renderText(output);
  process.stdout.write(`${rendered}\n`);
};
