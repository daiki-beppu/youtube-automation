#!/usr/bin/env bun
import { defineCommand, runMain } from "citty";

import { collectionPreflightCommand } from "../src/commands/collection-preflight/cli.ts";
import { generateMasterCommand } from "../src/commands/generate-master/cli.ts";
import { generateSunoCommand } from "../src/commands/generate-suno/cli.ts";
import { skillsCommand } from "../src/commands/skills/cli.ts";

const main = defineCommand({
  meta: {
    description: "youtube-channels-automation CLI (TS rewrite)",
    name: "tayk",
  },
  subCommands: {
    "collection-preflight": collectionPreflightCommand,
    "generate-master": generateMasterCommand,
    "generate-suno": generateSunoCommand,
    skills: skillsCommand,
  },
});

await runMain(main);
