// ERROR 停止からの途中再開 (#872) を支える純ロジックと chrome.storage I/O を 1 箇所に集約する。
//
// 純関数 (shouldShowResumeBanner / resumeRunRange) は content / popup の双方が import し、
// バナー表示条件と再開 range の解決を二重定義しないための SSOT とする。
// I/O (readResumeState / writeResumeState / clearResumeStateForCollection) は @wxt-dev/storage の
// 型付き wrapper で chrome.storage.local を読み書きする。storage.defineItem は呼ぶと内部で
// chrome.runtime へアクセスするため、node 環境 (vitest) で純関数だけを import したときに副作用を
// 起こさないよう遅延生成する（純関数テスト resume-state.test.ts を壊さないため）。
import { storage } from "wxt/utils/storage";

import { CLIPS_PER_REQUEST, RESUME_STATE_KEY } from "../../shared/constants";
import type { DurationFilter } from "../../shared/api";

/** ERROR 停止時に永続化する再開メタ情報 (#872)。 */
export interface ResumeState {
  /** 停止した collection の識別子（popup 選択中の collection id）。 */
  collectionId: string;
  /**
   * 次に実行する 0-based index（投入済み entry を含まない）(#924)。
   * - Generate click 前に中断: 中断 entry の index（再開時に再生成する）。
   * - Generate click 済み・受理確認済み: currentIndex + 1（再開時に重複生成しない）。
   * - Generate click 済み・silent drop 確定（InjectNotAcknowledgedError）: currentIndex（再開時に再生成する）。
   * `failedIndex === total` のときは全 entry 投入済みを意味し、再開時は playlist phase のみ実行される。
   */
  failedIndex: number;
  /** 連続実行対象の総 entry 数。 */
  total: number;
  /** 永続化時刻 (epoch ms)。stale 判定に使う。 */
  timestamp: number;
  /** リトライ上限まで失敗しスキップされた entry の 0-based index 一覧 (#948)。
   * 「失敗分のみ再実行」導線が run({indices}) へ渡す。旧 state には無い optional（後方互換）。 */
  failedIndices?: number[];
  /** 明示 indices 実行が途中中断したとき、再開で実行すべき残りの 0-based index 列。 */
  remainingIndices?: number[];
  /** playlist 追加対象として generate response から観測済みの clip ID 一覧。 */
  submittedClipIds?: string[];
  /** collection 単位 duration guard 閾値。復元後も同じ OK/NG 判定を維持する。 */
  durationFilter?: DurationFilter;
  /** true のとき submittedClipIds は resume 保存時点で OK clip IDs に正規化済み。 */
  submittedClipIdsAreDurationFiltered?: boolean;
  /** duration filter 後に playlist 追加・download へ採用する OK clip 件数。 */
  playlistExpectedClipCount?: number;
}

/** content へ渡す 0-based inclusive な実行範囲。 */
export interface RunRange {
  start: number;
  end: number;
}

/**
 * 再開バナーの表示・direct resume に必要な最小情報 (#872 要件3)。
 * chrome.storage 由来の {@link ResumeState} と content snapshot 由来 (failedIndex/total) の
 * 2 系統の復元ソースを同一形へ正規化し、二重化した復元経路を 1 つの UI 入力に集約する。
 */
export interface ResumeBanner {
  failedIndex: number;
  total: number;
  remainingIndices?: number[];
}

/** 再開バナーの stale 判定閾値（24 時間, ms）。要件4。 */
export const RESUME_STALE_MS = 24 * 60 * 60 * 1000;

/**
 * 起動時に再開バナーを表示すべきか判定する (要件4)。
 *   - state 無し → 表示しない
 *   - collectionId が選択中と不一致 → 表示しない（別 collection 選択中）
 *   - timestamp が RESUME_STALE_MS より古い → 表示しない（stale）。境界はちょうど閾値まで inclusive
 * now を注入可能にし、純関数として時刻依存を排してテストする。
 */
