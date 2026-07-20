import { describe, expect, it } from "vitest";

import type { CollectionSummary } from "../../shared/api";
import type { ResumeState } from "../lib/resume-state";
import {
  classifyUnattendedStop,
  createUnattendedManualState,
  nextUnattendedRunState,
  parseUnattendedLaunchHash,
  planUnattendedRun,
  type UnattendedRunRequest,
} from "../lib/unattended-run";

const COLLECTION: CollectionSummary = {
  id: "20260718-rjn-night-drive-collection",
  name: "night-drive",
  theme: "night-drive",
  status: "ready",
  pattern_count: 5,
  downloaded_count: 0,
};

const REQUEST: UnattendedRunRequest = {
  version: 1,
  requestId: "scheduled-20260718T120000Z",
  baseUrl: "http://rjn.localhost:7873",
  collectionId: COLLECTION.id,
  entryIndices: [0, 1, 2, 3, 4],
  downloadFormat: "wav",
  limits: {
    maxEntries: 2,
    maxConcurrentGenerations: 3,
    maxRetries: 1,
  },
};
const ENVELOPE = {
  version: 1 as const,
  baseUrl: REQUEST.baseUrl,
  nonce: "abcdefghijklmnopqrstuvwxyzABCDEFGH_1234567890",
};

function launchHash(value: unknown): string {
  const encoded = Buffer.from(JSON.stringify(value), "utf8").toString(
    "base64url"
  );
  return `#suno-helper-unattended=${encoded}`;
}

describe("parseUnattendedLaunchHash", () => {
  it("decodes and validates the scheduled launch request", () => {
    expect(parseUnattendedLaunchHash(launchHash(ENVELOPE))).toEqual(ENVELOPE);
  });

  it.each([
    ["unrelated fragment", "#create"],
    ["invalid base64 JSON", "#suno-helper-unattended=***"],
    [
      "non-loopback server",
      launchHash({ ...ENVELOPE, baseUrl: "https://evil.example" }),
    ],
    ["missing nonce", launchHash({ ...ENVELOPE, nonce: undefined })],
    ["short nonce", launchHash({ ...ENVELOPE, nonce: "short" })],
  ])("rejects %s", (_label, hash) => {
    if (hash === "#create") {
      expect(parseUnattendedLaunchHash(hash)).toBeNull();
      return;
    }
    expect(() => parseUnattendedLaunchHash(hash)).toThrow();
  });
});

describe("planUnattendedRun", () => {
  it("caps work and carries the remaining entries to the next scheduled run", () => {
    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: COLLECTION,
        entryCount: 5,
        resumeState: null,
      })
    ).toEqual({
      kind: "run",
      indices: [0, 1],
      deferredIndices: [2, 3, 4],
      previousSubmittedClipIds: [],
      playlistExpectedClipCount: undefined,
    });
  });

  it("resumes only unfinished indices and preserves observed clip ids", () => {
    const resumeState: ResumeState = {
      collectionId: COLLECTION.id,
      failedIndex: 2,
      total: 5,
      timestamp: Date.now(),
      remainingIndices: [2, 4],
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      playlistExpectedClipCount: 10,
    };

    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: COLLECTION,
        entryCount: 5,
        resumeState,
      })
    ).toEqual({
      kind: "run",
      indices: [2, 4],
      deferredIndices: [],
      previousSubmittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      playlistExpectedClipCount: 10,
    });
  });

  it("does not regenerate a collection that is already downloaded", () => {
    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: {
          ...COLLECTION,
          status: "downloaded",
          downloaded_count: 10,
          expected_file_count: 10,
          music_downloaded: true,
          suno_playlist_url: "https://suno.com/playlist/existing",
        },
        entryCount: 5,
        resumeState: null,
      })
    ).toEqual({ kind: "complete", reason: "already-downloaded" });
  });

  it("does not report completion when downloaded files lack a playlist URL", () => {
    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: { ...COLLECTION, status: "downloaded" },
        entryCount: 5,
        resumeState: null,
      })
    ).toMatchObject({ kind: "manual-intervention", reason: "run-error" });
  });

  it("does not complete while a durable failed entry remains", () => {
    const collection: CollectionSummary = {
      ...COLLECTION,
      status: "downloaded",
      downloaded_count: 8,
      expected_file_count: 8,
      music_downloaded: true,
      suno_playlist_url: "https://suno.com/playlist/partial",
    };
    const resumeState: ResumeState = {
      collectionId: COLLECTION.id,
      failedIndex: 5,
      total: 5,
      timestamp: Date.now(),
      failedIndices: [4],
      submittedClipIds: Array.from(
        { length: 8 },
        (_, index) => `clip-${index}`
      ),
      playlistExpectedClipCount: 8,
    };
    expect(
      planUnattendedRun({
        request: REQUEST,
        collection,
        entryCount: 5,
        resumeState,
      })
    ).not.toMatchObject({ kind: "complete" });
  });

  it("resumes playlist/download from saved clip ids without regenerating entries", () => {
    const resumeState: ResumeState = {
      collectionId: COLLECTION.id,
      failedIndex: 5,
      total: 5,
      timestamp: Date.now(),
      submittedClipIds: Array.from(
        { length: 10 },
        (_, index) => `clip-${index}`
      ),
      playlistExpectedClipCount: 10,
      playlistUrlsBeforeCreate: [],
    };

    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: COLLECTION,
        entryCount: 5,
        resumeState,
      })
    ).toEqual({
      kind: "retry-playlist",
      submittedClipIds: resumeState.submittedClipIds,
      expectedClipCount: 10,
    });
  });

  it("stops a legacy generation-complete checkpoint without a durable playlist baseline", () => {
    const resumeState: ResumeState = {
      collectionId: COLLECTION.id,
      failedIndex: 5,
      total: 5,
      timestamp: Date.now(),
      submittedClipIds: Array.from(
        { length: 10 },
        (_, index) => `clip-${index}`
      ),
      playlistExpectedClipCount: 10,
    };

    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: COLLECTION,
        entryCount: 5,
        resumeState,
      })
    ).toEqual({
      kind: "manual-intervention",
      reason: "existing-playlist",
      requiredAction:
        "playlist 作成前 baseline のない旧 checkpoint のため自動再作成できません。同名 playlist の有無と clip を確認してください。",
    });
  });

  it("retries only download when the playlist URL is already recorded", () => {
    const resumeState: ResumeState = {
      collectionId: COLLECTION.id,
      failedIndex: 5,
      total: 5,
      timestamp: Date.now(),
      submittedClipIds: Array.from(
        { length: 10 },
        (_, index) => `clip-${index}`
      ),
      playlistExpectedClipCount: 10,
    };
    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: {
          ...COLLECTION,
          suno_playlist_url: "https://suno.com/playlist/known",
        },
        entryCount: 5,
        resumeState,
      })
    ).toEqual({
      kind: "retry-download",
      submittedClipIds: resumeState.submittedClipIds,
      expectedClipCount: 10,
    });
  });

  it("stops instead of duplicating an existing playlist when recovery ids are unavailable", () => {
    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: {
          ...COLLECTION,
          suno_playlist_url: "https://suno.com/playlist/known",
        },
        entryCount: 5,
        resumeState: null,
      })
    ).toEqual({
      kind: "manual-intervention",
      reason: "existing-playlist",
      requiredAction:
        "既存 playlist の clip を選択して Download 再開を実行してください。新規生成は開始していません。",
    });
  });

  it("does not regenerate completed entries when the recovery clip ids are lost", () => {
    const resumeState: ResumeState = {
      collectionId: COLLECTION.id,
      failedIndex: 5,
      total: 5,
      timestamp: Date.now(),
    };
    expect(
      planUnattendedRun({
        request: REQUEST,
        collection: COLLECTION,
        entryCount: 5,
        resumeState,
      })
    ).toMatchObject({ kind: "manual-intervention", reason: "run-error" });
  });

  it("never widens a scheduled entry selection from stale resume state", () => {
    const resumeState: ResumeState = {
      collectionId: COLLECTION.id,
      failedIndex: 1,
      total: 5,
      timestamp: Date.now(),
      remainingIndices: [1, 2, 4],
    };
    expect(
      planUnattendedRun({
        request: { ...REQUEST, entryIndices: [2, 3] },
        collection: COLLECTION,
        entryCount: 5,
        resumeState,
      })
    ).toMatchObject({ kind: "run", indices: [2] });
  });
});

