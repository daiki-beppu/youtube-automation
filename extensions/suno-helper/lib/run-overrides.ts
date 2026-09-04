import type { DurationFilter, PromptEntry } from "../../shared/api";
import {
  DEFAULT_REGENERATE_DURATION_OUTLIERS,
  type RunModeId,
  type RunTimingReceipt,
} from "../../shared/constants";
import type { RunPayload } from "./messaging";
import {
  selectedEntryIndices,
  type PatternSelectionInput,
} from "./pattern-selection";
import {
  resumeRunRange,
  type ResumeBanner,
  type RunRange,
} from "./resume-state";

export interface RunOverrides {
  range?: RunRange;
  indices?: number[];
  submittedClipIds?: string[];
  submittedClipIdsAreDurationFiltered?: boolean;
  playlistExpectedClipCount?: number;
  /** 再開時に元 run の投入方式を引き継ぐ (#1586)。未指定は popup の現在選択（RunPayloadInput.runMode）。 */
  runMode?: RunModeId;
  regenerateDurationOutliers?: boolean;
  /** resume の開始で live 警告を消去しないよう、前 run の警告を payload へ戻す。 */
  durationOutlierWarnings?: Record<number, string>;
  timingReceipt?: RunTimingReceipt;
}

export interface PlaylistResumePayload {
  submittedClipIds: string[];
  submittedClipIdsAreDurationFiltered: boolean;
  playlistExpectedClipCount: number | undefined;
  timingReceipt?: RunTimingReceipt;
}

export interface RunPayloadInput {
  entries: PromptEntry[];
  playlistName: string;
  durationFilter?: DurationFilter;
  range: RunRange | undefined;
  collectionId: string;
  collectionQueueId?: string;
  runMode: RunModeId;
  regenerateDurationOutliers?: boolean;
  downloadEnabled: boolean;
  durationOutlierWarnings?: Record<number, string>;
  overrides: RunOverrides | undefined;
}

export function buildRunPayload(input: RunPayloadInput): RunPayload {
  return {
    entries: input.entries,
    playlistName: input.playlistName,
    ...(input.durationFilter ? { durationFilter: input.durationFilter } : {}),
    range: input.range,
    collectionId: input.collectionId,
    ...(input.collectionQueueId
      ? { collectionQueueId: input.collectionQueueId }
      : {}),
    runMode: input.overrides?.runMode ?? input.runMode,
    regenerateDurationOutliers:
      input.overrides?.regenerateDurationOutliers ??
      input.regenerateDurationOutliers ??
      DEFAULT_REGENERATE_DURATION_OUTLIERS,
    downloadEnabled: input.downloadEnabled,
    indices: input.overrides?.indices,
    submittedClipIds: input.overrides?.submittedClipIds,
    submittedClipIdsAreDurationFiltered:
      input.overrides?.submittedClipIdsAreDurationFiltered,
    playlistExpectedClipCount: input.overrides?.playlistExpectedClipCount,
    durationOutlierWarnings:
      input.overrides?.durationOutlierWarnings ?? input.durationOutlierWarnings,
    timingReceipt: input.overrides?.timingReceipt,
  };
}

export function buildResumeRunOverrides(
  resumeBanner: ResumeBanner,
  playlistResume: PlaylistResumePayload
): RunOverrides {
  if (
    resumeBanner.remainingIndices &&
    resumeBanner.remainingIndices.length > 0
  ) {
    return {
      indices: [...resumeBanner.remainingIndices],
      submittedClipIds: [...playlistResume.submittedClipIds],
      submittedClipIdsAreDurationFiltered:
        playlistResume.submittedClipIdsAreDurationFiltered,
      playlistExpectedClipCount: playlistResume.playlistExpectedClipCount,
      timingReceipt: playlistResume.timingReceipt,
    };
  }
  return {
    range: resumeRunRange(resumeBanner),
    submittedClipIds: [...playlistResume.submittedClipIds],
    submittedClipIdsAreDurationFiltered:
      playlistResume.submittedClipIdsAreDurationFiltered,
    playlistExpectedClipCount: playlistResume.playlistExpectedClipCount,
    timingReceipt: playlistResume.timingReceipt,
  };
}

export function buildFailedEntriesRunOverrides(
  failedEntries: number[],
  playlistResume: PlaylistResumePayload
): RunOverrides {
  return {
    indices: [...failedEntries],
    submittedClipIds: [...playlistResume.submittedClipIds],
    submittedClipIdsAreDurationFiltered:
      playlistResume.submittedClipIdsAreDurationFiltered,
    playlistExpectedClipCount: playlistResume.playlistExpectedClipCount,
    timingReceipt: playlistResume.timingReceipt,
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
