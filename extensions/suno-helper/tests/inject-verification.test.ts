// inject 後の受理検証 + retry ロジック (#864 root cause 3 → #948 で ACK 契約刷新) の回帰テスト。
//
// content.ts の inject ループは、Generate ボタン再 enabled だけを成功判定としていたため
// Suno 側の silent drop に気付かず次 entry に進み、drop された entry が永遠に再 inject されなかった。
// 修正では inject 前に marker を採取し、inject 後に受理（ACK）を検証する。達しなければ同じ entry を
// retry、それでも受理されなければ fail-loud で throw する。本ロジックを content.ts のクロージャ内
// インライン関数のままにすると unit test から到達できず、テスト側で再実装するアンチパターンに陥る。
// そのため retry ループを純粋・DI 化した `lib/inject-retry.ts::injectWithVerification` として抽出し、
// 依存（inject / markBeforeInject / waitForAck / isAborted）を mock 注入して実関数を検証する。
//
// 契約 (suno-helper/lib/inject-retry.ts):
//   injectWithVerification<M>(options): Promise<void>
//   options: {
//     inject: () => Promise<void>;                 // = () => injectAndGenerate(entry, i, total)
//     markBeforeInject: () => M;                   // inject 前の ACK 基準 marker（中身は ack-probe 側の関心）
//     waitForAck: (marker: M, opts: {
//       isAborted: () => boolean; pollIntervalMs: number; timeoutMs: number;
//     }) => Promise<boolean>;
//     isAborted: () => boolean;
//     maxRetry: number;
//     ackTimeoutMs: number;      // waitForAck の timeoutMs に渡す
//     pollIntervalMs: number;
//     describeEntry: () => string; // throw メッセージ用 `entry ${i} (${title ?? name})`
//   }
// 振る舞い:
//   - markBeforeInject() → inject() → isAborted なら即 return（throw しない）→ waitForAck で受理確認
//   - ack(true) で return / drop(false) で同じ entry を最大 maxRetry 回 retry
//   - 全 attempt drop なら throw（fail-loud、describeEntry をメッセージに含む）
import { describe, expect, it, vi } from "vitest";

import {
  InjectNotAcknowledgedError,
  injectWithVerification,
  type InjectWithVerificationOptions,
} from "../lib/inject-retry";

/** 既定値を持つ options を作り、test ごとに必要な mock だけ override する。 */
function makeOptions(
  overrides: Partial<InjectWithVerificationOptions<number>> = {},
): InjectWithVerificationOptions<number> {
  return {
    inject: vi.fn().mockResolvedValue(undefined),
    markBeforeInject: vi.fn().mockReturnValue(0),
    waitForAck: vi.fn().mockResolvedValue(true),
    isAborted: () => false,
    maxRetry: 2,
    ackTimeoutMs: 30000,
    pollIntervalMs: 500,
    describeEntry: () => "entry 0 (pattern-1)",
    ...overrides,
  };
}

