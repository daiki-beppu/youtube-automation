// @vitest-environment jsdom
//
// Suno 生成キュー監視 (#816 → #866 で再実装) の回帰テスト。
// Suno が `data-testid="clip-row"` と `svg.animate-spin` を撤去したため、実機検証 (order.md) で
// 「生成中→完了」を 100% 追跡できると確定した `button[aria-label="Remix clip"]` の disabled を軸に
// in-flight 検知を再構築する。音源が揃わない限り Remix できないという Suno のドメインルール由来の
// 状態であり、UI 装飾 (spinner/testid) より変更されにくい。
//
//   - clip カードは「Select clip / Remix clip / Edit title を各 1 つずつ含む最寄り祖先」で識別
//     (findCardRoot による構造的解決。Emotion class hash には依存しない)
//   - 生成中判定 = card 内 Remix btn が disabled (または aria-disabled="true")。strict isVisible() で
//     card 自体も filter
//   - 完了判定 = Remix btn enabled → 生成中ではない
//   - getInFlightClipCount() = 全 Remix btn からカードルートを解決し in-flight な distinct card 数
//   - fail-loud (req 8): Remix btn が 0 件 = DOM 構造が壊れている → silent に 0 を返さず throw
//   - waitForQueueSlot(maxClips, opts) = in-flight < maxClips になるまで poll
//
// 契約 (draft が実装すべき public API、shared/dom.ts):
//   - REMIX_BTN_SELECTOR: string
//   - findCardRoot(anchor: HTMLElement): HTMLElement
//   - isClipGenerating(card: HTMLElement): boolean
//   - getInFlightClipCount(): number   // Remix btn 0 件で throw
//   - waitForQueueSlot(maxClips: number, options: { isAborted; pollIntervalMs; timeoutMs; queueErrorWaitMs }): Promise<void>
//
// jsdom はレイアウトを行わず getBoundingClientRect が常に 0×0 を返すため、strict 可視判定
// 対象の card には markBbox (_helpers.ts) で bbox を擬似的に与える (dom.test.ts と同方針)。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  REMIX_BTN_SELECTOR,
  findCardRoot,
  getInFlightClipCount,
  isClipGenerating,
  waitForQueueSlot,
} from "../../shared/dom";
import { addClipCard, addQueueErrorDialog, buildClipCard, completeClipCard } from "./_helpers";

/** card 内の Remix btn (findCardRoot の anchor) を取り出す。 */
function remixBtnOf(card: HTMLElement): HTMLButtonElement {
  const btn = card.querySelector<HTMLButtonElement>(REMIX_BTN_SELECTOR);
  if (!btn) throw new Error("test fixture 不整合: card に Remix btn がありません。");
  return btn;
}

// queueErrorWaitMs は poll (10ms) と明確に分離して buffer 待機の途中経過を pin できるよう 200ms。
const FAST_OPTIONS = { pollIntervalMs: 10, timeoutMs: 1000, queueErrorWaitMs: 200 } as const;

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("REMIX_BTN_SELECTOR: 実 DOM 検証で確定した in-flight マーカー", () => {
  it('Given 定数 When 読む Then `button[aria-label="Remix clip"]` である', () => {
    expect(REMIX_BTN_SELECTOR).toBe('button[aria-label="Remix clip"]');
  });
});

