// inject 受理（ACK）のハイブリッド判定 (#948)。
//
// 旧 ACK は「DOM の in-flight が CLIPS_PER_REQUEST 増えるまで待つ」のみで、
//   - 増分検知に最大 30-45 秒かかる（clip card の DOM 反映ラグ待ち）
//   - Remix disabled プロキシの誤カウントで before が膨らみ誤 NACK しうる
// という問題があった。bridge が generate レスポンスを観測できる環境では
// 「レスポンスが返った = Suno が受理した」を一次シグナルにでき、ACK は数百 ms で確定する。
//
// ただし最初の entry の時点では bridge が機能しているか判定できない（観測実績ゼロ）ため、
// marker 取得時に両シグナルの基準値を取り、どちらかが達した時点で受理とみなす OR 判定にする。
// bridge が死んでいても DOM 増分で従来通り判定でき、安全側に倒れる。
import { CLIPS_PER_REQUEST } from "../../shared/constants";

/** ACK 判定の基準 marker。inject 前のスナップショット。 */
export interface AckMarker {
  /** tracker.submissionCount() の inject 前の値。これを超えたら bridge 経由で受理確定。 */
  submissionMarker: number;
  /** DOM の in-flight 数の inject 前の値。取得不能（Remix btn 0 件等）なら null で DOM 判定を捨てる。 */
  domBefore: number | null;
}

export interface AckWaiterDeps {
  /** generate レスポンスの累計観測回数（= tracker.submissionCount）。 */
  getSubmissionCount: () => number;
  /** DOM プロキシの in-flight 数（= shared/dom の getInFlightClipCount）。throw しうる。 */
  getDomInFlightCount: () => number;
  /** 1 リクエストで増える clip 数（= CLIPS_PER_REQUEST）。 */
  clipsPerRequest?: number;
  sleep: (ms: number) => Promise<void>;
  now?: () => number;
}

export interface AckWaitOptions {
  isAborted: () => boolean;
  pollIntervalMs: number;
  timeoutMs: number;
}

/** inject 前に呼び、両シグナルの基準値を採取する。 */
export function markAck(deps: AckWaiterDeps): AckMarker {
  let domBefore: number | null = null;
  try {
    domBefore = deps.getDomInFlightCount();
  } catch {
    // DOM 構造が解決できない（Remix btn 0 件等）。bridge シグナルだけで判定する。
  }
  return { submissionMarker: deps.getSubmissionCount(), domBefore };
}

/**
 * marker 基準で受理を待つ。受理 true / timeout false / 中断は true（停止優先、retry させない）。
 *   - bridge: submissionCount が marker を超えたら受理（generate レスポンス観測 = Suno が受理）
 *   - DOM:    in-flight が domBefore + clipsPerRequest 以上に増えたら受理（従来互換 fallback）
 */
export function createAckWaiter(
  deps: AckWaiterDeps
): (marker: AckMarker, options: AckWaitOptions) => Promise<boolean> {
  const clipsPerRequest = deps.clipsPerRequest ?? CLIPS_PER_REQUEST;
  const now = deps.now ?? Date.now;
  return async (marker, options) => {
    const deadline = now() + options.timeoutMs;
    while (now() < deadline) {
      if (options.isAborted()) {
        return true;
      }
      if (deps.getSubmissionCount() > marker.submissionMarker) {
        return true;
      }
      if (marker.domBefore !== null) {
        try {
          if (
            deps.getDomInFlightCount() >=
            marker.domBefore + clipsPerRequest
          ) {
            return true;
          }
        } catch {
          // 待機中に DOM が崩れたら以降は bridge シグナルのみで判定する。
          marker = { ...marker, domBefore: null };
        }
      }
      await deps.sleep(options.pollIntervalMs);
    }
    return false;
  };
}