export function shouldShowResumeBanner(state: ResumeState | null, selectedCollectionId: string, now: number): boolean {
  if (!state) {
    return false;
  }
  if (state.collectionId !== selectedCollectionId) {
    return false;
  }
  return now - state.timestamp <= RESUME_STALE_MS;
}

/**
 * バナー承認 → 1-click 自動再開で run() へ直接渡す 0-based inclusive range を構築する (#892 要件6)。
 * 失敗 entry (0-based failedIndex) から末尾 (total-1) まで。React state は次レンダ反映で closure から
 * 読めないため、acceptResume はこの純関数でローカルに range を組み立てて run({ range }) へ引数で渡す。
 */
export function resumeRunRange(banner: ResumeBanner): RunRange {
  return { start: banner.failedIndex, end: banner.total - 1 };
}

/**
 * 中断時に persist / emit する「次に実行する 0-based index」を決定する (#924)。
 *   - submitted（当該 entry の Generate を click 済み）かつ未受理確定でない → currentIndex + 1（再生成しない）
 *   - それ以外（click 前の中断 / silent drop 確定）→ currentIndex（再開時に再生成）
 * currentIndex + 1 === total のケースは playlist-phase persist (failedIndex=total) と同義になり、
 * resumeRunRange → {start: total, end: total-1} → runAll 0 回ループ → playlist 追加のみ実行となる。
 */
export function resolveInterruptIndex(currentIndex: number, submitted: boolean, isNotAcknowledged: boolean): number {
  return submitted && !isNotAcknowledged ? currentIndex + 1 : currentIndex;
}

/** 再開前の観測 ID と今回 run の観測 ID を合成する。件数不一致は部分 playlist を防ぐため fail-loud にする。 */
export function resolvePlaylistClipIds(
  previousSubmittedClipIds: string[],
  currentSubmittedClipIds: string[],
  expectedClipCount: number,
): string[] {
  const clipIds = Array.from(new Set([...previousSubmittedClipIds, ...currentSubmittedClipIds]));
  if (clipIds.length === 0) {
    throw new Error("playlist 対象の clip ID が 0 件です。bridge が clip を観測できなかった可能性があります。");
  }
  if (clipIds.length !== expectedClipCount) {
    throw new Error(`playlist 対象の clip ID 数が不足しています: expected ${expectedClipCount}, got ${clipIds.length}`);
  }
  return clipIds;
}

/** 旧 ResumeState には期待件数が無いため、collection 全体の entry 数から復元して部分 playlist を防ぐ。 */
export function resolvePlaylistExpectedClipCountForResume(
  savedExpectedClipCount: number | undefined,
  totalEntries: number,
): number {
  return savedExpectedClipCount ?? totalEntries * CLIPS_PER_REQUEST;
}

// --- chrome.storage.local I/O（storage item は遅延生成。理由はファイル冒頭コメント参照） ---

let cachedItem: ReturnType<typeof storage.defineItem<ResumeState | null>> | null = null;

function resumeStateItem() {
  if (!cachedItem) {
    cachedItem = storage.defineItem<ResumeState | null>(`local:${RESUME_STATE_KEY}`, { fallback: null });
  }
  return cachedItem;
}

/** 永続化済みの resume state を読む。未設定は null。 */
export async function readResumeState(): Promise<ResumeState | null> {
  return resumeStateItem().getValue();
}

/** ERROR 停止時の resume state を書き込む（既存があれば上書き）。 */
export async function writeResumeState(state: ResumeState): Promise<void> {
  await resumeStateItem().setValue(state);
}

/**
 * 指定 collection の resume state を消去する (要件5)。
 * 保存中の state が別 collection のものなら触らない（取り違え消去を防ぐ）。
 */
export async function clearResumeStateForCollection(collectionId: string): Promise<void> {
  const current = await resumeStateItem().getValue();
  if (current && current.collectionId === collectionId) {
    await resumeStateItem().setValue(null);
  }
}
