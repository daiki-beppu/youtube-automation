#!/usr/bin/env bun
import { defineCommand, runMain } from "citty";

import { generateSunoCommand } from "../src/commands/generate-suno/cli.ts";
import { playlistCommand } from "../src/commands/playlist/cli.ts";
import { skillsCommand } from "../src/commands/skills/cli.ts";

const main = defineCommand({
  meta: {
    description: "youtube-channels-automation CLI (TS rewrite)",
    name: "tayk",
  },
  subCommands: {
    "generate-suno": generateSunoCommand,
    playlist: playlistCommand,
    skills: skillsCommand,
  },
});

await runMain(main);