describe("injectWithVerification: inject 受理検証 + retry (#864/#948)", () => {
  it("Given 1 回目で ack される When 実行 Then inject 1 回・retry なし・throw なし", async () => {
    const inject = vi.fn().mockResolvedValue(undefined);
    const waitForAck = vi.fn().mockResolvedValue(true);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(injectWithVerification(makeOptions({ inject, waitForAck }))).resolves.toBeUndefined();

    expect(inject).toHaveBeenCalledTimes(1);
    expect(waitForAck).toHaveBeenCalledTimes(1);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("Given marker=4 / ackTimeoutMs=30000 When 受理確認 Then waitForAck に marker と timeoutMs を正しい位置で渡す", async () => {
    // 外部契約の入力位置チェック: marker=markBeforeInject() の返り値、
    // ackTimeoutMs は timeoutMs に（pollIntervalMs に取り違えない）入れて渡す。
    const markBeforeInject = vi.fn().mockReturnValue(4);
    const waitForAck = vi.fn().mockResolvedValue(true);

    await injectWithVerification(
      makeOptions({
        markBeforeInject,
        waitForAck,
        ackTimeoutMs: 30000,
        pollIntervalMs: 500,
      }),
    );

    expect(waitForAck).toHaveBeenCalledWith(4, {
      isAborted: expect.any(Function),
      pollIntervalMs: 500,
      timeoutMs: 30000,
    });
  });

  it("Given retry When 各 attempt Then markBeforeInject を attempt ごとに取り直す（前 attempt の marker を使い回さない）", async () => {
    // 1 回目の inject 自体が in-flight / submission を進めている可能性があるため、
    // retry では基準 marker を再採取しないと誤 NACK / 誤 ACK の両方が起きうる。
    const markBeforeInject = vi.fn().mockReturnValueOnce(0).mockReturnValueOnce(1);
    const waitForAck = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await injectWithVerification(makeOptions({ markBeforeInject, waitForAck }));

    expect(markBeforeInject).toHaveBeenCalledTimes(2);
    expect(waitForAck).toHaveBeenNthCalledWith(1, 0, expect.anything());
    expect(waitForAck).toHaveBeenNthCalledWith(2, 1, expect.anything());
    warn.mockRestore();
  });

  it("Given 1 回目 silent drop → 2 回目 ack When 実行 Then inject 2 回・warn 1 回・throw なし (復帰)", async () => {
    const inject = vi.fn().mockResolvedValue(undefined);
    const waitForAck = vi
      .fn()
      .mockResolvedValueOnce(false) // 1 回目: 受理されず
      .mockResolvedValueOnce(true); // 2 回目: 受理
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(injectWithVerification(makeOptions({ inject, waitForAck }))).resolves.toBeUndefined();

    expect(inject).toHaveBeenCalledTimes(2);
    expect(waitForAck).toHaveBeenCalledTimes(2);
    expect(warn).toHaveBeenCalledTimes(1); // drop した 1 回目のみ警告
    warn.mockRestore();
  });

  it("Given maxRetry=2 で全 attempt silent drop When 実行 Then inject 3 回・throw (fail-loud で ERROR phase へ)", async () => {
    const inject = vi.fn().mockResolvedValue(undefined);
    const waitForAck = vi.fn().mockResolvedValue(false); // 常に未受理
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(
      injectWithVerification(
        makeOptions({
          inject,
          waitForAck,
          maxRetry: 2,
          describeEntry: () => "entry 10 (queue-test-11)",
        }),
      ),
    ).rejects.toThrow(/queue-test-11/); // entry 特定情報を fail-loud メッセージに含む

    expect(inject).toHaveBeenCalledTimes(3); // 初回 + retry 2
    // retry 予告 warn は後続 attempt がある drop だけ（attempt 0,1）。終端 attempt 2 は
    // 予告せず throw が終端を伝えるため、論理破綻ログ `retry (3/2)` を出さない。
    expect(warn).toHaveBeenCalledTimes(2);
    const warnMessages = warn.mock.calls.map((call) => String(call[0]));
    expect(warnMessages).toEqual([expect.stringContaining("retry (1/2)"), expect.stringContaining("retry (2/2)")]);
    expect(warnMessages.some((message) => message.includes("retry (3/2)"))).toBe(false);
    warn.mockRestore();
  });

  it("Given inject 直後に中断 (isAborted=true) When 実行 Then waitForAck を呼ばず throw なしで return", async () => {
    // 停止押下は受理確認より優先。inject 後に aborted を見たら retry も検証もせず静かに抜ける。
    let aborted = false;
    const inject = vi.fn().mockImplementation(async () => {
      aborted = true;
    });
    const waitForAck = vi.fn().mockResolvedValue(false);

    await expect(
      injectWithVerification(makeOptions({ inject, waitForAck, isAborted: () => aborted })),
    ).resolves.toBeUndefined();

    expect(inject).toHaveBeenCalledTimes(1);
    expect(waitForAck).not.toHaveBeenCalled(); // 中断後は受理確認に進まない
  });
});

describe("InjectNotAcknowledgedError: 全 attempt 未受理の終端エラー (#924)", () => {
  it("Given 全 attempt drop When 終端 throw Then InjectNotAcknowledgedError の instanceof である", async () => {
    const waitForAck = vi.fn().mockResolvedValue(false);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    let caughtError: unknown;
    try {
      await injectWithVerification(makeOptions({ waitForAck, maxRetry: 1 }));
    } catch (err) {
      caughtError = err;
    }
    warn.mockRestore();

    expect(caughtError).toBeInstanceOf(InjectNotAcknowledgedError);
  });

  it("Given InjectNotAcknowledgedError When name を確認 Then 'InjectNotAcknowledgedError' である", () => {
    const err = new InjectNotAcknowledgedError("テスト");
    expect(err.name).toBe("InjectNotAcknowledgedError");
  });

  it("Given InjectNotAcknowledgedError When message を確認 Then 渡したメッセージがそのまま保持される（メッセージ不変）", async () => {
    const waitForAck = vi.fn().mockResolvedValue(false);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const describeEntry = () => "entry 3 (silent-drop-test)";

    let caughtError: unknown;
    try {
      await injectWithVerification(makeOptions({ waitForAck, maxRetry: 0, describeEntry }));
    } catch (err) {
      caughtError = err;
    }
    warn.mockRestore();

    expect(caughtError).toBeInstanceOf(InjectNotAcknowledgedError);
    expect((caughtError as InjectNotAcknowledgedError).message).toBe(
      "entry 3 (silent-drop-test) の inject が 1 回 silent drop されました",
    );
  });
});
