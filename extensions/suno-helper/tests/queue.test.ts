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
//   - waitForQueueSlot(maxClips: number, options: { isAborted; pollIntervalMs; timeoutMs }): Promise<void>
//
// jsdom はレイアウトを行わず getBoundingClientRect が常に 0×0 を返すため、strict 可視判定
// 対象の row には markBbox (_helpers.ts) で bbox を擬似的に与える (dom.test.ts と同方針)。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CLIP_ROW_SELECTOR, getInFlightClipCount, isClipGenerating, waitForQueueSlot } from "../../shared/dom";
import { markBbox } from "./_helpers";

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

const FAST_OPTIONS = { pollIntervalMs: 10, timeoutMs: 1000 } as const;

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
