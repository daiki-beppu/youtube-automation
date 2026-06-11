// inject 後の受理検証 + retry ロジック (#864 root cause 3)。
//
// content.ts の inject ループは Generate ボタン再 enabled だけを成功判定としていたため、
// Suno 側の silent drop に気付かず次 entry へ進み、drop された entry が永遠に再 inject されなかった。
// inject 前後で in-flight 増分を検証し、達しなければ同じ entry を retry、それでも増えなければ fail-loud で throw する。
//
// この retry ループを content.ts のクロージャ内インライン関数にすると unit test から到達できないため、
// 依存（inject / getInFlightClipCount / waitForInFlightIncrease / isAborted）を DI した純ロジックとして切り出す。

/**
 * 全 attempt で in-flight 増加が確認できなかった（= 投入が Suno に受理されていない）終端エラー (#924)。
 * runAll の ERROR catch で instanceof を判定し、silent drop 確定の場合は current entry を再生成する
 * よう interruptIndex を currentIndex に保つ（投入済み・受理済みの entry は skip して重複を防ぐ方針との対称）。
 */
export class InjectNotAcknowledgedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InjectNotAcknowledgedError";
  }
}

export interface InjectWithVerificationOptions {
  /** entry を 1 回 inject + Generate する（= () => injectAndGenerate(entry, i, total)）。 */
  inject: () => Promise<void>;
  /** 現在の in-flight clip 数を返す（inject 前の基準値 before の取得に使う）。 */
  getInFlightClipCount: () => number;
  /** in-flight が before + delta 以上へ増えるまで待機し、受理 true / timeout false を返す。 */
  waitForInFlightIncrease: (
    before: number,
    delta: number,
    opts: { isAborted: () => boolean; pollIntervalMs: number; timeoutMs: number },
  ) => Promise<boolean>;
  /** 中断フラグ。inject 直後に true なら受理確認も retry もせず静かに return する。 */
  isAborted: () => boolean;
  /** 受理を期待する clip 数（= waitForInFlightIncrease に渡す delta）。 */
  clipsPerRequest: number;
  /** silent drop 時に同じ entry を再投入する最大回数。 */
  maxRetry: number;
  /** waitForInFlightIncrease の timeoutMs に渡す inject ack 待ち上限。 */
  ackTimeoutMs: number;
  pollIntervalMs: number;
  /** throw / warn メッセージ用の entry 特定文字列（= `entry ${i} (${title ?? name})`）。 */
  describeEntry: () => string;
}

/**
 * entry を inject し、in-flight が clipsPerRequest 増えたことを検証する。
 *   - inject() → 中断なら即 return（throw しない）→ waitForInFlightIncrease で受理確認
 *   - 受理 (true) で return / 未受理 (false) で同じ entry を最大 maxRetry 回 retry
 *   - 全 attempt で未受理なら throw（fail-loud。describeEntry をメッセージに含め ERROR phase へ落とす）
 */
export async function injectWithVerification(options: InjectWithVerificationOptions): Promise<void> {
  for (let attempt = 0; attempt <= options.maxRetry; attempt++) {
    const before = options.getInFlightClipCount();
    await options.inject();
    if (options.isAborted()) {
      return;
    }
    const ok = await options.waitForInFlightIncrease(before, options.clipsPerRequest, {
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
        `${options.describeEntry()} inject が ${options.clipsPerRequest} clip acknowledge されず retry (${attempt + 1}/${options.maxRetry})`,
      );
    }
  }
  throw new InjectNotAcknowledgedError(
    `${options.describeEntry()} の inject が ${options.maxRetry + 1} 回 silent drop されました`,
  );
}