describe("findCardRoot: Remix btn から clip card root を構造的に解決する", () => {
  it("Given Select/Remix/Edit を各 1 つ持つ card の Remix btn When 解決する Then その card root を返す", () => {
    const card = addClipCard({ generating: true });
    expect(findCardRoot(remixBtnOf(card))).toBe(card);
  });

  it("Given 複数 card を内包する container When 各 Remix btn から解決する Then 上位 container ではなく最寄りの card を返す", () => {
    // 上位 container は Select/Remix/Edit を 2 つずつ持つ。exactly-one 判定が container で止まらず
    // 各カード境界 (各ボタン 1 個ずつ) で確定することを担保する。
    const container = document.createElement("div");
    const card1 = buildClipCard({ generating: true });
    const card2 = buildClipCard({ generating: false });
    container.append(card1, card2);
    document.body.appendChild(container);

    expect(findCardRoot(remixBtnOf(card1))).toBe(card1);
    expect(findCardRoot(remixBtnOf(card2))).toBe(card2);
  });

  it("Given anchor から祖先を辿っても 3 ボタンが揃う card root が無い When 解決する Then throw する (fail-loud)", () => {
    // Select/Edit を伴わない孤立した Remix btn。構造解決できないので silent に返さず throw。
    const lone = document.createElement("button");
    lone.setAttribute("aria-label", "Remix clip");
    document.body.appendChild(lone);

    expect(() => findCardRoot(lone)).toThrow();
  });
});

describe("isClipGenerating: 1 card の生成中判定 (Remix btn disabled)", () => {
  it("Given 可視 card の Remix btn が disabled When 判定する Then true (生成中)", () => {
    const card = addClipCard({ generating: true });
    expect(isClipGenerating(card)).toBe(true);
  });

  it("Given 可視 card の Remix btn が aria-disabled=true When 判定する Then true (生成中)", () => {
    const card = addClipCard({ generating: true, generatingVia: "aria-disabled" });
    expect(isClipGenerating(card)).toBe(true);
  });

  it("Given 可視 card の Remix btn が enabled When 判定する Then false (完了)", () => {
    const card = addClipCard({ generating: false });
    expect(isClipGenerating(card)).toBe(false);
  });

  it("Given Remix btn は disabled だが card が非可視 (display:none/bbox0) When 判定する Then false (strict isVisible で除外)", () => {
    const card = addClipCard({ generating: true, visible: false });
    expect(isClipGenerating(card)).toBe(false);
  });

  it("Given 親が display:none の card When 判定する Then false (親 walk で除外)", () => {
    const wrapper = document.createElement("div");
    wrapper.style.display = "none";
    document.body.appendChild(wrapper);
    const card = buildClipCard({ generating: true }); // bbox は非 0。除外理由は親の display:none のみに限定。
    wrapper.appendChild(card);

    expect(isClipGenerating(card)).toBe(false);
  });

  it("Given card 内に Remix btn が無い When 判定する Then throw する (fail-loud, req 8)", () => {
    const card = document.createElement("div");
    document.body.appendChild(card);
    expect(() => isClipGenerating(card)).toThrow();
  });
});

describe("getInFlightClipCount: in-flight な distinct card 数", () => {
  it("Given 生成中 3 / 完了 1 / 非可視生成中 1 When 数える Then 可視生成中の 3 を返す", () => {
    addClipCard({ generating: true });
    addClipCard({ generating: true });
    addClipCard({ generating: true });
    addClipCard({ generating: false });
    addClipCard({ generating: true, visible: false });

    expect(getInFlightClipCount()).toBe(3);
  });

  it("Given 全て完了 card (Remix enabled) When 数える Then 0 を返す (Remix btn は存在するので throw しない)", () => {
    addClipCard({ generating: false });
    addClipCard({ generating: false });

    expect(getInFlightClipCount()).toBe(0);
  });

  it("Given Remix btn が 1 件も無い When 数える Then throw する (fail-loud, req 8: silent 0 を返さない)", () => {
    // これが本 issue のバグ本体: selector 0 hit を silent に 0 と返すと上限まで過剰投入する。
    expect(() => getInFlightClipCount()).toThrow();
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
    addClipCard({ generating: true }); // in-flight 1 < 20
    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given in-flight が上限ちょうど When 1 clip 完了で空く Then 投入を再開 (resolve) する", async () => {
    // 20 card 生成中 = 10 リクエスト in-flight = 上限。11 件目はここで待たされる。
    const cards = Array.from({ length: 20 }, () => addClipCard({ generating: true }));
    expect(getInFlightClipCount()).toBe(20);

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });

    // 上限のままでは resolve しない（poll しても 20 >= 20）。
    let settled = false;
    void pending.then(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 3);
    expect(settled).toBe(false);

    // 1 clip 完了 (Remix btn enabled) → in-flight 19 < 20 → 次の poll で resolve。
    completeClipCard(cards[0]);
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs);

    await expect(pending).resolves.toBeUndefined();
    expect(getInFlightClipCount()).toBe(19);
  });

  it("Given isAborted が true When 待機する Then 上限超でも即 resolve する (throw しない)", async () => {
    Array.from({ length: 20 }, () => addClipCard({ generating: true }));

    const pending = waitForQueueSlot(20, { isAborted: () => true, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given 上限のまま空かない When deadline 超過 Then timeout throw する", async () => {
    Array.from({ length: 20 }, () => addClipCard({ generating: true }));

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    const expectation = expect(pending).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.timeoutMs + FAST_OPTIONS.pollIntervalMs + 50);
    await expectation;
  });
});

