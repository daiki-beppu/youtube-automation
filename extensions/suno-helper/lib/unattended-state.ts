import { storage } from "wxt/utils/storage";

import { UNATTENDED_RUN_STATE_KEY } from "../../shared/constants";
import type { UnattendedRunState } from "./unattended-run";

let cachedItem: ReturnType<
  typeof storage.defineItem<UnattendedRunState | null>
> | null = null;

function unattendedStateItem() {
  if (!cachedItem) {
    cachedItem = storage.defineItem<UnattendedRunState | null>(
      `local:${UNATTENDED_RUN_STATE_KEY}`,
      { fallback: null }
    );
  }
  return cachedItem;
}

export function readUnattendedRunState(): Promise<UnattendedRunState | null> {
  return unattendedStateItem().getValue();
}

export function exposeUnattendedRunState(
  root: HTMLElement,
  state: UnattendedRunState
): void {
  root.dataset.sunoUnattendedRequestId = state.requestId;
  root.dataset.sunoUnattendedCollectionId = state.collectionId;
  root.dataset.sunoUnattendedStatus = state.status;
  root.dataset.sunoUnattendedCheckpoint = state.checkpoint;
  if (state.stopReason) {
    root.dataset.sunoUnattendedStopReason = state.stopReason;
  } else {
    delete root.dataset.sunoUnattendedStopReason;
  }
  if (state.requiredAction) {
    root.dataset.sunoUnattendedRequiredAction = state.requiredAction;
  } else {
    delete root.dataset.sunoUnattendedRequiredAction;
  }
}

export async function writeUnattendedRunState(
  state: UnattendedRunState
): Promise<void> {
  await unattendedStateItem().setValue(state);
  if (typeof document !== "undefined") {
    exposeUnattendedRunState(document.documentElement, state);
  }
}
