import type { PromptEntry } from "../../shared/api";
import type { RunPayload } from "./messaging";
import { resumeRunRange, type ResumeBanner, type RunRange } from "./resume-state";

export type RunPayloadObject = Exclude<RunPayload, PromptEntry[]>;

export interface RunOverrides {
  range?: RunRange;
  indices?: number[];
  submittedClipIds?: string[];
  playlistExpectedClipCount?: number;
}

export interface PlaylistResumePayload {
  submittedClipIds: string[];
  playlistExpectedClipCount: number | undefined;
}

export interface RunPayloadInput {
  entries: PromptEntry[];
  playlistName: string | undefined;
  range: RunRange | undefined;
  collectionId: string;
  overrides: RunOverrides | undefined;
}

export function buildRunPayload(input: RunPayloadInput): RunPayloadObject {
  return {
    entries: input.entries,
    playlistName: input.playlistName,
    range: input.range,
    collectionId: input.collectionId === "" ? undefined : input.collectionId,
    indices: input.overrides?.indices,
    submittedClipIds: input.overrides?.submittedClipIds,
    playlistExpectedClipCount: input.overrides?.playlistExpectedClipCount,
  };
}

export function buildResumeRunOverrides(
  resumeBanner: ResumeBanner,
  playlistResume: PlaylistResumePayload,
): RunOverrides {
  return {
    range: resumeRunRange(resumeBanner),
    submittedClipIds: [...playlistResume.submittedClipIds],
    playlistExpectedClipCount: playlistResume.playlistExpectedClipCount,
  };
}

export function buildFailedEntriesRunOverrides(
  failedEntries: number[],
  playlistResume: PlaylistResumePayload,
): RunOverrides {
  return {
    indices: [...failedEntries],
    submittedClipIds: [...playlistResume.submittedClipIds],
    playlistExpectedClipCount: playlistResume.playlistExpectedClipCount,
  };
}
