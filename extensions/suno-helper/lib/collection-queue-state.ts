import { storage } from "wxt/utils/storage";

import {
  COLLECTION_QUEUE_STATE_KEY,
  type RunModeId,
} from "../../shared/constants";

export type CollectionQueueItemStatus = "pending" | "succeeded" | "failed";

export interface CollectionQueueItem {
  collectionId: string;
  status: CollectionQueueItemStatus;
  message?: string;
}

export type CollectionQueueStatus = "running" | "paused" | "completed";

export interface CollectionQueueState {
  version: 1;
  queueId: string;
  baseUrl: string;
  items: CollectionQueueItem[];
  currentIndex: number;
  status: CollectionQueueStatus;
  runMode: RunModeId;
  regenerateDurationOutliers: boolean;
  createdAt: number;
  updatedAt: number;
}

export interface CollectionQueueTransition {
  state: CollectionQueueState;
  requiresPageReload: boolean;
}

interface CreateCollectionQueueOptions {
  queueId: string;
  baseUrl: string;
  collectionIds: string[];
  runMode: RunModeId;
  regenerateDurationOutliers: boolean;
  now: number;
}

interface RecordCollectionResultOptions {
  collectionId: string;
  outcome: "succeeded" | "failed";
  message?: string;
  now: number;
}

interface SettleCollectionQueueRunOptions {
  collectionId: string;
  phase: "finished" | "error" | "stopped";
  failedEntryCount: number;
  message?: string;
  now: number;
}

function requireNonEmpty(value: string, field: string): string {
  if (value.trim().length === 0) {
    throw new Error(`${field} must be non-empty`);
  }
  return value;
}

export function orderSelectedCollectionIds(
  collections: ReadonlyArray<{ id: string }>,
  selectedIds: ReadonlySet<string>
): string[] {
  return collections
    .map((collection) => collection.id)
    .filter((id) => selectedIds.has(id));
}

export function createCollectionQueue(
  options: CreateCollectionQueueOptions
): CollectionQueueState {
  if (options.collectionIds.length === 0) {
    throw new Error("collection queue requires at least one collection");
  }
  const collectionIds = options.collectionIds.map((id, index) =>
    requireNonEmpty(id, `collectionIds[${index}]`)
  );
  if (new Set(collectionIds).size !== collectionIds.length) {
    throw new Error("collectionIds must be unique");
  }
  return {
    version: 1,
    queueId: requireNonEmpty(options.queueId, "queueId"),
    baseUrl: requireNonEmpty(options.baseUrl, "baseUrl"),
    items: collectionIds.map((collectionId) => ({
      collectionId,
      status: "pending",
    })),
    currentIndex: 0,
    status: "running",
    runMode: options.runMode,
    regenerateDurationOutliers: options.regenerateDurationOutliers,
    createdAt: options.now,
    updatedAt: options.now,
  };
}

export function currentCollectionId(
  state: CollectionQueueState
): string | null {
  if (state.status === "completed") {
    return null;
  }
  return state.items[state.currentIndex]?.collectionId ?? null;
}

export function recordCollectionResult(
  state: CollectionQueueState,
  options: RecordCollectionResultOptions
): CollectionQueueTransition {
  if (state.status !== "running") {
    throw new Error("collection queue must be running");
  }
  const activeCollectionId = currentCollectionId(state);
  if (activeCollectionId !== options.collectionId) {
    throw new Error(
      `collection queue expected ${activeCollectionId ?? "none"}, got ${options.collectionId}`
    );
  }
  const items = state.items.map((item, index) =>
    index === state.currentIndex
      ? {
          collectionId: item.collectionId,
          status: options.outcome,
          ...(options.message ? { message: options.message } : {}),
        }
      : item
  );
  const currentIndex = state.currentIndex + 1;
  const completed = currentIndex >= items.length;
  return {
    state: {
      ...state,
      items,
      currentIndex,
      status: completed ? "completed" : "running",
      updatedAt: options.now,
    },
    requiresPageReload: !completed,
  };
}

export function pauseCollectionQueue(
  state: CollectionQueueState,
  now: number
): CollectionQueueState {
  if (state.status !== "running") {
    return state;
  }
  return { ...state, status: "paused", updatedAt: now };
}

export function resumeCollectionQueue(
  state: CollectionQueueState,
  now: number
): CollectionQueueState {
  if (state.status !== "paused") {
    return state;
  }
  return { ...state, status: "running", updatedAt: now };
}

export function settleCollectionQueueRun(
  state: CollectionQueueState,
  options: SettleCollectionQueueRunOptions
): CollectionQueueTransition {
  if (currentCollectionId(state) !== options.collectionId) {
    throw new Error("collection queue settlement does not match current item");
  }
  if (options.phase === "stopped") {
    return {
      state: pauseCollectionQueue(state, options.now),
      requiresPageReload: false,
    };
  }
  const succeeded =
    options.phase === "finished" && options.failedEntryCount === 0;
  return recordCollectionResult(state, {
    collectionId: options.collectionId,
    outcome: succeeded ? "succeeded" : "failed",
    ...(!succeeded && options.message ? { message: options.message } : {}),
    now: options.now,
  });
}

let cachedItem: ReturnType<
  typeof storage.defineItem<CollectionQueueState | null>
> | null = null;

function collectionQueueItem() {
  if (!cachedItem) {
    cachedItem = storage.defineItem<CollectionQueueState | null>(
      `local:${COLLECTION_QUEUE_STATE_KEY}`,
      { fallback: null }
    );
  }
  return cachedItem;
}

export function readCollectionQueue(): Promise<CollectionQueueState | null> {
  return collectionQueueItem().getValue();
}

export function writeCollectionQueue(
  state: CollectionQueueState
): Promise<void> {
  return collectionQueueItem().setValue(state);
}

export function removeCollectionQueue(): Promise<void> {
  return collectionQueueItem().removeValue();
}

export async function settleStoredCollectionQueueRun(
  queueId: string,
  options: SettleCollectionQueueRunOptions
): Promise<CollectionQueueTransition | null> {
  const state = await readCollectionQueue();
  if (!state || state.queueId !== queueId) {
    return null;
  }
  const transition = settleCollectionQueueRun(state, options);
  await writeCollectionQueue(transition.state);
  return transition;
}
