// @vitest-environment jsdom
//
// Suno 生成キュー監視 (#816) の回帰テスト。実 DOM 検証 (order.md) で確定した仕様を担保する:
//   - clip-row は `[data-testid="clip-row"]` で識別 (1 タブで 16 件確認)
//   - 生成中判定 = row 内に `svg.animate-spin` を含む。strict isVisible() で row 自体も filter
//   - 完了判定 = duration テキストあり / spinner なし → 生成中ではない
//   - getInFlightClipCount() = 全 visible clip-row のうち生成中の数
//   - waitForQueueSlot(maxClips, opts) = in-flight < maxClips になるまで poll
//
// 契約 (draft が実装すべき public API、shared/dom.ts):
//   - CLIP_ROW_SELECTOR: string
//   - isClipGenerating(row: HTMLElement): boolean
//   - getInFlightClipCount(): number
//   - waitForQueueSlot(maxClips: number, options: { isAborted; pollIntervalMs; timeoutMs; queueErrorWaitMs }): Promise<void>
//     #847 で queueErrorWaitMs（toast 消失後の安全マージン）を必須オプションに追加。
//
// jsdom はレイアウトを行わず getBoundingClientRect が常に 0×0 を返すため、strict 可視判定
// 対象の row には markBbox (_helpers.ts) で bbox を擬似的に与える (dom.test.ts と同方針)。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CLIP_ROW_SELECTOR,
  getInFlightClipCount,
  isClipGenerating,
  waitForInFlightIncrease,
  waitForQueueSlot,
} from "../../shared/dom";
import { addQueueErrorDialog, markBbox } from "./_helpers";

/**
 * clip-row を body に挿入する。
 *   - generating=true: row 内に `svg.animate-spin` を置く (生成中)
 *   - generating=false: duration テキストのみ (完了)
 *   - visible=false: display:none + bbox 0×0 (strict isVisible で除外される行)
 */
function addClipRow(opts: { generating?: boolean; visible?: boolean } = {}): HTMLElement {
  const row = document.createElement("div");
  row.setAttribute("data-testid", "clip-row");
  if (opts.generating) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "animate-spin");
    row.appendChild(svg);
  } else {
    const duration = document.createElement("span");
    duration.textContent = "2:02";
    row.appendChild(duration);
  }
  document.body.appendChild(row);
  if (opts.visible === false) {
    row.style.display = "none";
    markBbox(row, 0, 0);
  } else {
    markBbox(row, 200, 60);
  }
  return row;
}

/** generating な row から spinner を取り除き「完了」状態にする (poll 中に slot が空く状況を作る)。 */
function completeClip(row: HTMLElement): void {
  row.querySelector("svg.animate-spin")?.remove();
}

// queueErrorWaitMs は poll (10ms) と明確に分離して buffer 待機の途中経過を pin できるよう 200ms。
const FAST_OPTIONS = { pollIntervalMs: 10, timeoutMs: 1000, queueErrorWaitMs: 200 } as const;

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("CLIP_ROW_SELECTOR: 実 DOM 検証で確定した安定識別子", () => {
  it('Given 定数 When 読む Then `[data-testid="clip-row"]` である', () => {
    expect(CLIP_ROW_SELECTOR).toBe('[data-testid="clip-row"]');
  });
});

describe("isClipGenerating: 1 行の生成中判定", () => {
  it("Given 可視 row 内に svg.animate-spin When 判定する Then true", () => {
    const row = addClipRow({ generating: true });
    expect(isClipGenerating(row)).toBe(true);
  });

  it("Given 可視 row だが spinner 無し (duration のみ) When 判定する Then false (完了)", () => {
    const row = addClipRow({ generating: false });
    expect(isClipGenerating(row)).toBe(false);
  });

  it("Given spinner はあるが row が非可視 (display:none/bbox0) When 判定する Then false (strict isVisible で除外)", () => {
    const row = addClipRow({ generating: true, visible: false });
    expect(isClipGenerating(row)).toBe(false);
  });

  it("Given 親が display:none の row When 判定する Then false (親 walk で除外)", () => {
    const wrapper = document.createElement("div");
    wrapper.style.display = "none";
    document.body.appendChild(wrapper);
    const row = document.createElement("div");
    row.setAttribute("data-testid", "clip-row");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "animate-spin");
    row.appendChild(svg);
    wrapper.appendChild(row);
    markBbox(row, 200, 60); // bbox は非 0。除外理由は親の display:none のみに限定する。

    expect(isClipGenerating(row)).toBe(false);
  });
});

describe("getInFlightClipCount: 可視 clip-row のうち生成中の数", () => {
  it("Given 生成中 3 / 完了 1 / 非可視生成中 1 When 数える Then 可視生成中の 3 を返す", () => {
    addClipRow({ generating: true });
    addClipRow({ generating: true });
    addClipRow({ generating: true });
    addClipRow({ generating: false });
    addClipRow({ generating: true, visible: false });

    expect(getInFlightClipCount()).toBe(3);
  });

  it("Given clip-row が 1 件も無い When 数える Then 0 を返す", () => {
    expect(getInFlightClipCount()).toBe(0);
  });

  it("Given 全て完了 row When 数える Then 0 を返す", () => {
    addClipRow({ generating: false });
    addClipRow({ generating: false });

    expect(getInFlightClipCount()).toBe(0);
  });
});