describe("classifyUnattendedStop", () => {
  it.each([
    ["Sign in to continue", "login-required"],
    ["captcha challenge が解消されません", "captcha-required"],
    ["Confirm credit usage before creating", "cost-confirmation-required"],
    ["Generate ボタンが見つかりません", "ui-incompatible"],
    ["network disconnected", "run-error"],
  ])("classifies %s", (message, expected) => {
    expect(classifyUnattendedStop(message)).toBe(expected);
  });
});

describe("nextUnattendedRunState", () => {
  it("records a resumable checkpoint when the per-run entry limit is reached", () => {
    expect(
      nextUnattendedRunState({
        request: REQUEST,
        progress: {
          phase: "stopped",
          index: 2,
          total: 5,
          message: "定期実行の entry 上限に到達しました",
        },
        deferredIndices: [2, 3, 4],
        now: 1234,
      })
    ).toMatchObject({
      requestId: REQUEST.requestId,
      collectionId: REQUEST.collectionId,
      status: "checkpoint",
      checkpoint: "entries",
      pendingEntryIndices: [2, 3, 4],
      requiredAction: "次回の定期実行で未完了 entry から再開します。",
      updatedAt: 1234,
    });
  });

  it("records manual action and a classified stop reason on fatal errors", () => {
    expect(
      nextUnattendedRunState({
        request: REQUEST,
        progress: {
          phase: "error",
          index: 1,
          total: 5,
          message: "captcha challenge が解消されません",
        },
        deferredIndices: [],
        now: 2000,
      })
    ).toMatchObject({
      status: "manual-intervention",
      checkpoint: "entries",
      stopReason: "captcha-required",
      requiredAction: "Suno の CAPTCHA を手動で解決してから再開してください。",
    });
  });

  it("marks the run complete only after the terminal phase", () => {
    expect(
      nextUnattendedRunState({
        request: REQUEST,
        progress: { phase: "finished", total: 5 },
        deferredIndices: [],
        now: 3000,
        verifiedComplete: true,
      })
    ).toMatchObject({
      status: "completed",
      checkpoint: "complete",
      pendingEntryIndices: [],
    });
  });
});

describe("createUnattendedManualState", () => {
  it("records an existing playlist as a safe manual stop", () => {
    expect(
      createUnattendedManualState({
        request: REQUEST,
        reason: "existing-playlist",
        message: "既存 playlist の回復情報がありません",
        checkpoint: "download",
        now: 4000,
      })
    ).toMatchObject({
      status: "manual-intervention",
      checkpoint: "download",
      stopReason: "existing-playlist",
      requiredAction:
        "既存 playlist の clip を選択して Download 再開を実行してください。",
      updatedAt: 4000,
    });
  });
});