describe("waitForQueueSlot: queue 上限エラー toast 検知 (#847)", () => {
  // race condition (Create→DOM 反映ラグ) で Suno が 21 件目を reject すると「Generation in progress」
  // toast が出る。slot が空いていても toast 中は投入を止め、消失後に queueErrorWaitMs の安全マージンを
  // 待ってから再開する。toast が一度も出ない経路（既存 4 ケース）は挙動不変であること（回帰）も担保済み。
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given toast 可視中 When 空きスロットがあっても Then resolve せず待機を継続する", async () => {
    addClipCard({ generating: true }); // in-flight 1 < 20（スロットは空いている）
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
    addClipCard({ generating: true }); // slot は空き
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
    addClipCard({ generating: true }); // in-flight 1 < 20、toast なし

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given toast 可視中でも isAborted=true When 待機する Then 即 resolve する (中断優先)", async () => {
    addClipCard({ generating: true });
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
    addClipCard({ generating: true }); // slot は空き（待機要因は buffer のみ）
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

// in-flight 増分検証 (waitForInFlightIncrease) は #948 で lib/ack-probe.ts のハイブリッド ACK
// （bridge の generate レスポンス観測 OR DOM 増分）へ移管した。回帰テストは tests/ack-probe.test.ts。

describe("waitForQueueSlot: getCount DI (#948)", () => {
  // Remix disabled プロキシは生成完了後も disabled が残り過大カウントする（実測 20 中 16 誤判定）。
  // bridge の status ベースカウントを getCount として注入できることを担保する。
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given getCount を注入 When 待機する Then DOM プロキシではなく getCount で判定する", async () => {
    // DOM 上は 20 card 生成中（プロキシなら上限到達）だが、getCount は 4 を返す（実 in-flight）。
    Array.from({ length: 20 }, () => addClipCard({ generating: true }));

    const getCount = vi.fn().mockReturnValue(4);
    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS, getCount });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined(); // 4 < 20 で即 resolve（プロキシの 20 では待たされる）
    expect(getCount).toHaveBeenCalled();
  });

  it("Given getCount が上限以上 → poll 中に減る When 待機する Then 減った時点で resolve する", async () => {
    addClipCard({ generating: false }); // DOM 側は完了 card のみ（プロキシなら 0 で即素通し）

    const getCount = vi.fn().mockReturnValue(20);
    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS, getCount });
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 3);
    expect(settled).toBe(false); // getCount=20 >= 20 のうちは待機（DOM の 0 を見ていない）

    getCount.mockReturnValue(18);
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs);
    await expect(pending).resolves.toBeUndefined();
  });

  it("Given getCount 未指定 When 待機する Then 従来どおり DOM プロキシで判定する（後方互換）", async () => {
    addClipCard({ generating: true }); // in-flight 1 < 20

    const pending = waitForQueueSlot(20, { isAborted: () => false, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });
});
