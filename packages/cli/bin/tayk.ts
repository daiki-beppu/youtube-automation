#!/usr/bin/env bun
import { defineCommand, runMain } from "citty";

import {
  distrokidMigrateCommandArgs,
  distrokidMigrateCommandMeta,
} from "../src/commands/distrokid-migrate/definition.ts";
import { generateSunoCommand } from "../src/commands/generate-suno/cli.ts";
import { skillsCommand } from "../src/commands/skills/cli.ts";

const distrokidMigrateCommand = defineCommand({
  args: distrokidMigrateCommandArgs,
  meta: distrokidMigrateCommandMeta,
  async run(context) {
    const { distrokidMigrateCommand: command } =
      await import("../src/commands/distrokid-migrate/cli.ts");
    return command.run?.(context);
  },
});

const main = defineCommand({
  meta: {
    description: "youtube-channels-automation CLI (TS rewrite)",
    name: "tayk",
  },
  subCommands: {
    "distrokid-migrate": distrokidMigrateCommand,
    "generate-suno": generateSunoCommand,
    skills: skillsCommand,
  },
});

await runMain(main);