describe("waitForQueueSlot: in-flight < maxClips まで待機", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given in-flight が既に上限未満 When 待機する Then 即 resolve する", async () => {
    addClipRow({ generating: true }); // in-flight 1 < 20
    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given in-flight が上限ちょうど When 1 clip 完了で空く Then 投入を再開 (resolve) する", async () => {
    // 20 clip 生成中 = 10 リクエスト in-flight = 上限。11 件目はここで待たされる。
    const rows = Array.from({ length: 20 }, () => addClipRow({ generating: true }));
    expect(getInFlightClipCount()).toBe(20);

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });

    // 上限のままでは resolve しない（poll しても 20 >= 20）。
    let settled = false;
    void pending.then(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 3);
    expect(settled).toBe(false);

    // 1 clip 完了 → in-flight 19 < 20 → 次の poll で resolve。
    completeClip(rows[0]);
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs);

    await expect(pending).resolves.toBeUndefined();
    expect(getInFlightClipCount()).toBe(19);
  });

  it("Given isAborted が true When 待機する Then 上限超でも即 resolve する (throw しない)", async () => {
    Array.from({ length: 20 }, () => addClipRow({ generating: true }));

    const pending = waitForQueueSlot(20, { isAborted: () => true, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given 上限のまま空かない When deadline 超過 Then timeout throw する", async () => {
    Array.from({ length: 20 }, () => addClipRow({ generating: true }));

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    const expectation = expect(pending).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.timeoutMs + FAST_OPTIONS.pollIntervalMs + 50);
    await expectation;
  });
});

