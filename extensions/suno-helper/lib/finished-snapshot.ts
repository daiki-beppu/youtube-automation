// run 一式完了時リロード (#1411) と popup 進捗復元 (#852) の橋渡し。
//
// リロードは content script の in-memory snapshot（queryProgress の復元 SSOT）を破棄するため、
// run 中に popup を閉じていた運用者が完了後に再 open しても「完走したか」「per-entry の
// done/failed」を確認できなくなる。FINISHED 到達時（リロード予約の直前）に snapshot を
// chrome.storage.local へ退避し、リロード後の queryProgress が in-memory 不在時の
// fallback として読むことで、直近完了 run の結果表示を引き継ぐ。
//
// stale 化の防止: timestamp を付与し、読み出し時に閾値超過なら破棄する。
// 次 run 開始（initSnapshot）でも消去する（新しい実行が始まったら前 run の完了表示は不要）。
//
// I/O は resume-state.ts と同じく storage item を遅延生成する（storage.defineItem は呼ぶと
// 内部で chrome.runtime へアクセスするため、node 環境 (vitest) で純関数だけを import した
// ときに副作用を起こさないため）。
import { storage } from "wxt/utils/storage";

import {
  FINISHED_SNAPSHOT_KEY,
  type SnapshotPayload,
} from "../../shared/constants";

/** 退避する直近完了 run の snapshot と stale 判定メタ情報。 */
export interface FinishedSnapshotState {
  /** FINISHED 適用済みの snapshot（isRunning=false、itemStates は done/failed 確定済み）。 */
  snapshot: SnapshotPayload;
  /** 退避時刻 (epoch ms)。stale 判定に使う。 */
  timestamp: number;
}

/** 退避 snapshot の stale 判定閾値 (ms)。resume state の再開バナー (#872) と同じ 24 時間。 */
export const FINISHED_SNAPSHOT_STALE_MS = 24 * 60 * 60 * 1000;

/**
 * 退避 snapshot が復元表示に足る鮮度かを判定する。境界はちょうど閾値まで inclusive
 * （shouldShowResumeBanner と同じ規約）。now を注入可能にし、純関数として時刻依存を排してテストする。
 */
export function isFinishedSnapshotFresh(
  state: FinishedSnapshotState | null,
  now: number
): boolean {
  if (!state) {
    return false;
  }
  return now - state.timestamp <= FINISHED_SNAPSHOT_STALE_MS;
}

// --- chrome.storage.local I/O（storage item は遅延生成。理由はファイル冒頭コメント参照） ---

let cachedItem: ReturnType<
  typeof storage.defineItem<FinishedSnapshotState | null>
> | null = null;

function finishedSnapshotItem() {
  if (!cachedItem) {
    cachedItem = storage.defineItem<FinishedSnapshotState | null>(
      `local:${FINISHED_SNAPSHOT_KEY}`,
      {
        fallback: null,
      }
    );
  }
  return cachedItem;
}

/** FINISHED snapshot を退避する（既存があれば上書き）。リロード予約の直前に await で呼ぶこと。 */
export async function writeFinishedSnapshot(
  state: FinishedSnapshotState
): Promise<void> {
  await finishedSnapshotItem().setValue(state);
}

/**
 * 退避済みの直近完了 run の snapshot を読む。未退避・stale は null。
 * stale 分は読み捨てず消去する（次回以降の read で毎回 stale 判定するのを避ける衛生処理。
 * 消去失敗しても戻り値には影響しないため fire-and-forget）。
 */
export async function readFreshFinishedSnapshot(
  now: number
): Promise<SnapshotPayload | null> {
  const state = await finishedSnapshotItem().getValue();
  if (!state) {
    return null;
  }
  if (!isFinishedSnapshotFresh(state, now)) {
    void finishedSnapshotItem().setValue(null);
    return null;
  }
  return state.snapshot;
}

/** 退避済み snapshot を消去する。次 run 開始（initSnapshot）時に呼ぶ。 */
export async function clearFinishedSnapshot(): Promise<void> {
  await finishedSnapshotItem().setValue(null);
}
