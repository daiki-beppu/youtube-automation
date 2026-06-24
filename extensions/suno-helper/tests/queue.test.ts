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
//   - getInFlightClipCount() = Remix btn のあるカードと明示的な生成中シグナルを持つカードの union 数
//   - clip 候補自体が無く、現在ビューが検出できる場合だけ空 queue として 0
//   - fail-loud (req 8): 現在ビューも検出不能なら silent に 0 を返さず throw
//   - waitForQueueSlot(maxClips, opts) = in-flight < maxClips になるまで poll
//
// 契約 (draft が実装すべき public API、shared/dom.ts):
//   - REMIX_BTN_SELECTOR: string
//   - findCardRoot(anchor: HTMLElement): HTMLElement
//   - isClipGenerating(card: HTMLElement): boolean
//   - getInFlightClipCount(): number
//   - waitForQueueSlot(maxClips: number, options: { isAborted; pollIntervalMs; timeoutMs; queueErrorWaitMs }): Promise<void>
//
// jsdom はレイアウトを行わず getBoundingClientRect が常に 0×0 を返すため、strict 可視判定
// 対象の card には markBbox (_helpers.ts) で bbox を擬似的に与える (dom.test.ts と同方針)。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  REMIX_BTN_SELECTOR,
  detectSunoViewMode,
  findCardRoot,
  getInFlightClipCount,
  isClipGenerating,
  waitForQueueSlot,
} from "../../shared/dom";
import { addClipCard, addQueueErrorDialog, buildClipCard, completeClipCard, markBbox } from "./_helpers";

/** card 内の Remix btn (findCardRoot の anchor) を取り出す。 */
function remixBtnOf(card: HTMLElement): HTMLButtonElement {
  const btn = card.querySelector<HTMLButtonElement>(REMIX_BTN_SELECTOR);
  if (!btn) throw new Error("test fixture 不整合: card に Remix btn がありません。");
  return btn;
}

function makeViewButton(label: string): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.textContent = label;
  markBbox(btn, 120, 32);
  document.body.appendChild(btn);
  return btn;
}

function makeViewTrigger(label: string): HTMLButtonElement {
  const btn = makeViewButton(label);
  btn.setAttribute("aria-haspopup", "listbox");
  return btn;
}

function addViewVariantCard(opts: { view: "waveform" | "grid"; generating: boolean; visible?: boolean }): HTMLElement {
  const card = document.createElement("article");
  card.dataset.view = opts.view;

  const actions = document.createElement("div");
  if (opts.view === "waveform") {
    const select = document.createElement("button");
    select.setAttribute("aria-label", "Select clip");
    actions.appendChild(select);
  }

  const remix = document.createElement("button");
  remix.setAttribute("aria-label", "Remix clip");
  remix.disabled = opts.generating;
  actions.appendChild(remix);
  markBbox(actions, 120, 40);
  card.appendChild(actions);

  if (opts.visible === false) {
    card.style.display = "none";
    markBbox(card, 0, 0);
  } else {
    markBbox(card, 240, 80);
  }
  document.body.appendChild(card);
  return card;
}

function addStatusOnlyCard(opts: { ariaBusy?: boolean; progressbar?: boolean; visible?: boolean }): HTMLElement {
  const card = document.createElement("article");
  const select = document.createElement("button");
  select.setAttribute("aria-label", "Select clip");
  card.appendChild(select);
  if (opts.ariaBusy === true) {
    card.setAttribute("aria-busy", "true");
  }
  if (opts.progressbar === true) {
    const progress = document.createElement("div");
    progress.setAttribute("role", "progressbar");
    card.appendChild(progress);
    markBbox(progress, 120, 8);
  }
  if (opts.visible === false) {
    card.style.display = "none";
    markBbox(card, 0, 0);
  } else {
    markBbox(card, 240, 80);
  }
  markBbox(select, 20, 20);
  document.body.appendChild(card);
  return card;
}

