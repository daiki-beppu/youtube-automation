#!/usr/bin/env bun
import { defineCommand, runMain } from "citty";

import { skillsCommand } from "../src/commands/skills/cli.ts";

// ADR-0004: yt は citty dispatcher。subcommand 実体は src/commands/ の adapter が
// core registry (@youtube-automation/core/registry) を呼ぶ。
const main = defineCommand({
  meta: {
    description: "youtube-channels-automation CLI (TS rewrite)",
    name: "yt",
  },
  subCommands: { skills: skillsCommand },
});

await runMain(main);
