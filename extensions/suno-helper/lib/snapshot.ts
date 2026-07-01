// content script が SSOT として保持する進捗スナップショットの構築・更新を行う純関数 (#852)。
// itemStates の遷移ロジックを content (snapshot 構築) と popup (live 表示 / restore) で
// 二重定義しないため、ここに 1 箇所だけ集約する。useSunoRunner と content.ts の双方が import する。
import type { PromptEntry } from "../../shared/api";
import { PHASE, type ItemState, type Phase, type ProgressPayload, type SnapshotPayload } from "../../shared/constants";

/**
 * 連続実行の開始時スナップショット。全 idle・isRunning=true・entries を保持して初期化する。
 * playlistName は collection mode のみ渡され、再 open 復元時の display 用に保持する (#854)。
 * 単一ファイル mode では省略され undefined（playlist phase を実行しない）。
 */
export function initSnapshot(entries: PromptEntry[], playlistName?: string): SnapshotPayload {
  return {
    entries,
    itemStates: entries.map(() => "idle"),
    isRunning: true,
    progress: { phase: PHASE.INJECTING, total: entries.length },
    playlistName,
  };
}

/** itemStates を phase に応じて遷移させる（INJECTING / DONE / ENTRY_FAILED のみ、他 phase は不変）。非破壊で新配列を返す。 */
export function nextItemStates(prev: ItemState[], phase: Phase, index?: number): ItemState[] {
  if (phase === PHASE.INJECTING) {
    return prev.map((s, i) => (i === index ? "active" : s === "active" ? "idle" : s));
  }
  if (phase === PHASE.DONE) {
    return prev.map((s, i) => (i === index ? "done" : s));
  }
  if (phase === PHASE.ENTRY_FAILED) {
    // リトライ上限まで失敗しスキップされた entry (#948)。run 全体は継続する。
    return prev.map((s, i) => (i === index ? "failed" : s));
  }
  return prev;
}

/** 連続実行を終える phase（以降 isRunning=false）。snapshot 自体は破棄せず再 open 表示用に残す。 */
export function isTerminalPhase(phase: Phase): boolean {
  return phase === PHASE.FINISHED || phase === PHASE.STOPPED || phase === PHASE.ERROR;
}

/** progress 受信でスナップショットを更新する。終了 phase で isRunning=false（entries/itemStates は保持）。 */
export function applyProgress(snap: SnapshotPayload, payload: ProgressPayload): SnapshotPayload {
  const nextAcceptedClipIds =
    payload.acceptedClipIds && payload.acceptedClipIds.length > 0
      ? Array.from(new Set([...(snap.yieldAcceptedClipIds ?? []), ...payload.acceptedClipIds]))
      : snap.yieldAcceptedClipIds;
  const nextYieldRetryCounts =
    payload.index !== undefined && payload.yieldRetryCount !== undefined
      ? { ...(snap.yieldRetryCounts ?? {}), [payload.index]: payload.yieldRetryCount }
      : snap.yieldRetryCounts;
  return {
    ...snap,
    itemStates: nextItemStates(snap.itemStates, payload.phase, payload.index),
    progress: payload,
    isRunning: isTerminalPhase(payload.phase) ? false : snap.isRunning,
    // ERROR phase でのみ failedIndex を確定する（chrome.storage の resume state と二重化, #872）。
    // 非 ERROR phase では既存値を保つ。ERROR が index 無し（playlist phase 等）なら undefined のまま。
    // #924: payload.index は resolveInterruptIndex で「次に実行する index」に補正済みのため、
    // ここで受け取った値をそのまま failedIndex として記録すれば chrome.storage 側と意味が一致する。
    failedIndex: payload.phase === PHASE.ERROR ? payload.index : snap.failedIndex,
    // ENTRY_FAILED の受信ごとにスキップ済み index を蓄積する (#948)。popup の「失敗分のみ再実行」が消費。
    failedIndices:
      payload.phase === PHASE.ENTRY_FAILED && payload.index !== undefined
        ? [...(snap.failedIndices ?? []), payload.index]
        : snap.failedIndices,
    yieldAcceptedClipIds: nextAcceptedClipIds,
    yieldRetryCounts: nextYieldRetryCounts,
  };
}
