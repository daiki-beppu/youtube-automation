// entry 単位の自動リトライ + スキップ継続の判定ロジック (#948)。
//
// 従来の runAll は 1 entry の失敗で run 全体を ERROR 停止していた。entry 失敗率がわずかでも
// 55 entries の連続実行はほぼ完走できない（2% でも完走率 ≈ 0.98^55 ≈ 33%）。本モジュールは
// 1 entry の実行を失敗分類つきで包み、
//   - 一時的な失敗 → 同一 entry を maxRetry 回まで再試行
//   - 再試行しても失敗 → "failed"（caller がスキップして次 entry へ進み、failedIndices に記録）
//   - 投入済み（Generate click 済みで受理失敗確定でない）→ "presumed-done"（再試行すると重複生成
//     になるため、生成済みとみなして次へ。従来の resolveInterruptIndex(i+1) と同じ判断）
//   - 致命的（FatalRunError: DOM 不在 / captcha 手動解決 timeout / queue stall）→ "fatal"
//     （caller が従来どおり run 全体を ERROR 停止する）
//   - 中断 → "aborted"（caller の STOPPED 経路へ）
// content.ts のクロージャ内に書くと unit test から到達できないため、依存を DI した純ロジックとして切り出す。

/** 1 entry の実行結果。caller (runAll) は outcome ごとに DONE / ENTRY_FAILED / ERROR / STOPPED を emit する。 */
export type EntryRunResult =
  | { outcome: "ok" }
  | { outcome: "aborted" }
  | { outcome: "presumed-done"; error: unknown }
  | { outcome: "failed"; error: unknown }
  | { outcome: "fatal"; error: unknown };

export interface RunEntryWithRetryOptions {
  /** entry を 1 回実行する（= queue 待ち + injectWithVerification の一連）。 */
  attempt: () => Promise<void>;
  /** 中断フラグ。retry 間の待機より優先する。 */
  isAborted: () => boolean;
  /** 直近 attempt のエラーが「投入済み（再実行すると重複生成）」を意味するか。 */
  wasSubmitted: (error: unknown) => boolean;
  /** run 全体を止めるべき致命的エラーか（= FatalRunError の instanceof 判定）。 */
  isFatal: (error: unknown) => boolean;
  /** 同一 entry を再試行する最大回数（preset.maxEntryRetry）。 */
  maxRetry: number;
  /** retry 間の待機 (ms)。jitter 込みで毎回 fresh 算出する。 */
  retryDelayMs: () => number;
  /** retry 予告時に progress 等へ通知する hook。attempt は 1-based。 */
  onRetry?: (attempt: number, max: number, error: unknown) => void;
  /** 中断可能な sleep（= shared/dom の abortableSleep）。 */
  sleep: (ms: number, isAborted: () => boolean) => Promise<void>;
  /** warn メッセージ用の entry 特定文字列。 */
  describeEntry: () => string;
}

export async function runEntryWithRetry(options: RunEntryWithRetryOptions): Promise<EntryRunResult> {
  for (let attempt = 0; ; attempt++) {
    try {
      await options.attempt();
      return { outcome: "ok" };
    } catch (error) {
      // 分類の優先順位: fatal > aborted > presumed-done > retry > failed。
      // fatal は retry しても必ず再発するため最優先で抜ける。
      if (options.isFatal(error)) {
        return { outcome: "fatal", error };
      }
      if (options.isAborted()) {
        return { outcome: "aborted" };
      }
      if (options.wasSubmitted(error)) {
        // Generate click 済み・受理失敗確定でない（典型: 生成完了待ち timeout）。clip は Suno 側で
        // 生成が進んでいる公算が高く、再実行すると重複生成になるため生成済み扱いで次へ進む。
        return { outcome: "presumed-done", error };
      }
      if (attempt < options.maxRetry) {
        const message = error instanceof Error ? error.message : String(error);
        console.warn(`${options.describeEntry()} が失敗、entry retry (${attempt + 1}/${options.maxRetry}): ${message}`);
        options.onRetry?.(attempt + 1, options.maxRetry, error);
        await options.sleep(options.retryDelayMs(), options.isAborted);
        if (options.isAborted()) {
          return { outcome: "aborted" };
        }
        continue;
      }
      return { outcome: "failed", error };
    }
  }
}
