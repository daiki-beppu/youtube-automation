export {
  DEFAULT_BITRATE,
  DEFAULT_CROSSFADE_DURATION,
  GenerateMasterInputSchema,
  GenerateMasterOutputSchema,
} from "./schema.ts";
export type { GenerateMasterInput, GenerateMasterOutput } from "./schema.ts";
export { findChannelRootForCollection } from "./paths.ts";
export { generateMasterService } from "./service.ts";
