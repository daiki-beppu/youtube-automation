import process from "node:process";

import { listSkillsService } from "@youtube-automation/core/skills-sync";
import type { SkillListOutput } from "@youtube-automation/core/skills-sync";

// ADR 0002 thin wrapper: 引数 parse → service 呼び出し → 整形出力 のみ。
// business logic と重い依存は packages/core 側に置く。

type OutputFormat = "json" | "text";

interface ListOptions {
  format: OutputFormat;
  skillsDir?: string;
}

const parseListOptions = (flags: string[]): ListOptions => {
  let format: OutputFormat = "text";
  let skillsDir: string | undefined;
  for (let i = 0; i < flags.length; i += 1) {
    const flag = flags[i];
    if (flag === "--json") {
      format = "json";
    } else if (flag === "--skills-dir") {
      const value = flags[i + 1];
      if (value === undefined) {
        throw new Error("Missing value for option: --skills-dir");
      }
      skillsDir = value;
      i += 1;
    } else {
      throw new Error(`Unknown option: ${flag}`);
    }
  }
  return { format, skillsDir };
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

  const { format, skillsDir } = parseListOptions(flags);
  const result = await listSkillsService({ skillsDir });
  if (!result.ok) {
    // ADR-0003 thin wrapper: domain で exit code を決める (quota は 75、その他 1)。
    process.stderr.write(`[${result.error.domain}] ${result.error.message}\n`);
    process.exit(result.error.domain === "quota" ? 75 : 1);
  }

  const output = result.value;
  const rendered =
    format === "json" ? JSON.stringify(output) : renderText(output);
  process.stdout.write(`${rendered}\n`);
};
