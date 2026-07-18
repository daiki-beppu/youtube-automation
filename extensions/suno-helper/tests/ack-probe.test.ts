// ハイブリッド ACK 判定 (#948) の回帰テスト。
//
// 旧 waitForInFlightIncrease（DOM 増分のみ・queue.test.ts に在籍）の契約を引き継ぎつつ、
// bridge の generate レスポンス観測（submissionCount 増分）を一次シグナルに加えた OR 判定。
//   - bridge: submissionCount > marker.submissionMarker で受理（数百 ms で確定する速い経路）
//   - DOM:    in-flight >= domBefore + clipsPerRequest で受理（bridge 不調時の従来互換）
//   - 中断は受理判定より優先で true（retry させない）
//   - timeout で false（throw しない。retry 判断は caller=injectWithVerification 側）
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAckWaiter, markAck, type AckWaiterDeps } from "../lib/ack-probe";

const FAST = { pollIntervalMs: 10, timeoutMs: 1000 } as const;

function makeDeps(overrides: Partial<AckWaiterDeps> = {}): AckWaiterDeps {
  return {
    getSubmissionCount: () => 0,
    getDomInFlightCount: () => 0,
    clipsPerRequest: 2,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("markAck: inject 前の基準 marker 採取", () => {
  it("Given 両シグナル取得可 When 採取する Then submission / DOM の両基準値を持つ", () => {
    const marker = markAck(
      makeDeps({ getSubmissionCount: () => 3, getDomInFlightCount: () => 5 })
    );
    expect(marker).toEqual({ submissionMarker: 3, domBefore: 5 });
  });

  it("Given DOM カウントが throw（Remix btn 0 件等） When 採取する Then domBefore=null で bridge のみ判定", () => {
    const marker = markAck(
      makeDeps({
        getSubmissionCount: () => 3,
        getDomInFlightCount: () => {
          throw new Error("Remix btn が 1 件も見つかりません。");
        },
      })
    );
    expect(marker).toEqual({ submissionMarker: 3, domBefore: null });
  });
});

describe("createAckWaiter: bridge シグナル経路", () => {
  it("Given submissionCount が marker を超えている When 待機する Then 即 resolve true（速い経路）", async () => {
    const wait = createAckWaiter(makeDeps({ getSubmissionCount: () => 4 }));
    const pending = wait(
      { submissionMarker: 3, domBefore: 0 },
      { isAborted: () => false, ...FAST }
    );
    await vi.advanceTimersByTimeAsync(0);
    await expect(pending).resolves.toBe(true);
  });

  it("Given poll 中に generate レスポンスを観測 When submissionCount が増える Then resolve true", async () => {
    let submissions = 1;
    const wait = createAckWaiter(
      makeDeps({ getSubmissionCount: () => submissions })
    );
    const pending = wait(
      { submissionMarker: 1, domBefore: 0 },
      { isAborted: () => false, ...FAST }
    );
    let settled: boolean | undefined;
    void pending.then((v) => {
      settled = v;
    });

    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs * 3);
    expect(settled).toBeUndefined(); // marker と同値のうちは未受理

    submissions = 2;
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);
    await expect(pending).resolves.toBe(true);
  });
});

describe("createAckWaiter: DOM 増分経路（bridge 不調時の従来互換）", () => {
  it("Given submission は動かず DOM が before+delta まで増える When 待機する Then resolve true", async () => {
    let inflight = 4;
    const wait = createAckWaiter(
      makeDeps({ getDomInFlightCount: () => inflight })
    );
    const pending = wait(
      { submissionMarker: 0, domBefore: 4 },
      { isAborted: () => false, ...FAST }
    );
    let settled: boolean | undefined;
    void pending.then((v) => {
      settled = v;
    });

    inflight = 5; // 5 < 4 + 2 = 6
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);
    expect(settled).toBeUndefined(); // 部分受理では通さない（絶対値 before+delta 比較）

    inflight = 6; // 6 >= 6
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);
    await expect(pending).resolves.toBe(true);
  });

  it("Given domBefore=null（採取時に DOM 不能） When DOM だけが増えても Then 受理にしない（bridge のみ判定）", async () => {
    const wait = createAckWaiter(makeDeps({ getDomInFlightCount: () => 100 }));
    const pending = wait(
      { submissionMarker: 0, domBefore: null },
      { isAborted: () => false, ...FAST }
    );
    await vi.advanceTimersByTimeAsync(
      FAST.timeoutMs + FAST.pollIntervalMs + 50
    );
    await expect(pending).resolves.toBe(false);
  });

  it("Given 待機中に DOM カウントが throw し始める When poll する Then 以降は bridge のみで判定し throw を漏らさない", async () => {
    let domBroken = false;
    let submissions = 0;
    const wait = createAckWaiter(
      makeDeps({
        getSubmissionCount: () => submissions,
        getDomInFlightCount: () => {
          if (domBroken) throw new Error("DOM 崩れ");
          return 0;
        },
      })
    );
    const pending = wait(
      { submissionMarker: 0, domBefore: 0 },
      { isAborted: () => false, ...FAST }
    );
    let settled: boolean | undefined;
    void pending.then((v) => {
      settled = v;
    });

    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs * 2);
    domBroken = true;
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs * 2);
    expect(settled).toBeUndefined(); // throw を漏らさず待機を継続

    submissions = 1; // bridge 経路で受理
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);
    await expect(pending).resolves.toBe(true);
  });
});

describe("createAckWaiter: 中断と timeout", () => {
  it("Given isAborted=true When 未受理でも待機する Then 即 resolve true（停止優先、retry させない）", async () => {
    const wait = createAckWaiter(makeDeps());
    const pending = wait(
      { submissionMarker: 0, domBefore: 0 },
      { isAborted: () => true, ...FAST }
    );
    await vi.advanceTimersByTimeAsync(0);
    await expect(pending).resolves.toBe(true);
  });

  it("Given どちらのシグナルも達しない When deadline 超過 Then resolve false（throw しない）", async () => {
    const wait = createAckWaiter(makeDeps());
    const pending = wait(
      { submissionMarker: 0, domBefore: 0 },
      { isAborted: () => false, ...FAST }
    );
    await vi.advanceTimersByTimeAsync(
      FAST.timeoutMs + FAST.pollIntervalMs + 50
    );
    await expect(pending).resolves.toBe(false);
  });
});
