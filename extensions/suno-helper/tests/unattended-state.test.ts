// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { exposeUnattendedRunState } from "../lib/unattended-state";

describe("exposeUnattendedRunState", () => {
  it("publishes a machine-readable manual intervention notification", () => {
    exposeUnattendedRunState(document.documentElement, {
      requestId: "scheduled-test",
      collectionId: "collection",
      status: "manual-intervention",
      checkpoint: "download",
      pendingEntryIndices: [],
      stopReason: "captcha-required",
      requiredAction: "CAPTCHA を手動で解決してください。",
      updatedAt: 1,
    });

    expect(document.documentElement.dataset).toMatchObject({
      sunoUnattendedRequestId: "scheduled-test",
      sunoUnattendedCollectionId: "collection",
      sunoUnattendedStatus: "manual-intervention",
      sunoUnattendedCheckpoint: "download",
      sunoUnattendedStopReason: "captcha-required",
      sunoUnattendedRequiredAction: "CAPTCHA を手動で解決してください。",
    });
  });

  it("clears stale manual fields when the next run completes", () => {
    document.documentElement.dataset.sunoUnattendedStopReason =
      "captcha-required";
    document.documentElement.dataset.sunoUnattendedRequiredAction = "manual";
    exposeUnattendedRunState(document.documentElement, {
      requestId: "scheduled-test-2",
      collectionId: "collection",
      status: "completed",
      checkpoint: "complete",
      pendingEntryIndices: [],
      updatedAt: 2,
    });

    expect(document.documentElement.dataset.sunoUnattendedStatus).toBe(
      "completed"
    );
    expect(
      document.documentElement.dataset.sunoUnattendedStopReason
    ).toBeUndefined();
    expect(
      document.documentElement.dataset.sunoUnattendedRequiredAction
    ).toBeUndefined();
  });
});