describe("waitForQueueSlot: queue 上限エラー toast 検知 (#847)", () => {
  // race condition (Create→clip-row DOM 反映ラグ) で Suno が 21 件目を reject すると
  // 「Generation in progress」toast が出る。slot が空いていても toast 中は投入を止め、
  // toast 消失後に queueErrorWaitMs の安全マージンを待ってから再開する。
  // toast が一度も出ない経路（既存 4 ケース）は挙動不変であること（回帰）も上記で担保済み。
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given toast 可視中 When 空きスロットがあっても Then resolve せず待機を継続する", async () => {
    addClipRow({ generating: true }); // in-flight 1 < 20（スロットは空いている）
    const toast = addQueueErrorDialog(); // だが queue 上限 toast が出ている

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 5);
    expect(settled).toBe(false); // toast 中はスロットが空いていても投入しない

    // 後始末: toast を消し buffer を経過させて未解決 promise を残さない。
    toast.remove();
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.queueErrorWaitMs + FAST_OPTIONS.pollIntervalMs * 2);
    await expect(pending).resolves.toBeUndefined();
  });

  it("Given toast 消失 When queueErrorWaitMs buffer 経過 Then 投入を再開 (resolve) する", async () => {
    addClipRow({ generating: true }); // slot は空き
    const toast = addQueueErrorDialog();

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 5); // toast 監視中
    toast.remove();
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs); // 消失検知 → buffer 開始

    // buffer の途中まで（残り 2 poll 分を残す）では再開しない = 安全マージンが効いている。
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.queueErrorWaitMs - FAST_OPTIONS.pollIntervalMs * 2);
    expect(settled).toBe(false);

    // buffer 完了で resolve。
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.queueErrorWaitMs);
    await expect(pending).resolves.toBeUndefined();
    expect(settled).toBe(true);
  });

  it("Given toast が一度も出ない When 空きスロットあり Then 即 resolve する (toast 無し経路は挙動不変)", async () => {
    addClipRow({ generating: true }); // in-flight 1 < 20、toast なし

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given toast 可視中でも isAborted=true When 待機する Then 即 resolve する (中断優先)", async () => {
    addClipRow({ generating: true });
    addQueueErrorDialog();

    const pending = waitForQueueSlot(20, { isAborted: () => true, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given buffer 待機中に停止 (isAborted=true) When 満了前 Then abortableSleep の poll 粒度内で即 resolve する (#847 停止反応性)", async () => {
    // 本番 queueErrorWaitMs=30000ms。buffer 待機を中断不可の sleep にすると停止が最大 30 秒遅延し、
    // 受け入れ条件「停止後 3 秒以内」を満たさない。abortableSleep の poll(250ms)で中断検知されることを、
    // poll 粒度より十分長い buffer(1000ms)を与え、満了前の停止で resolve することで確認する。
    const SLOW_BUFFER = { pollIntervalMs: 10, timeoutMs: 5000, queueErrorWaitMs: 1000 } as const;
    addClipRow({ generating: true }); // slot は空き（待機要因は buffer のみ）
    const toast = addQueueErrorDialog();

    let aborted = false;
    const pending = waitForQueueSlot(20, { isAborted: () => aborted, ...SLOW_BUFFER });
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(SLOW_BUFFER.pollIntervalMs * 5); // toast 監視中
    toast.remove();
    await vi.advanceTimersByTimeAsync(SLOW_BUFFER.pollIntervalMs); // 消失検知 → buffer 開始
    expect(settled).toBe(false); // buffer 満了(1000ms)前なのでまだ未解決

    // buffer 満了を待たず停止。abortableSleep の poll(250ms)以内で検知され resolve する。
    aborted = true;
    await vi.advanceTimersByTimeAsync(250);
    await expect(pending).resolves.toBeUndefined();
    expect(settled).toBe(true);
  });
});

// inject 後に「実際に CLIPS_PER_REQUEST 個 clip が受理されたか」を in-flight 増分で検証する (#864 root cause 3)。
// 契約 (draft が実装すべき public API、shared/dom.ts):
//   - waitForInFlightIncrease(beforeCount: number, delta: number,
//       options: { isAborted: () => boolean; pollIntervalMs: number; timeoutMs: number }): Promise<boolean>
//     - getInFlightClipCount() >= beforeCount + delta になったら resolve true（受理確認）
//     - timeout で resolve false（throw しない。retry 判断は caller=injectWithVerification 側）
//     - isAborted() が true なら未達でも即 resolve true（停止優先。waitForQueueSlot と同じ中断優先）
//     - 絶対値 beforeCount + delta 比較（相対追跡しない。order.md 契約どおり）
// waitForQueueSlot と異なり throw せず boolean を返す点が本質的な差分。
describe("waitForInFlightIncrease: inject 後の in-flight 増分検証 (#864)", () => {
  const FAST = { pollIntervalMs: 10, timeoutMs: 1000 } as const;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given 既に beforeCount+delta 以上 (before=0, delta=2, in-flight=2) When 待機 Then 即 resolve true", async () => {
    addClipRow({ generating: true });
    addClipRow({ generating: true }); // in-flight 2 >= 0 + 2

    const pending = waitForInFlightIncrease(0, 2, { isAborted: () => false, ...FAST });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBe(true);
  });

  it("Given 投入直後はまだ反映されない→後から delta 分 clip-row 出現 When poll Then resolve true", async () => {
    // inject 直後は clip-row DOM 反映ラグで 0 件。poll 中に 2 件出現したら受理確認。
    const pending = waitForInFlightIncrease(0, 2, { isAborted: () => false, ...FAST });
    let settled: boolean | undefined;
    void pending.then((v) => {
      settled = v;
    });

    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs * 3);
    expect(settled).toBeUndefined(); // 0 件のうちは未達

    addClipRow({ generating: true });
    addClipRow({ generating: true });
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);

    await expect(pending).resolves.toBe(true);
  });

  it("Given delta=2 を 1 件ずつ満たす When 各 poll で再評価 Then 全 delta 到達後にのみ resolve true", async () => {
    const pending = waitForInFlightIncrease(0, 2, { isAborted: () => false, ...FAST });
    let settled: boolean | undefined;
    void pending.then((v) => {
      settled = v;
    });

    addClipRow({ generating: true }); // in-flight 1 < 2
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);
    expect(settled).toBeUndefined(); // 1 件では未達（部分受理では通さない）

    addClipRow({ generating: true }); // in-flight 2 >= 2
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);
    await expect(pending).resolves.toBe(true);
  });

  it("Given 既存 in-flight 4 / before=4 / delta=2 When 6 まで増える Then resolve true (絶対値 before+delta 比較)", async () => {
    // before を明示的に渡し、絶対値 before+delta で判定する契約を pin する。
    Array.from({ length: 4 }, () => addClipRow({ generating: true }));
    expect(getInFlightClipCount()).toBe(4);

    const pending = waitForInFlightIncrease(4, 2, { isAborted: () => false, ...FAST });
    let settled: boolean | undefined;
    void pending.then((v) => {
      settled = v;
    });

    addClipRow({ generating: true }); // 5 < 6
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);
    expect(settled).toBeUndefined();

    addClipRow({ generating: true }); // 6 >= 6
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);
    await expect(pending).resolves.toBe(true);
  });

  it("Given 増分が達しないまま deadline 超過 When 待機 Then resolve false (throw しない)", async () => {
    // silent drop を表現。waitForQueueSlot と違い throw せず false を返し、retry 判断は caller に委ねる。
    const pending = waitForInFlightIncrease(0, 2, { isAborted: () => false, ...FAST });

    await vi.advanceTimersByTimeAsync(FAST.timeoutMs + FAST.pollIntervalMs + 50);

    await expect(pending).resolves.toBe(false);
  });

  it("Given isAborted=true When 増分未達でも待機 Then 即 resolve true (停止優先)", async () => {
    // clip-row は 1 件も無い（未達）が、停止押下中は受理判定より中断を優先して true で抜ける。
    const pending = waitForInFlightIncrease(0, 2, { isAborted: () => true, ...FAST });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBe(true);
  });
});
