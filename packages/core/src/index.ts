// Skeleton entry for the core package. Real domain logic is migrated in later #727 issues.
export const greeting = (): string =>
  "youtube-channels-automation core (TS rewrite skeleton)";

export {
  AuthError,
  AutomationError,
  ConfigError,
  GeneratorError,
  QuotaExhaustedError,
  UploadError,
  ValidationError,
  YouTubeAPIError,
  type YouTubeAPIErrorOptions,
} from "./errors.ts";
export { resolveSecret, SECRET_REFS } from "./secrets.ts";
