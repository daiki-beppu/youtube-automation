// Skeleton entry for the core package. Real domain logic is migrated in later #727 issues.
export const greeting = (): string =>
  "youtube-channels-automation core (TS rewrite skeleton)";

export { ConfigError } from "./errors.ts";
export { resolveSecret, SECRET_REFS } from "./secrets.ts";
