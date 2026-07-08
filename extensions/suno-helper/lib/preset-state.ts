// 連続実行ペーシングの jitter 算出と run mode の chrome.storage I/O を集約する。
// speed preset 永続化は #1573 で廃止済み。queue/serial の選択だけ #1586 で保持する。
import { storage } from "wxt/utils/storage";

import { RUN_MODE_STORAGE_KEY, type RunModeId } from "../../shared/constants";

export type { RunModeId };

/** 既定の投入方式 (#1586): 既存の直列実行を維持する。 */
export const DEFAULT_RUN_MODE_ID: RunModeId = "serial";

/**
 * 基準待機 baseMs に ±jitterMs の振れを加える。
 * `baseMs + (random()*2-1)*jitterMs` で [base-jitter, base+jitter] に分布させる。
 * random は DI 可能（テストで min/max を pin する）。production の content からは省略呼び出しで Math.random を使う。
 */
export function applyJitter(baseMs: number, jitterMs: number, random: () => number = Math.random): number {
  return baseMs + (random() * 2 - 1) * jitterMs;
}

// --- chrome.storage.local I/O（storage item は遅延生成。理由はファイル冒頭コメント参照） ---

function createRunModeItem() {
  return storage.defineItem<RunModeId>(`local:${RUN_MODE_STORAGE_KEY}`, {
    fallback: DEFAULT_RUN_MODE_ID,
  });
}

let cachedRunModeItem: ReturnType<typeof createRunModeItem> | null = null;

function runModeItem(): ReturnType<typeof createRunModeItem> {
  if (!cachedRunModeItem) {
    cachedRunModeItem = createRunModeItem();
  }
  return cachedRunModeItem;
}

export async function readRunModeId(): Promise<RunModeId> {
  return runModeItem().getValue();
}

export async function writeRunModeId(id: RunModeId): Promise<void> {
  await runModeItem().setValue(id);
}