function addListCandidateWithoutCountSignal(): HTMLElement {
  const card = document.createElement("div");
  for (const label of ["Select clip", "Edit title"]) {
    const button = document.createElement("button");
    button.setAttribute("aria-label", label);
    card.appendChild(button);
    markBbox(button, 20, 20);
  }
  markBbox(card, 240, 80);
  document.body.appendChild(card);
  return card;
}

function addNonClipBusyArticle(): HTMLElement {
  const article = document.createElement("article");
  const progress = document.createElement("div");
  progress.setAttribute("role", "progressbar");
  article.appendChild(progress);
  markBbox(progress, 120, 8);
  markBbox(article, 240, 80);
  document.body.appendChild(article);
  return article;
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

describe("detectSunoViewMode: Suno の現在ビューを検出する", () => {
  it("Given view dropdown が List 表記を表示している When 検出する Then list を返す", () => {
    makeViewTrigger("List ▼");

    expect(detectSunoViewMode()).toBe("list");
  });

  it("Given Newest sort dropdown と Waveform view dropdown がある When 検出する Then waveform を返す", () => {
    makeViewTrigger("Newest ▼");
    makeViewTrigger("Waveform");

    expect(detectSunoViewMode()).toBe("waveform");
  });

  it("Given view dropdown が装飾付き Waveform 表記を表示している When 検出する Then waveform を返す", () => {
    makeViewButton("Newest");
    makeViewTrigger("Waveform ▼");

    expect(detectSunoViewMode()).toBe("waveform");
  });

  it("Given Newest sort dropdown と Grid view dropdown がある When 検出する Then grid を返す", () => {
    makeViewTrigger("Newest ▼");
    makeViewTrigger("Grid");

    expect(detectSunoViewMode()).toBe("grid");
  });

  it("Given view dropdown が装飾付き Grid 表記を表示している When 検出する Then grid を返す", () => {
    makeViewButton("Newest");
    makeViewTrigger("Grid ▾");

    expect(detectSunoViewMode()).toBe("grid");
  });

  it("Given menu option が複数 DOM 上にある When current trigger が無い Then unknown を返す", () => {
    makeViewButton("List");
    makeViewButton("Waveform");
    makeViewButton("Grid");

    expect(detectSunoViewMode()).toBe("unknown");
  });

  it("Given selected option が 1 件だけある When 検出する Then selected の view を返す", () => {
    const option = makeViewButton("Grid");
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", "true");
    makeViewButton("List");
    makeViewButton("Waveform");

    expect(detectSunoViewMode()).toBe("grid");
  });

  it("Given view dropdown が DOM 上に無い When 検出する Then unknown を返す", () => {
    makeViewButton("Newest");

    expect(detectSunoViewMode()).toBe("unknown");
  });

  it("Given 状態属性のない単独 Grid button がある When 検出する Then grid を返す", () => {
    makeViewButton("Grid");

    expect(detectSunoViewMode()).toBe("grid");
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

  it("Given Waveform 風 card が Select/Remix だけを持つ When 解決する Then その card root を返す", () => {
    const card = addViewVariantCard({ view: "waveform", generating: true });

    expect(findCardRoot(remixBtnOf(card))).toBe(card);
  });

  it("Given Grid 風 card が Remix だけを持つ When 解決する Then その card root を返す", () => {
    const card = addViewVariantCard({ view: "grid", generating: true });

    expect(findCardRoot(remixBtnOf(card))).toBe(card);
  });

  it("Given Grid 風 card の可視 action wrapper が Remix を持つ When 解決する Then wrapper ではなく article root を返す", () => {
    const card = addViewVariantCard({ view: "grid", generating: true });

    expect(findCardRoot(remixBtnOf(card))).toBe(card);
    expect(findCardRoot(remixBtnOf(card))).not.toBe(remixBtnOf(card).parentElement);
  });

  it("Given Waveform 風 card の可視 action wrapper が Select/Remix を持つ When 解決する Then wrapper ではなく article root を返す", () => {
    const card = addViewVariantCard({ view: "waveform", generating: true });

    expect(findCardRoot(remixBtnOf(card))).toBe(card);
    expect(findCardRoot(remixBtnOf(card))).not.toBe(remixBtnOf(card).parentElement);
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

  it("Given Waveform 風 card が Select/Remix だけを持つ When 数える Then 生成中 card 数を返す", () => {
    addViewVariantCard({ view: "waveform", generating: true });
    addViewVariantCard({ view: "waveform", generating: false });
    addViewVariantCard({ view: "waveform", generating: true, visible: false });

    expect(getInFlightClipCount()).toBe(1);
  });

  it("Given Grid 風 card が Remix だけを持つ When 数える Then 生成中 card 数を返す", () => {
    addViewVariantCard({ view: "grid", generating: true });
    addViewVariantCard({ view: "grid", generating: true });
    addViewVariantCard({ view: "grid", generating: false });

    expect(getInFlightClipCount()).toBe(2);
  });

  it("Given Remix btn が無く明示的な生成中シグナルがある When 数える Then in-flight 数を返す", () => {
    addStatusOnlyCard({ ariaBusy: true });
    addStatusOnlyCard({ progressbar: true });
    addStatusOnlyCard({ ariaBusy: true, visible: false });
    addNonClipBusyArticle();

    expect(getInFlightClipCount()).toBe(2);
  });

  it("Given 完了 Remix card と Remix 不在の生成中 card が混在 When 数える Then union した in-flight 数を返す", () => {
    addClipCard({ generating: false });
    addStatusOnlyCard({ ariaBusy: true });
    addStatusOnlyCard({ progressbar: true });

    expect(getInFlightClipCount()).toBe(2);
  });

  it("Given Remix btn が無く代替生成中シグナルも無い When 数える Then throw する (fail-loud)", () => {
    expect(() => getInFlightClipCount()).toThrow();
  });

  it("Given Grid view で clip 候補自体が無い When 数える Then 空 queue として 0 を返す", () => {
    makeViewTrigger("Newest ▼");
    makeViewTrigger("Grid ▼");

    expect(getInFlightClipCount()).toBe(0);
  });

  it("Given Grid view で clip 候補はあるが Remix も生成中シグナルも無い When 数える Then throw する", () => {
    makeViewTrigger("Newest ▼");
    makeViewTrigger("Grid ▼");
    addStatusOnlyCard({});

    expect(() => getInFlightClipCount()).toThrow();
  });

  it("Given List view の div clip 候補に Remix も生成中シグナルも無い When 数える Then throw する", () => {
    makeViewTrigger("Newest ▼");
    makeViewTrigger("List ▼");
    addListCandidateWithoutCountSignal();

    expect(() => getInFlightClipCount()).toThrow();
  });

  it.each(["waveform", "grid"] as const)(
    "Given %s view で completed Remix card と signal 欠落 clip 候補が混在 When 数える Then throw する",
    (view) => {
      makeViewTrigger("Newest ▼");
      makeViewTrigger(view === "waveform" ? "Waveform" : "Grid");
      addViewVariantCard({ view, generating: false });
      addStatusOnlyCard({});

      expect(() => getInFlightClipCount()).toThrow();
    },
  );
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
  }, 15_000);
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

describe("waitForQueueSlot: stall ベース判定 (#948)", () => {
  // 正確な in-flight カウントの下では「上限で長く待つ」のは正常状態（clip 完了に数分かかる）。
  // getLastChangeAt 注入時は固定 deadline を廃し、in-flight 集合が stallTimeoutMs 変化しない
  // ときのみ throw する。status 遷移が続く限り timeoutMs を超えても待ち続けることを pin する。
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const STALL = { pollIntervalMs: 10, timeoutMs: 100, queueErrorWaitMs: 200, stallTimeoutMs: 1000 } as const;

  it("Given status 遷移が続く（lastChangeAt が更新され続ける） When timeoutMs を超えて待つ Then throw せず待機を継続する", async () => {
    addClipCard({ generating: false }); // DOM fallback の throw 回避用 seed（getCount 注入で参照されない）
    const getCount = vi.fn().mockReturnValue(20);
    let lastChange = 0;
    const pending = waitForQueueSlot(20, {
      isAborted: () => false,
      ...STALL,
      getCount,
      getLastChangeAt: () => lastChange,
    });
    let outcome: "resolved" | "rejected" | undefined;
    pending.then(
      () => {
        outcome = "resolved";
      },
      () => {
        outcome = "rejected";
      },
    );

    // 固定 deadline (timeoutMs=100) を大きく超えても、変化が続く限り throw しない。
    for (let i = 0; i < 5; i++) {
      lastChange = Date.now(); // status 遷移を模す
      await vi.advanceTimersByTimeAsync(STALL.stallTimeoutMs / 2);
    }
    expect(outcome).toBeUndefined();

    getCount.mockReturnValue(18); // slot が空いたら resolve
    await vi.advanceTimersByTimeAsync(STALL.pollIntervalMs);
    expect(outcome).toBe("resolved");
  });

  it("Given in-flight 集合が stallTimeoutMs 変化しない When 待機する Then stall として throw する", async () => {
    addClipCard({ generating: false });
    const getCount = vi.fn().mockReturnValue(20);
    const pending = waitForQueueSlot(20, {
      isAborted: () => false,
      ...STALL,
      getCount,
      getLastChangeAt: () => 0, // 一度も変化しない
    });
    const expectation = expect(pending).rejects.toThrow(/変化しませんでした/);
    await vi.advanceTimersByTimeAsync(STALL.stallTimeoutMs + STALL.pollIntervalMs + 50);
    await expectation;
  });

  it("Given stall 経路でも isAborted=true When 待機する Then 即 resolve する（中断優先）", async () => {
    addClipCard({ generating: false });
    const pending = waitForQueueSlot(20, {
      isAborted: () => true,
      ...STALL,
      getCount: () => 20,
      getLastChangeAt: () => 0,
    });
    await vi.advanceTimersByTimeAsync(0);
    await expect(pending).resolves.toBeUndefined();
  });

  it("Given getLastChangeAt 未注入 When 待機する Then 従来どおり固定 deadline で throw する（後方互換）", async () => {
    addClipCard({ generating: false });
    const pending = waitForQueueSlot(20, {
      isAborted: () => false,
      pollIntervalMs: 10,
      timeoutMs: 100,
      queueErrorWaitMs: 200,
      getCount: () => 20,
    });
    const expectation = expect(pending).rejects.toThrow(/タイムアウト/);
    await vi.advanceTimersByTimeAsync(100 + 10 + 50);
    await expectation;
  });
});

describe("waitForQueueSlot × clip-tracker 統合: 実測シナリオの回帰 (#948)", () => {
  // 実測で確認した「DOM 上 20 clips が Remix disabled だが実 status は complete 16 / streaming 4」
  // の状況で、status ベースのカウントなら即投入再開されることを tracker と組み合わせて pin する。
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given DOM 20 disabled / 実 status complete 16 + streaming 4 When tracker を getCount に注入 Then 即投入再開する", async () => {
    const { createClipTracker } = await import("../lib/clip-tracker");
    // DOM プロキシ視点では 20 clips すべて生成中（Balanced 上限 10 を常時超過 = 旧バグの再現条件）。
    Array.from({ length: 20 }, () => addClipCard({ generating: true }));
    expect(getInFlightClipCount()).toBe(20);

    const tracker = createClipTracker();
    const clips = Array.from({ length: 20 }, (_, i) => ({ id: `c${i}`, status: "submitted" }));
    for (let i = 0; i < 10; i++) {
      tracker.registerSubmitted(clips.slice(i * 2, i * 2 + 2));
    }
    tracker.applyFeedStatuses(clips.map((c, i) => ({ id: c.id, status: i < 16 ? "complete" : "streaming" })));
    expect(tracker.getInFlightCount()).toBe(4);

    const pending = waitForQueueSlot(10, {
      isAborted: () => false,
      ...FAST_OPTIONS,
      getCount: () => tracker.getInFlightCount(),
      getLastChangeAt: () => tracker.lastChangeAt(),
      stallTimeoutMs: 600000,
    });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined(); // 4 < 10 で即 resolve（DOM プロキシなら 20 >= 10 で待機）
  });
});
