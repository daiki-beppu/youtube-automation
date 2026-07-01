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
  /** 終端 status に達していない観測済み clip 数。 */
  getInFlightCount(): number;
  /** 未終端 clip の id 一覧（active feed poll の照会対象）。 */
  getPendingIds(): string[];
  /** この run で投入した clip のうち、まだ終端 status に達していない id 一覧。 */
  getPendingSubmittedIds(): string[];
  /** この run の generate レスポンスで観測した clip id 一覧。playlist 対象の SSOT。 */
  getSubmittedIds(): string[];
  /** id に紐づく duration 秒数。feed 観測前または旧 resume ID は undefined。 */
  getDuration(id: string): number | undefined;
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
  let submissions = 0;
  let observedGenerate = false;
  let observedFeed = false;
  let feedAt = 0;
  let changeAt = 0;

  function upsert(clip: ObservedClip): void {
    const prev = statusById.get(clip.id);
    if (prev !== clip.status) {
      statusById.set(clip.id, clip.status);
      changeAt = now();
    }
    if (clip.duration !== undefined && durationById.get(clip.id) !== clip.duration) {
      durationById.set(clip.id, clip.duration);
      changeAt = now();
    }
  }

  return {
    registerSubmitted(clips) {
      observedGenerate = true;
      submissions += 1;
      for (const clip of clips) {
        submittedById.set(clip.id, true);
        upsert(clip);
      }
    },
    applyFeedStatuses(clips) {
      observedFeed = true;
      feedAt = now();
      for (const clip of clips) {
        // 既知 clip は status 更新。未知 clip は未終端のみ passive 合流する
        // （終端済みの未知 clip は slot を占有しないため、集計を無駄に膨らませない）。
        if (statusById.has(clip.id) || !TERMINAL.has(clip.status)) {
          upsert(clip);
        }
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
    getDuration(id) {
      return durationById.get(id);
    },
    clearSubmittedIds() {
      submittedById.clear();
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
