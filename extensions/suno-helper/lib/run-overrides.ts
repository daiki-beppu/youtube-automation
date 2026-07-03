import type { DurationFilter, PromptEntry } from "../../shared/api";
import type { RunPayload } from "./messaging";
import { selectedEntryIndices, type PatternSelectionInput } from "./pattern-selection";
import { resumeRunRange, type ResumeBanner, type RunRange } from "./resume-state";

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
  playlistName: string;
  durationFilter?: DurationFilter;
  range: RunRange | undefined;
  collectionId: string;
  overrides: RunOverrides | undefined;
}

export function buildRunPayload(input: RunPayloadInput): RunPayload {
  return {
    entries: input.entries,
    playlistName: input.playlistName,
    ...(input.durationFilter ? { durationFilter: input.durationFilter } : {}),
    range: input.range,
    collectionId: input.collectionId,
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

export function buildSelectedEntriesRunOverrides({
  selectedEntries,
  itemStates,
  entryCount,
}: PatternSelectionInput): RunOverrides | undefined {
  const indices = selectedEntryIndices({
    selectedEntries,
    itemStates,
    entryCount,
  });

  if (indices.length === 0) {
    throw new Error("実行対象が選択されていません。");
  }
  if (indices.length === entryCount) {
    return undefined;
  }
  return { indices };
}
