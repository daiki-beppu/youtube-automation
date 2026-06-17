import type { SupportedAudioExtension } from "./schema.ts";

export interface ResolvedMasteringOptions {
  readonly bitrate: string;
  readonly collectionDir: string;
  readonly crossfadeSeconds: number;
  readonly loop?: number;
  readonly pinFirst?: readonly string[];
  readonly pinFirstCount?: number;
  readonly shuffle: boolean;
  readonly shuffleSeed?: number;
  readonly targetDuration?: number;
}

export interface AudioTrackSet {
  readonly audioExt: SupportedAudioExtension;
  readonly files: readonly string[];
}
