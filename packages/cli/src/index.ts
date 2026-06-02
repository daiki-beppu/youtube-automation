import process from "node:process";

import { greeting } from "@youtube-automation/core";

// Skeleton CLI entry. Real yt-* commands are migrated in later #727 issues.
export const run = (): void => {
  process.stdout.write(`${greeting()}\n`);
};
