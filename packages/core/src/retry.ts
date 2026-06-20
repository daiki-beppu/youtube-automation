// 共通リトライ seam（#959）。adapter ごとの retry ループ再発明を防ぐ単一実装。
//
// 旧 `image/base.ts` の `RETRY_MAX` / `RETRY_BACKOFF` / `backoffMs` / `SleepMs` を
// ここへ昇格した。リトライの所有者は service 層（例: `image/service.ts`）であり、
// provider / adapter は 1-attempt 契約（成功は値を return、失敗は throw）に縮退する。
// quota（`QuotaExhaustedError`）は ADR-0003 に従い retry せず Result で caller へ
// 返す（`domain: "quota"` + `retryAfterSeconds`）。

import { defaultShouldRetry } from "./errors.ts";

export { defaultShouldRetry };

/** リトライ間バックオフのスリープ注入点（ミリ秒）。 */
export type SleepMs = (ms: number) => Promise<void>;

// 既定のリトライ予算（Python `utils/image_provider/base.py` 由来の 3 回 / 10-30-60 秒）。
const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_BACKOFF_SECONDS = [10, 30, 60] as const;

// 実時間で待機する default sleep（テストは fake を注入する）。
const realSleep: SleepMs = (ms) => Bun.sleep(ms);

/** `withRetry` の挙動を制御するポリシー。全フィールド省略可（既定値あり）。 */
export interface RetryPolicy {
  /** attempt 間の待機秒数列。attempts が多い場合は末尾値を再利用する。既定 [10, 30, 60] */
  readonly backoffSeconds?: readonly number[];
  /** 最大試行回数。既定 3 */
  readonly maxAttempts?: number;
  /** エラーを retry すべきかの判定。既定 {@link defaultShouldRetry} */
  readonly shouldRetry?: (error: unknown) => boolean;
  /** バックオフ待機の注入点。既定は Bun.sleep ベースの実時間待機 */
  readonly sleep?: SleepMs;
}

/**
 * `attempt` を最大 `maxAttempts` 回まで実行する共通リトライ実装。
 *
 * 成功したら即 return。エラー時は `shouldRetry` が false なら即 rethrow、true なら
 * `backoffSeconds[attemptIndex]`（範囲外は末尾値）秒を待機して再試行する。
 * 回数を使い切ったら最後のエラーをそのまま rethrow する（握りつぶさない）。
 */
export const withRetry = async <T>(
  attempt: (attemptIndex: number) => Promise<T>,
  policy?: RetryPolicy
): Promise<T> => {
  const maxAttempts = policy?.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  const backoffSeconds = policy?.backoffSeconds ?? DEFAULT_BACKOFF_SECONDS;
  const shouldRetry = policy?.shouldRetry ?? defaultShouldRetry;
  const sleep = policy?.sleep ?? realSleep;

  for (let attemptIndex = 0; attemptIndex < maxAttempts; attemptIndex += 1) {
    try {
      return await attempt(attemptIndex);
    } catch (error) {
      // non-retryable は即 rethrow、回数尽きは最後のエラーをそのまま rethrow する。
      if (!shouldRetry(error) || attemptIndex >= maxAttempts - 1) {
        throw error;
      }
      // 範囲外の attempt は末尾のバックオフ値を再利用する（空配列は待機なし）。
      const seconds =
        backoffSeconds[Math.min(attemptIndex, backoffSeconds.length - 1)] ?? 0;
      await sleep(seconds * 1000);
    }
  }
  // maxAttempts < 1 でループが一度も回らなかった場合のみ到達する不変条件違反。
  throw new Error(
    `validation: withRetry の maxAttempts=${maxAttempts} は 1 以上が必要です`
  );
};
