// inject 後の受理検証 + retry ロジック (#864 root cause 3) の回帰テスト。
//
// content.ts の inject ループは、Generate ボタン再 enabled だけを成功判定としていたため
// Suno 側の silent drop に気付かず次 entry に進み、drop された entry が永遠に再 inject されなかった。
// 修正では inject 前後で in-flight 増分を検証し、達しなければ同じ entry を retry、それでも増えなければ
// fail-loud で throw する。本ロジックを content.ts のクロージャ内インライン関数のままにすると
// unit test から到達できず、テスト側で再実装する（= 実呼び出しチェーンを通らない）アンチパターンに陥る。
// そのため retry ループを純粋・DI 化した `lib/inject-retry.ts::injectWithVerification` として抽出し、
// 依存（inject / getInFlightClipCount / waitForInFlightIncrease / isAborted）を mock 注入して
// 実関数を呼び出しチェーンごと検証する。
//
// 契約 (draft が実装すべき public API、suno-helper/lib/inject-retry.ts):
//   injectWithVerification(options): Promise<void>
//   options: {
//     inject: () => Promise<void>;                 // = () => injectAndGenerate(entry, i, total)
//     getInFlightClipCount: () => number;
//     waitForInFlightIncrease: (before: number, delta: number, opts: {
//       isAborted: () => boolean; pollIntervalMs: number; timeoutMs: number;
//     }) => Promise<boolean>;
//     isAborted: () => boolean;
//     clipsPerRequest: number;   // delta（受理を期待する clip 数）
//     maxRetry: number;
//     ackTimeoutMs: number;      // waitForInFlightIncrease の timeoutMs に渡す
//     pollIntervalMs: number;
//     describeEntry: () => string; // throw メッセージ用 `entry ${i} (${title ?? name})`
//   }
// 振る舞い:
//   - inject() → isAborted なら即 return（throw しない）→ waitForInFlightIncrease で受理確認
//   - ack(true) で return / drop(false) で同じ entry を最大 maxRetry 回 retry
//   - 全 attempt drop なら throw（fail-loud、describeEntry をメッセージに含む）
import { describe, expect, it, vi } from "vitest";

import { injectWithVerification, type InjectWithVerificationOptions } from "../lib/inject-retry";

/** 既定値を持つ options を作り、test ごとに必要な mock だけ override する。 */
function makeOptions(overrides: Partial<InjectWithVerificationOptions> = {}): InjectWithVerificationOptions {
  return {
    inject: vi.fn().mockResolvedValue(undefined),
    getInFlightClipCount: vi.fn().mockReturnValue(0),
    waitForInFlightIncrease: vi.fn().mockResolvedValue(true),
    isAborted: () => false,
    clipsPerRequest: 2,
    maxRetry: 2,
    ackTimeoutMs: 30000,
    pollIntervalMs: 500,
    describeEntry: () => "entry 0 (pattern-1)",
    ...overrides,
  };
}

describe("injectWithVerification: inject 受理検証 + retry (#864)", () => {
  it("Given 1 回目で ack される When 実行 Then inject 1 回・retry なし・throw なし", async () => {
    const inject = vi.fn().mockResolvedValue(undefined);
    const waitForInFlightIncrease = vi.fn().mockResolvedValue(true);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(
      injectWithVerification(makeOptions({ inject, waitForInFlightIncrease })),
    ).resolves.toBeUndefined();

    expect(inject).toHaveBeenCalledTimes(1);
    expect(waitForInFlightIncrease).toHaveBeenCalledTimes(1);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("Given before=4 / clipsPerRequest=2 / ackTimeoutMs=30000 When 受理確認 Then waitForInFlightIncrease に正しい位置で渡す", async () => {
    // 外部契約の入力位置チェック: before=getInFlightClipCount(), delta=clipsPerRequest,
    // ackTimeoutMs は timeoutMs に（pollIntervalMs に取り違えない）入れて渡す。
    const getInFlightClipCount = vi.fn().mockReturnValue(4);
    const waitForInFlightIncrease = vi.fn().mockResolvedValue(true);

    await injectWithVerification(
      makeOptions({
        getInFlightClipCount,
        waitForInFlightIncrease,
        clipsPerRequest: 2,
        ackTimeoutMs: 30000,
        pollIntervalMs: 500,
      }),
    );

    expect(waitForInFlightIncrease).toHaveBeenCalledWith(4, 2, {
      isAborted: expect.any(Function),
      pollIntervalMs: 500,
      timeoutMs: 30000,
    });
  });

  it("Given 1 回目 silent drop → 2 回目 ack When 実行 Then inject 2 回・warn 1 回・throw なし (復帰)", async () => {
    const inject = vi.fn().mockResolvedValue(undefined);
    const waitForInFlightIncrease = vi
      .fn()
      .mockResolvedValueOnce(false) // 1 回目: 受理されず
      .mockResolvedValueOnce(true); // 2 回目: 受理
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(
      injectWithVerification(makeOptions({ inject, waitForInFlightIncrease })),
    ).resolves.toBeUndefined();

    expect(inject).toHaveBeenCalledTimes(2);
    expect(waitForInFlightIncrease).toHaveBeenCalledTimes(2);
    expect(warn).toHaveBeenCalledTimes(1); // drop した 1 回目のみ警告
    warn.mockRestore();
  });

  it("Given maxRetry=2 で全 attempt silent drop When 実行 Then inject 3 回・throw (fail-loud で ERROR phase へ)", async () => {
    const inject = vi.fn().mockResolvedValue(undefined);
    const waitForInFlightIncrease = vi.fn().mockResolvedValue(false); // 常に未受理
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(
      injectWithVerification(
        makeOptions({
          inject,
          waitForInFlightIncrease,
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
    expect(warnMessages).toEqual([
      expect.stringContaining("retry (1/2)"),
      expect.stringContaining("retry (2/2)"),
    ]);
    expect(warnMessages.some((message) => message.includes("retry (3/2)"))).toBe(false);
    warn.mockRestore();
  });

  it("Given inject 直後に中断 (isAborted=true) When 実行 Then waitForInFlightIncrease を呼ばず throw なしで return", async () => {
    // 停止押下は受理確認より優先。inject 後に aborted を見たら retry も検証もせず静かに抜ける。
    let aborted = false;
    const inject = vi.fn().mockImplementation(async () => {
      aborted = true;
    });
    const waitForInFlightIncrease = vi.fn().mockResolvedValue(false);

    await expect(
      injectWithVerification(
        makeOptions({ inject, waitForInFlightIncrease, isAborted: () => aborted }),
      ),
    ).resolves.toBeUndefined();

    expect(inject).toHaveBeenCalledTimes(1);
    expect(waitForInFlightIncrease).not.toHaveBeenCalled(); // 中断後は受理確認に進まない
  });
});
