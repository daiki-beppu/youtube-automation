// inject 後の受理検証 + retry ロジック (#864 root cause 3 → #948 で ACK 契約を刷新)。
//
// content.ts の inject ループは Generate ボタン再 enabled だけを成功判定としていたため、
// Suno 側の silent drop に気付かず次 entry へ進み、drop された entry が永遠に再 inject されなかった。
// inject 前に marker を採取し、inject 後に受理（ACK）を検証する。達しなければ同じ entry を retry、
// それでも受理されなければ fail-loud で throw する。
//
// #948: ACK のシグナルは呼び出し側が markBeforeInject / waitForAck として注入する
// （実装は lib/ack-probe.ts のハイブリッド判定 = bridge の generate レスポンス観測 OR DOM 増分）。
// 本モジュールは marker の中身に関知しないジェネリックな retry 骨格に徹する。
//
// この retry ループを content.ts のクロージャ内インライン関数にすると unit test から到達できないため、
// 依存（inject / markBeforeInject / waitForAck / isAborted）を DI した純ロジックとして切り出す。

/**
 * 全 attempt で受理が確認できなかった（= 投入が Suno に受理されていない）終端エラー (#924)。
 * runAll の ERROR catch で instanceof を判定し、silent drop 確定の場合は current entry を再生成する
 * よう interruptIndex を currentIndex に保つ（投入済み・受理済みの entry は skip して重複を防ぐ方針との対称）。
 */
export class InjectNotAcknowledgedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InjectNotAcknowledgedError";
  }
}

export interface InjectWithVerificationOptions<M> {
  /** entry を 1 回 inject + Generate する（= () => injectAndGenerate(entry, i, total)）。 */
  inject: () => Promise<void>;
  /** inject 前に呼び、ACK 判定の基準 marker を返す（= ack-probe の markAck）。 */
  markBeforeInject: () => M;
  /** marker 基準で受理を確認する。受理 true / timeout false を返す（= ack-probe の waiter）。 */
  waitForAck: (
    marker: M,
    opts: {
      isAborted: () => boolean;
      pollIntervalMs: number;
      timeoutMs: number;
    }
  ) => Promise<boolean>;
  /** 中断フラグ。inject 直後に true なら受理確認も retry もせず静かに return する。 */
  isAborted: () => boolean;
  /** silent drop 時に同じ entry を再投入する最大回数。 */
  maxRetry: number;
  /** waitForAck の timeoutMs に渡す inject ack 待ち上限。 */
  ackTimeoutMs: number;
  pollIntervalMs: number;
  /** throw / warn メッセージ用の entry 特定文字列（= `entry ${i} (${title ?? name})`）。 */
  describeEntry: () => string;
}

export interface RetryInjectStepWithFallbackOptions {
  /** retry 対象の inject step。例: Lyrics paste 注入。 */
  run: () => Promise<void>;
  /** 全 retry が失敗した後に 1 回だけ試す fallback。例: beforeinput 注入。 */
  fallback: (lastError: unknown) => Promise<void>;
  /** retry 対象エラーかを判定する。対象外エラーは即 throw する。 */
  isRetryable: (error: unknown) => boolean;
  /** run を再試行する最大回数。総 attempt 数は maxRetry + 1。 */
  maxRetry: number;
  /** warn メッセージ用の step 特定文字列。 */
  describeStep: () => string;
}

export async function retryInjectStepWithFallback(
  options: RetryInjectStepWithFallbackOptions
): Promise<void> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= options.maxRetry; attempt++) {
    try {
      await options.run();
      return;
    } catch (error) {
      if (!options.isRetryable(error)) {
        throw error;
      }
      lastError = error;
      const message = error instanceof Error ? error.message : String(error);
      if (attempt < options.maxRetry) {
        console.warn(
          `${options.describeStep()} が失敗、inject retry (${attempt + 1}/${options.maxRetry}): ${message}`
        );
        continue;
      }
      console.warn(
        `${options.describeStep()} が ${options.maxRetry + 1} 回失敗したため ` +
          `beforeinput fallback を試します: ${message}`
      );
    }
  }
  await options.fallback(lastError);
}

/**
 * entry を inject し、受理（ACK）されたことを検証する。
 *   - markBeforeInject() → inject() → 中断なら即 return（throw しない）→ waitForAck で受理確認
 *   - 受理 (true) で return / 未受理 (false) で同じ entry を最大 maxRetry 回 retry
 *   - 全 attempt で未受理なら throw（fail-loud。describeEntry をメッセージに含め ERROR phase へ落とす）
 */
export async function injectWithVerification<M>(
  options: InjectWithVerificationOptions<M>
): Promise<void> {
  for (let attempt = 0; attempt <= options.maxRetry; attempt++) {
    const marker = options.markBeforeInject();
    await options.inject();
    if (options.isAborted()) {
      return;
    }
    const ok = await options.waitForAck(marker, {
      isAborted: options.isAborted,
      pollIntervalMs: options.pollIntervalMs,
      timeoutMs: options.ackTimeoutMs,
    });
    if (ok) {
      return;
    }
    // retry を予告するのは後続 attempt が残っているときだけ。終端 attempt の未受理は
    // 直後の throw が終端を伝えるため、`retry (3/2)` のような論理破綻ログを出さない。
    if (attempt < options.maxRetry) {
      console.warn(
        `${options.describeEntry()} inject が acknowledge されず retry (${attempt + 1}/${options.maxRetry})`
      );
    }
  }
  throw new InjectNotAcknowledgedError(
    `${options.describeEntry()} の inject が ${options.maxRetry + 1} 回 silent drop されました`
  );
}
