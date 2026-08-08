import { storage } from "wxt/utils/storage";

export const CHALLENGE_LOG_MAX_RECORDS = 100;

export type ChallengeLogSource =
  | "preflight"
  | "before-create"
  | "generation-wait";

export interface ChallengeLogRecord {
  timestamp: number;
  source: ChallengeLogSource;
  runMode: "serial" | "queue" | null;
  unattended: boolean;
  entryIndex: number | null;
  total: number | null;
  challengeLevel: number;
  recentCreateCount: number;
}

const CHALLENGE_LOG_STORAGE_KEY = "sunoChallengeLog";

let cachedItem: ReturnType<
  typeof storage.defineItem<ChallengeLogRecord[]>
> | null = null;
let appendQueue: Promise<void> = Promise.resolve();

function challengeLogItem() {
  if (!cachedItem) {
    cachedItem = storage.defineItem<ChallengeLogRecord[]>(
      `local:${CHALLENGE_LOG_STORAGE_KEY}`,
      { fallback: [] }
    );
  }
  return cachedItem;
}

function allowlistedRecord(input: ChallengeLogRecord): ChallengeLogRecord {
  return {
    timestamp: input.timestamp,
    source: input.source,
    runMode: input.runMode,
    unattended: input.unattended,
    entryIndex: input.entryIndex,
    total: input.total,
    challengeLevel: input.challengeLevel,
    recentCreateCount: input.recentCreateCount,
  };
}

async function appendRecord(record: ChallengeLogRecord): Promise<void> {
  try {
    const current = (await challengeLogItem().getValue()) ?? [];
    const next = [...current, record].slice(-CHALLENGE_LOG_MAX_RECORDS);
    await challengeLogItem().setValue(next);
  } catch (error) {
    console.warn("[suno-helper] challenge log の保存に失敗しました:", error);
  }
}

export function appendChallengeRecord(
  input: ChallengeLogRecord
): Promise<void> {
  const record = allowlistedRecord(input);
  const pending = appendQueue.then(() => appendRecord(record));
  appendQueue = pending;
  return pending;
}

export async function readChallengeLog(): Promise<ChallengeLogRecord[]> {
  try {
    return (await challengeLogItem().getValue()) ?? [];
  } catch (error) {
    console.warn("[suno-helper] challenge log の読込に失敗しました:", error);
    return [];
  }
}
