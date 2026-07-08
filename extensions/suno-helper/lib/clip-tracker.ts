// bridge が観測した clip status の集計 (#948)。
//
// in-flight の SSOT。bridge（MAIN world）からの観測イベントを集約し、
//   - in-flight 数 = 観測済み clip のうち status が終端（complete/error）でないもの
//   - inject ACK   = generate レスポンスの観測回数（submission count）の増分
// を提供する。DOM の「Remix disabled」プロキシ（生成完了後も disabled が残り過大カウント、
// 実測 20 中 16 誤判定）を置き換える一次情報になる。
//
// passive 合流: feed 観測で現れた未終端 clip は、この run の投入でなくても集計に加える。
// 前 run の残留 in-flight や手動投入分もキュー slot を占有するため、数えないと過剰投入になる。
import { TERMINAL_CLIP_STATUSES, type ObservedClip } from "../../shared/constants";

const TERMINAL = new Set<string>(TERMINAL_CLIP_STATUSES);

export interface ClipTracker {
  /** generate レスポンス観測（= この run の投入受理）。submission count を進め、clip を登録する。 */
  registerSubmitted(clips: ObservedClip[]): void;
  /** feed 観測で status を更新する。未知の未終端 clip は passive 合流で登録する。 */
  applyFeedStatuses(clips: ObservedClip[]): void;
  /**
   * active feed poll（ID 指定照会, FEED_V3_POLL_RESPONSE）の応答を反映する。
   * passive feed と違い、未知 clip でも終端 status を含めて登録する: reload 後の resume では
   * 保存済み clip が照会時点で complete 済みのことが多く、終端を落とすと getPendingIdsByIds が
   * 永遠に pending 扱いして完了待ちが stall するため（#1586）。
   */
  applyRequestedStatuses(clips: ObservedClip[]): void;
  /** 終端 status に達していない観測済み clip 数。 */
  getInFlightCount(): number;
  /** 未終端 clip の id 一覧（active feed poll の照会対象）。 */
  getPendingIds(): string[];
  /** 指定した id のうち、まだ終端 status に達していない id 一覧。 */
  getPendingIdsByIds(ids: string[]): string[];
  /** この run で投入した clip のうち、まだ終端 status に達していない id 一覧。 */
  getPendingSubmittedIds(): string[];
  /** この run の generate レスポンスで観測した clip id 一覧。playlist 対象の SSOT。 */
  getSubmittedIds(): string[];
  /** duration yield guard を通過した submitted clip id を記録する。 */
  markAccepted(ids: string[]): void;
  /** duration yield guard を通過した submitted clip id 一覧。 */
  getAcceptedSubmittedIds(): string[];
  /** duration yield guard で不採用になった attempt の clip id を playlist 対象から外す。 */
  dropSubmittedIds(ids: string[]): void;
  /** 観測済み clip の duration (sec)。未観測または generate/feed に duration が無い場合は undefined。 */
  getDuration(clipId: string): number | undefined;
  /** run 開始時に playlist 対象 ID だけを初期化する。status 集計は残す。 */
  clearSubmittedIds(): void;
  /** generate / feed のいずれかを 1 度でも観測したか。false の間は DOM プロキシへ縮退する。 */
  hasObservedAnyTraffic(): boolean;
  /** generate レスポンスの累計観測回数。inject ACK の marker に使う。 */
  submissionCount(): number;
  /** 最後に feed 観測（passive / active 問わず）を適用した時刻 (ms)。stale 判定に使う。 */
  lastFeedAt(): number;
  /** 観測済み clip 集合（status 含む）が最後に変化した時刻 (ms)。stall 判定（後続 PR）に使う。 */
  lastChangeAt(): number;
}

export function createClipTracker(now: () => number = Date.now): ClipTracker {
  const statusById = new Map<string, string>();
  const durationById = new Map<string, number>();
  const submittedById = new Map<string, true>();
  const acceptedSubmittedById = new Map<string, true>();
  let submissions = 0;
  let observedGenerate = false;
  let observedFeed = false;
  let feedAt = 0;
  let changeAt = 0;

  function isValidDuration(duration: unknown): duration is number {
    return typeof duration === "number" && Number.isFinite(duration) && duration >= 0;
  }

  function recordDuration(clip: ObservedClip): void {
    const duration = clip.duration ?? clip.durationSec;
    if (isValidDuration(duration)) {
      durationById.set(clip.id, duration);
    }
  }

  function upsert(clip: ObservedClip): void {
    const prev = statusById.get(clip.id);
    if (prev !== clip.status) {
      statusById.set(clip.id, clip.status);
      changeAt = now();
    }
    const duration = clip.duration ?? clip.durationSec;
    if (isValidDuration(duration) && durationById.get(clip.id) !== duration) {
      durationById.set(clip.id, duration);
      changeAt = now();
    }
  }

  return {
    registerSubmitted(clips) {
      observedGenerate = true;
      submissions += 1;
      for (const clip of clips) {
        submittedById.set(clip.id, true);
        recordDuration(clip);
        upsert(clip);
      }
    },
    applyFeedStatuses(clips) {
      observedFeed = true;
      feedAt = now();
      for (const clip of clips) {
        recordDuration(clip);
        // 既知 clip は status 更新。未知 clip は未終端のみ passive 合流する
        // （終端済みの未知 clip は slot を占有しないため、集計を無駄に膨らませない）。
        if (statusById.has(clip.id) || !TERMINAL.has(clip.status)) {
          upsert(clip);
        }
      }
    },
    applyRequestedStatuses(clips) {
      observedFeed = true;
      feedAt = now();
      for (const clip of clips) {
        recordDuration(clip);
        // ID 指定照会の応答は終端 status も含めて登録する（interface コメント参照, #1586）。
        // 終端 clip は in-flight / pending の各集計から自然に外れるため過大カウントにはならない。
        upsert(clip);
      }
    },
    getInFlightCount() {
      let count = 0;
      for (const status of statusById.values()) {
        if (!TERMINAL.has(status)) {
          count += 1;
        }
      }
      return count;
    },
    getPendingIds() {
      const ids: string[] = [];
      for (const [id, status] of statusById) {
        if (!TERMINAL.has(status)) {
          ids.push(id);
        }
      }
      return ids;
    },
    getPendingIdsByIds(ids) {
      return ids.filter((id) => {
        const status = statusById.get(id);
        return !status || !TERMINAL.has(status);
      });
    },
    getPendingSubmittedIds() {
      const ids: string[] = [];
      for (const id of submittedById.keys()) {
        const status = statusById.get(id);
        if (!status || !TERMINAL.has(status)) {
          ids.push(id);
        }
      }
      return ids;
    },
    getSubmittedIds() {
      return Array.from(submittedById.keys());
    },
    markAccepted(ids) {
      for (const id of ids) {
        if (submittedById.has(id)) {
          acceptedSubmittedById.set(id, true);
        }
      }
    },
    getAcceptedSubmittedIds() {
      return Array.from(acceptedSubmittedById.keys());
    },
    dropSubmittedIds(ids) {
      for (const id of ids) {
        submittedById.delete(id);
        acceptedSubmittedById.delete(id);
      }
    },
    getDuration(clipId) {
      return durationById.get(clipId);
    },
    clearSubmittedIds() {
      submittedById.clear();
      acceptedSubmittedById.clear();
    },
    hasObservedAnyTraffic() {
      return observedGenerate || observedFeed;
    },
    submissionCount() {
      return submissions;
    },
    lastFeedAt() {
      return feedAt;
    },
    lastChangeAt() {
      return changeAt;
    },
  };
}
