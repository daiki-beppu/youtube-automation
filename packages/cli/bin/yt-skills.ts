#!/usr/bin/env bun
import process from "node:process";

import { runSkillsCli } from "../skills-sync/cli.ts";

try {
  await runSkillsCli(process.argv.slice(2));
} catch (error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}
