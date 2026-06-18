#!/usr/bin/env bun
import { defineCommand, runMain } from "citty";

import { channelInitCommand } from "../src/commands/channel-init/cli.ts";
import { generateSunoCommand } from "../src/commands/generate-suno/cli.ts";
import { skillsCommand } from "../src/commands/skills/cli.ts";

const main = defineCommand({
  meta: {
    description: "youtube-channels-automation CLI (TS rewrite)",
    name: "tayk",
  },
  subCommands: {
    "channel-init": channelInitCommand,
    "generate-suno": generateSunoCommand,
    skills: skillsCommand,
  },
});

await runMain(main);
