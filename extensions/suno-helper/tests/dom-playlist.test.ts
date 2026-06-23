// @vitest-environment jsdom
//
// clip 一括 playlist 追加 (#854) の DOM 操作群 `shared/playlist-dom.ts` の回帰テスト。
// order.md 実機 DOM 検証で確定したセレクタ・操作仕様を担保する:
//   - clip row は `.clip-browser-list-scroller` 直下の `div` のうち内側に `.multi-select-button` の
//     Select/Deselect ボタンを含むもので識別する（#881 で `data-testid="clip-row"` 廃止に追従）。
//     生成中 / 完了は区別しない（status フィルタなし、#862）
//   - multi-select は `.multi-select-button > button[aria-label="Select clip"]` を click（未選択のみマッチ）し、
//     click 後 `.multi-select-button > button[aria-label="Deselect clip"]` への遷移を poll で verify する (#878)
//   - Cmd+P (Mac=metaKey / 他=ctrlKey) を document に dispatch して Add to Playlist dialog を開く
//   - dialog は text "Add to Playlist" を含む可視 `[role="dialog"]`。OneTrust cookie dialog
//     (id^="ot-" / aria-label が /privacy/i) は除外フィルタで拾わない
//   - dialog 内 `input[placeholder="Playlist Name"]` に setNativeValue、Create Playlist ボタンを click
//
// 契約 (shared/playlist-dom.ts の public API):
//   - CLIP_LIST_SCROLLER_SELECTOR: string = '.clip-browser-list-scroller'
//   - SELECT_CLIP_BUTTON_SELECTOR: string = '.multi-select-button > button[aria-label="Select clip"]'
//   - DESELECT_CLIP_BUTTON_SELECTOR: string = '.multi-select-button > button[aria-label="Deselect clip"]'
//   - PLAYLIST_NAME_INPUT_SELECTOR: string = 'input[placeholder="Playlist Name"]'
//   - ensureClipRowsLoadedByIds(ids, opts): Promise<HTMLElement[]>  // ID 指定 + 遅延ロード対応。scroller 不在 / row 0 件で fail-loud throw (#881)
//   - ensureClipRowsLoaded(count, opts): Promise<HTMLElement[]>  // count 件ベース + 遅延ロード対応 (#924)
//   - multiSelectClips(rows: HTMLElement[]): Promise<void>  // 空 rows / click 後 selected 不遷移で fail-loud (#878, #881)
//   - openAddToPlaylistDialogViaCmdP(): Promise<HTMLElement>
//   - fillPlaylistNameAndCreate(dialog: HTMLElement, name: string): Promise<void>
//   - waitForPlaylistDialogClose(opts: { isAborted; pollIntervalMs; timeoutMs }): Promise<void>
//
// jsdom はレイアウトを行わず getBoundingClientRect が常に 0×0 を返すため、strict 可視判定
// 対象要素には markBbox (_helpers.ts) で bbox を擬似的に与える (dom.test.ts / queue.test.ts と同方針)。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CLIP_LIST_SCROLLER_SELECTOR,
  DESELECT_CLIP_BUTTON_SELECTOR,
  PLAYLIST_NAME_INPUT_SELECTOR,
  PLAYLIST_ROW_LABEL_SELECTOR,
  SELECT_CLIP_BUTTON_SELECTOR,
  clickPlaylistRowByName,
  ensureClipRowsLoaded,
  ensureClipRowsLoadedByIds,
  fillPlaylistNameAndCreate,
  multiSelectClips,
  openAddToPlaylistDialogViaCmdP,
  waitForPlaylistDialogClose,
} from "../../shared/playlist-dom";
import { markBbox } from "./_helpers";

/**
 * clip list の scroll container `.clip-browser-list-scroller` を取得（無ければ作成）する (#881)。
 */
function getOrCreateScroller(): HTMLElement {
  const existing = document.querySelector<HTMLElement>(".clip-browser-list-scroller");
  if (existing) {
    return existing;
  }
  const scroller = document.createElement("div");
  scroller.className = "clip-browser-list-scroller";
  document.body.appendChild(scroller);
  return scroller;
}

/**
 * scroller 直下の「単一中間ラッパ div」を取得（無ければ作成）する (#881)。
 *
 * 実機 Suno (order.md L26) は `scroller > 単一中間ラッパ div > 複数 per-clip div > ... >
 * .multi-select-button` 構造で、per-clip div は **scroller の直接子ではなく** この 1 つの
 * ラッパ配下に並ぶ。全 clip row をこの単一ラッパに入れることで、`:scope > div`（scroller 直下
 * div を row とする素朴実装 = 中間ラッパ 1 件に collapse する）と、ボタン基点の per-clip 導出を
 * 区別できる fixture になる（VAL-NEW-dom-playlist-test-L74 の collapse 検出）。
 * class 名は構造判定に使われないため、fixture 内の再取得用マーカーとしてのみ付与する。
 */
function getOrCreateClipList(): HTMLElement {
  const scroller = getOrCreateScroller();
  const existing = scroller.querySelector<HTMLElement>(":scope > div.clip-list-wrapper");
  if (existing) {
    return existing;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "clip-list-wrapper";
  scroller.appendChild(wrapper);
  return wrapper;
}

/**
 * 新 Suno DOM 構造 (#881) の clip row を単一中間ラッパ配下に挿入する。
 *   scroller > div.clip-list-wrapper > div(per-clip = 返り値 row) > .multi-select-button > button
 * を写像する。Emotion の hash class は構造判定に使わないため、ここでは付与しない。
 * ID ベース row loader（内部の collectLoadedClipRows）は button の
 * `closest('.multi-select-button').parentElement`（= per-clip div）を row として導出するため、
 * 返り値 `row` はその per-clip div になる。
 *   - selectLabel: multi-select ボタンの aria-label（"Select clip"=未選択 / "Deselect clip"=選択済み）
 *   - visible=false: display:none + bbox 0×0（strict isVisible で除外される行）
 */
function addClipRow(
  opts: {
    selectLabel?: string;
    visible?: boolean;
    songId?: string;
    idSource?: "href" | "data-song-id" | "data-clip-id";
  } = {},
): {
  row: HTMLElement;
  btn: HTMLButtonElement;
} {
  const { selectLabel = "Select clip", visible = true, songId, idSource = "href" } = opts;
  const list = getOrCreateClipList();

  const row = document.createElement("div"); // per-clip div（.multi-select-button の親 = 導出される row）
  if (songId && idSource === "data-song-id") {
    row.dataset.songId = songId;
  }
  if (songId && idSource === "data-clip-id") {
    row.dataset.clipId = songId;
  }
  if (songId && idSource === "href") {
    const songLink = document.createElement("a");
    songLink.href = `/song/${songId}`;
    songLink.textContent = songId;
    row.appendChild(songLink);
  }
  const wrapper = document.createElement("div");
  wrapper.className = "multi-select-button";
  const btn = document.createElement("button");
  btn.setAttribute("aria-label", selectLabel);
  wrapper.appendChild(btn);
  row.appendChild(wrapper);
  list.appendChild(row);

  if (visible === false) {
    row.style.display = "none";
    markBbox(row, 0, 0);
  } else {
    markBbox(row, 200, 60);
  }
  markBbox(btn, 20, 20);
  return { row, btn };
}

function addAlternateViewRows(
  count: number,
  opts: { selectLabel?: string } = {},
): {
  viewport: HTMLElement;
  rows: HTMLElement[];
  buttons: HTMLButtonElement[];
} {
  const viewport = document.createElement("section");
  viewport.dataset.sunoClipViewport = "grid";
  viewport.style.overflowY = "auto";
  markBbox(viewport, 480, 360);
  document.body.appendChild(viewport);

  const rows: HTMLElement[] = [];
  const buttons: HTMLButtonElement[] = [];
  for (let i = 0; i < count; i++) {
    const row = document.createElement("article");
    row.dataset.clipOrdinal = String(i);
    const btn = document.createElement("button");
    btn.setAttribute("aria-label", opts.selectLabel ?? "Select clip");
    row.appendChild(btn);
    viewport.appendChild(row);
    markBbox(row, 200, 60);
    markBbox(btn, 20, 20);
    rows.push(row);
    buttons.push(btn);
  }
  return { viewport, rows, buttons };
}

function addAlternateViewRow(
  viewport: HTMLElement,
  index: number,
): {
  row: HTMLElement;
  btn: HTMLButtonElement;
} {
  const row = document.createElement("article");
  row.dataset.clipOrdinal = String(index);
  const btn = document.createElement("button");
  btn.setAttribute("aria-label", "Select clip");
  row.appendChild(btn);
  viewport.appendChild(row);
  markBbox(row, 200, 60);
  markBbox(btn, 20, 20);
  return { row, btn };
}

/**
 * Add to Playlist dialog を模した `[role="dialog"]` を body に挿入する。
 *   - text: 内部見出しの textContent（判定対象。order.md の span#_r_dg_ 相当）
 *   - ariaLabel / id: cookie 除外フィルタ検証用（"Privacy Preference Center" / "ot-..."）
 *   - visible=false: display:none + bbox 0×0（strict isVisible で除外される残骸）
 */
function addPlaylistDialog(
  opts: { text?: string; ariaLabel?: string; id?: string; visible?: boolean } = {},
): HTMLElement {
  const { text = "Add to Playlist", ariaLabel, id, visible = true } = opts;
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  if (ariaLabel !== undefined) dialog.setAttribute("aria-label", ariaLabel);
  if (id !== undefined) dialog.id = id;

  const heading = document.createElement("span");
  heading.textContent = text;
  dialog.appendChild(heading);
  document.body.appendChild(dialog);

  if (visible === false) {
    dialog.style.display = "none";
    markBbox(dialog, 0, 0);
  } else {
    markBbox(dialog, 400, 300);
  }
  return dialog;
}

/** Playlist Name input と Create Playlist / Liked Songs ボタンを備えた dialog を作る。 */
function addDialogWithForm(): {
  dialog: HTMLElement;
  input: HTMLInputElement;
  liked: HTMLButtonElement;
  create: HTMLButtonElement;
} {
  const dialog = addPlaylistDialog();
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Playlist Name";
  markBbox(input, 200, 30);

  const liked = document.createElement("button");
  liked.textContent = "Liked Songs";
  markBbox(liked, 100, 30);

  const create = document.createElement("button");
  create.textContent = "Create Playlist";
  markBbox(create, 100, 30);

  dialog.append(input, liked, create);
  return { dialog, input, liked, create };
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("playlist-dom セレクタ定数: 実機 DOM 検証で確定した安定識別子", () => {
  it("Given CLIP_LIST_SCROLLER_SELECTOR When 読む Then clip list の scroll container class セレクタである", () => {
    expect(CLIP_LIST_SCROLLER_SELECTOR).toBe(".clip-browser-list-scroller");
  });

  it("Given SELECT_CLIP_BUTTON_SELECTOR When 読む Then 未選択の Select clip ボタンセレクタである", () => {
    expect(SELECT_CLIP_BUTTON_SELECTOR).toBe('.multi-select-button > button[aria-label="Select clip"]');
  });

  it("Given DESELECT_CLIP_BUTTON_SELECTOR When 読む Then 選択済みを示す Deselect clip ボタンセレクタである（Select と対称）", () => {
    expect(DESELECT_CLIP_BUTTON_SELECTOR).toBe('.multi-select-button > button[aria-label="Deselect clip"]');
  });

  it("Given PLAYLIST_NAME_INPUT_SELECTOR When 読む Then Playlist Name input セレクタである", () => {
    expect(PLAYLIST_NAME_INPUT_SELECTOR).toBe('input[placeholder="Playlist Name"]');
  });

  it("Given PLAYLIST_ROW_LABEL_SELECTOR When 読む Then dialog 内 row の label を識別する Tailwind class セレクタである", () => {
    expect(PLAYLIST_ROW_LABEL_SELECTOR).toBe("div.ml-4.font-sans");
  });
});

/**
 * scroller に遅延ロード scroll イベントリスナーを取り付けるヘルパ。
 * jsdom にはレイアウトエンジンがないため scrollHeight を Object.defineProperty で stub し、
 * scrollTop の setter で値を保持する stub にする。
 * scroller の scroll イベントが発火するたびに追加 row を batchSize 件 append する。
 * これにより「scrollTop 代入 + scroll event dispatch → +N row」の遅延ロードを写像する。
 */
function setupLazyLoader(scroller: HTMLElement, batchSize: number, opts: { initialScrollHeight?: number } = {}): void {
  // scrollHeight stub（初期値を与えないと 0 のまま）
  let _scrollHeight = opts.initialScrollHeight ?? 1000;
  Object.defineProperty(scroller, "scrollHeight", {
    configurable: true,
    get: () => _scrollHeight,
  });

  // scrollTop を setter で値保持（jsdom はデフォルト readonly 相当）
  let _scrollTop = 0;
  Object.defineProperty(scroller, "scrollTop", {
    configurable: true,
    get: () => _scrollTop,
    set: (v: number) => {
      _scrollTop = v;
    },
  });

  // scroll イベントで追加 row を append
  scroller.addEventListener("scroll", () => {
    for (let i = 0; i < batchSize; i++) {
      addClipRow();
    }
    // scrollHeight も伸ばして次回ループが進むようにする
    _scrollHeight += batchSize * 60;
  });
}

function setupAlternateLazyLoader(viewport: HTMLElement, batchSize: number): void {
  let _scrollHeight = 1000;
  Object.defineProperty(viewport, "scrollHeight", {
    configurable: true,
    get: () => _scrollHeight,
  });

  let _scrollTop = 0;
  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    get: () => _scrollTop,
    set: (v: number) => {
      _scrollTop = v;
    },
  });

  viewport.addEventListener("scroll", () => {
    const existing = viewport.querySelectorAll("article").length;
    for (let i = 0; i < batchSize; i++) {
      addAlternateViewRow(viewport, existing + i);
    }
    _scrollHeight += batchSize * 60;
  });
}

function setupStepwiseLazyLoader(
  scroller: HTMLElement,
  batchSize: number,
  dimensions: { scrollHeight: number; clientHeight: number },
  opts: { maxBatches?: number } = {},
): { scrollPositions: number[] } {
  let scrollHeight = dimensions.scrollHeight;
  let scrollTop = 0;
  const { clientHeight } = dimensions;
  const scrollPositions: number[] = [];
  const maxBatches = opts.maxBatches ?? 1;

  Object.defineProperty(scroller, "scrollHeight", {
    configurable: true,
    get: () => scrollHeight,
  });
  Object.defineProperty(scroller, "clientHeight", {
    configurable: true,
    get: () => clientHeight,
  });
  Object.defineProperty(scroller, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = v;
    },
  });

  let loadedBatches = 0;
  scroller.addEventListener("scroll", () => {
    scrollPositions.push(scrollTop);
    const maxScrollTop = scrollHeight - clientHeight;
    if (loadedBatches >= maxBatches || scrollTop <= 0 || scrollTop >= maxScrollTop) {
      return;
    }
    loadedBatches += 1;
    for (let i = 0; i < batchSize; i++) {
      addClipRow();
    }
    scrollHeight += batchSize * 60;
  });
  return { scrollPositions };
}

function setupBottomAfterIntermediateLazyLoader(
  scroller: HTMLElement,
  batchSize: number,
  dimensions: { scrollHeight: number; clientHeight: number },
): { scrollPositions: number[] } {
  let scrollHeight = dimensions.scrollHeight;
  let scrollTop = 0;
  const { clientHeight } = dimensions;
  const scrollPositions: number[] = [];

  Object.defineProperty(scroller, "scrollHeight", {
    configurable: true,
    get: () => scrollHeight,
  });
  Object.defineProperty(scroller, "clientHeight", {
    configurable: true,
    get: () => clientHeight,
  });
  Object.defineProperty(scroller, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = v;
    },
  });

  let loaded = false;
  scroller.addEventListener("scroll", () => {
    scrollPositions.push(scrollTop);
    const maxScrollTop = scrollHeight - clientHeight;
    if (loaded || scrollTop < maxScrollTop) {
      return;
    }
    loaded = true;
    for (let i = 0; i < batchSize; i++) {
      addClipRow();
    }
    scrollHeight += batchSize * 60;
  });
  return { scrollPositions };
}

describe("ensureClipRowsLoadedByIds: 生成 run の submitted ID による clip row 収集", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given 単一中間ラッパ配下に複数 per-clip div When target ID で取得する Then 各 clip を別 row に分離する", async () => {
    const rows = [
      addClipRow({ songId: "fresh-a" }).row,
      addClipRow({ songId: "fresh-b" }).row,
      addClipRow({ songId: "fresh-c" }).row,
    ];
    const scroller = getOrCreateScroller();
    expect(scroller.querySelectorAll(":scope > div").length).toBe(1);

    const pending = ensureClipRowsLoadedByIds(["fresh-a", "fresh-b", "fresh-c"], {
      isAborted: () => false,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toEqual(rows);
    expect(new Set(result).size).toBe(3);
  });

  it("Given DOM 先頭に古い row がある When target ID で取得する Then 今回生成した row だけを返す", async () => {
    addClipRow({ songId: "old-a" });
    addClipRow({ songId: "old-b" });
    const freshA = addClipRow({ songId: "fresh-a" }).row;
    const freshB = addClipRow({ songId: "fresh-b" }).row;

    const pending = ensureClipRowsLoadedByIds(["fresh-a", "fresh-b"], {
      isAborted: () => false,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toHaveLength(2);
    expect(new Set(result)).toEqual(new Set([freshA, freshB]));
  });

  it("Given row が明示 data 属性で song ID を持つ When target ID で取得する Then 該当 row を返す", async () => {
    const bySongId = addClipRow({ songId: "fresh-data-song", idSource: "data-song-id" }).row;
    const byClipId = addClipRow({ songId: "fresh-data-clip", idSource: "data-clip-id" }).row;

    const pending = ensureClipRowsLoadedByIds(["fresh-data-song", "fresh-data-clip"], {
      isAborted: () => false,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(new Set(result)).toEqual(new Set([bySongId, byClipId]));
  });

  it("Given target ID が追加ロード後に現れる When target ID で取得する Then scroll して該当 row を返す", async () => {
    addClipRow({ songId: "old-a" });
    const scroller = getOrCreateScroller();
    let loaded = false;
    Object.defineProperty(scroller, "scrollHeight", {
      configurable: true,
      get: () => 1000,
    });
    Object.defineProperty(scroller, "scrollTop", {
      configurable: true,
      get: () => 0,
      set: () => undefined,
    });
    scroller.addEventListener("scroll", () => {
      if (!loaded) {
        loaded = true;
        addClipRow({ songId: "fresh-late" });
      }
    });

    const pending = ensureClipRowsLoadedByIds(["fresh-late"], {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toHaveLength(1);
    expect(result[0].querySelector<HTMLAnchorElement>('a[href="/song/fresh-late"]')).not.toBeNull();
  });

  it("Given target ID が揃った後 When target ID で取得する Then scrollTop が 0 に戻る", async () => {
    addClipRow({ songId: "fresh-a" });
    const scroller = getOrCreateScroller();
    let scrollTop = 500;
    Object.defineProperty(scroller, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = value;
      },
    });

    const pending = ensureClipRowsLoadedByIds(["fresh-a"], { isAborted: () => false });
    await vi.runAllTimersAsync();
    await pending;

    expect(scrollTop).toBe(0);
  });

  it("Given target ID が最後まで不足する When target ID で取得する Then missing ID を含むエラーで throw する", async () => {
    addClipRow({ songId: "old-a" });

    const pending = ensureClipRowsLoadedByIds(["fresh-missing"], {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 200,
    });
    const expectation = expect(pending).rejects.toThrow(/fresh-missing/);
    await vi.advanceTimersByTimeAsync(1000);
    await expectation;
  });

  it("Given .clip-browser-list-scroller が存在しない When target ID で取得する Then fail-loud で throw する", async () => {
    await expect(ensureClipRowsLoadedByIds(["fresh-a"], { isAborted: () => false })).rejects.toThrow(
      /clip row が見つかりません/,
    );
  });

  it("Given scroller はあるが clip row が 0 件 When target ID で取得する Then fail-loud で throw する", async () => {
    getOrCreateScroller();

    await expect(ensureClipRowsLoadedByIds(["fresh-a"], { isAborted: () => false })).rejects.toThrow(
      /clip row が見つかりません/,
    );
  });

  it("Given isAborted=true When target ID で取得する Then 見つかった row だけを返して throw しない", async () => {
    const found = addClipRow({ songId: "fresh-a" }).row;

    const pending = ensureClipRowsLoadedByIds(["fresh-a", "fresh-missing"], {
      isAborted: () => true,
    });
    await vi.runAllTimersAsync();

    await expect(pending).resolves.toEqual([found]);
  });
});

describe("ensureClipRowsLoaded: 遅延ロード対応 clip row 収集 (#924)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given 初期ロードで count 件揃っている When ensureClipRowsLoaded Then スクロールなしで先頭 count 件を返す", async () => {
    // 5 row ロード済み、count=5 → 即返す
    const rows = Array.from({ length: 5 }, () => addClipRow().row);

    const pending = ensureClipRowsLoaded(5, { isAborted: () => false });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toEqual(rows);
  });

  it("Given 単一中間ラッパ配下に複数 per-clip div When 取得する Then 各 clip を別 row に分離する（1 row に collapse しない）", async () => {
    // 実機 (order.md L26) は scroller 直下が単一中間ラッパで、per-clip div はその配下に並ぶ。
    const rows = Array.from({ length: 3 }, () => addClipRow().row);

    // fixture が「scroller 直下 = 単一中間ラッパ 1 件」構造であることを明示
    const scroller = getOrCreateScroller();
    expect(scroller.querySelectorAll(":scope > div").length).toBe(1);

    const pending = ensureClipRowsLoaded(3, { isAborted: () => false });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toEqual(rows);
    expect(new Set(result).size).toBe(3); // per-clip で 3 件（collapse なら 1 で落ちる）
  });

  it("Given 未選択・選択済み row が混在 When 取得する Then どちらも row として返す", async () => {
    const a = addClipRow({ selectLabel: "Select clip" }).row;
    const b = addClipRow({ selectLabel: "Deselect clip" }).row;
    const c = addClipRow({ selectLabel: "Select clip" }).row;

    const pending = ensureClipRowsLoaded(3, { isAborted: () => false });
    await vi.runAllTimersAsync();
    expect(await pending).toEqual([a, b, c]);
  });

  it("Given scroller 内 5 row When count=3 Then 先頭 3 row だけ返す", async () => {
    const rows = Array.from({ length: 5 }, () => addClipRow().row);

    const pending = ensureClipRowsLoaded(3, { isAborted: () => false });
    await vi.runAllTimersAsync();
    expect(await pending).toEqual(rows.slice(0, 3));
  });

  it("Given 非可視 row が混在 When 取得する Then strict isVisible で除外する", async () => {
    const visible = addClipRow().row;
    addClipRow({ visible: false });

    const pending = ensureClipRowsLoaded(1, { isAborted: () => false });
    await vi.runAllTimersAsync();
    expect(await pending).toEqual([visible]);
  });

  it("Given .clip-browser-list-scroller が無い Grid 風 container When 取得する Then Select clip button から row を解決する", async () => {
    const { rows } = addAlternateViewRows(3);

    await expect(ensureClipRowsLoaded(3, { isAborted: () => false })).resolves.toEqual(rows);
  });

  it("Given 非表示 row だけの .clip-browser-list-scroller と Grid 風 container When 取得する Then visible な Grid 側 rows を返す", async () => {
    addClipRow({ visible: false });
    const { rows } = addAlternateViewRows(3);

    await expect(ensureClipRowsLoaded(3, { isAborted: () => false })).resolves.toEqual(rows);
  });

  it("Given .clip-browser-list-scroller が無い Grid 風 container で初期不足 When 取得する Then 代替 scroller を scroll して count 件を返す", async () => {
    const { viewport, rows } = addAlternateViewRows(3);
    setupAlternateLazyLoader(viewport, 2);

    const pending = ensureClipRowsLoaded(5, {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toHaveLength(5);
    expect(result.slice(0, 3)).toEqual(rows);
  });

  it("Given Select clip button が generic parent しか持たない When 取得する Then row 不明として fail-loud で throw する", async () => {
    const parent = document.createElement("div");
    const btn = document.createElement("button");
    btn.setAttribute("aria-label", "Select clip");
    parent.appendChild(btn);
    document.body.appendChild(parent);
    markBbox(parent, 200, 60);
    markBbox(btn, 20, 20);

    await expect(ensureClipRowsLoaded(1, { isAborted: () => false })).rejects.toThrow(/clip row が見つかりません/);
  });

  it("Given 初期不足 → 1 回の追加ロードで揃う When ensureClipRowsLoaded Then scroll イベントで row が増えてから返す", async () => {
    // 初期 2 row、count=4 → scroll 1 回で +2 row → 計 4 件で揃う
    const initial = Array.from({ length: 2 }, () => addClipRow().row);
    const scroller = getOrCreateScroller();
    setupLazyLoader(scroller, 2); // scroll 1 回で +2 row

    const pending = ensureClipRowsLoaded(4, {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toHaveLength(4);
    expect(result.slice(0, 2)).toEqual(initial); // 先頭 2 件は元の row
  });

  it("Given 複数回の追加ロードで揃う When ensureClipRowsLoaded Then 複数回スクロールして返す", async () => {
    // 初期 1 row、count=3 → scroll 2 回で +1+1 row → 計 3 件
    addClipRow();
    const scroller = getOrCreateScroller();
    setupLazyLoader(scroller, 1); // scroll 1 回で +1 row

    const pending = ensureClipRowsLoaded(3, {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toHaveLength(3);
  });

  it("Given bottom jump では増えない stepwise loader When ensureClipRowsLoaded Then 複数バッチで 23 件から 30 件までロードする", async () => {
    Array.from({ length: 23 }, () => addClipRow().row);
    const scroller = getOrCreateScroller();
    const { scrollPositions } = setupStepwiseLazyLoader(
      scroller,
      5,
      {
        scrollHeight: 1000,
        clientHeight: 200,
      },
      { maxBatches: 2 },
    );

    const pending = ensureClipRowsLoaded(30, {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toHaveLength(30);
    expect(scrollPositions).not.toContain(1100);
  });

  it("Given 最大スクロール量が step 以下 When ensureClipRowsLoaded Then 初回から末尾に飛ばず中間 scroll event を発火する", async () => {
    Array.from({ length: 23 }, () => addClipRow().row);
    const scroller = getOrCreateScroller();
    const { scrollPositions } = setupStepwiseLazyLoader(scroller, 5, {
      scrollHeight: 700,
      clientHeight: 200,
    });

    const pending = ensureClipRowsLoaded(28, {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toHaveLength(28);
    expect(scrollPositions[0]).toBeGreaterThan(0);
    expect(scrollPositions[0]).toBeLessThan(500);
  });

  it("Given 初回中間では増えず末尾で増える loader When ensureClipRowsLoaded Then 2 回目以降に末尾へ到達してロードする", async () => {
    Array.from({ length: 23 }, () => addClipRow().row);
    const scroller = getOrCreateScroller();
    const { scrollPositions } = setupBottomAfterIntermediateLazyLoader(scroller, 5, {
      scrollHeight: 700,
      clientHeight: 200,
    });

    const pending = ensureClipRowsLoaded(28, {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result).toHaveLength(28);
    expect(scrollPositions[0]).toBeGreaterThan(0);
    expect(scrollPositions[0]).toBeLessThan(500);
    expect(scrollPositions).toContain(500);
  });

  it("Given bottom jump では増えない loader When playlist 追加フロー Then 本番 API で 8 件選択して dialog close まで到達する", async () => {
    Array.from({ length: 4 }, () => addClipRow().row);
    const scroller = getOrCreateScroller();
    const { scrollPositions } = setupStepwiseLazyLoader(scroller, 4, {
      scrollHeight: 240,
      clientHeight: 200,
    });
    let submittedPlaylistName = "";
    document.addEventListener("keydown", (e) => {
      if (e.key !== "p" || (!e.metaKey && !e.ctrlKey)) {
        return;
      }
      const { dialog, input, create } = addDialogWithForm();
      create.addEventListener("click", () => {
        submittedPlaylistName = input.value;
        dialog.remove();
      });
    });

    const pendingRows = ensureClipRowsLoaded(8, {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    const rows = await pendingRows;
    for (const row of rows) {
      const button = row.querySelector<HTMLButtonElement>(SELECT_CLIP_BUTTON_SELECTOR);
      if (!button) {
        throw new Error("test fixture must include Select clip button");
      }
      selectOnClick(button);
    }

    await multiSelectClips(rows);
    const dialog = await openAddToPlaylistDialogViaCmdP();
    await fillPlaylistNameAndCreate(dialog, "test-lazy-load-playlist");
    await waitForPlaylistDialogClose({
      isAborted: () => false,
      pollIntervalMs: 10,
      timeoutMs: 1000,
    });

    expect(rows).toHaveLength(8);
    expect(document.querySelectorAll(DESELECT_CLIP_BUTTON_SELECTOR)).toHaveLength(8);
    expect(submittedPlaylistName).toBe("test-lazy-load-playlist");
    expect(scrollPositions[0]).toBeGreaterThan(0);
    expect(scrollPositions[0]).toBeLessThan(40);
  });

  it("Given 末尾到達（ロードが増えない）で不足 When ensureClipRowsLoaded Then X/Y 件を含むメッセージで throw（silent slice 廃止）", async () => {
    // 3 row で末尾（scroll しても増えない）、count=5 を要求
    Array.from({ length: 3 }, () => addClipRow().row);
    // setupLazyLoader を使わない（scroll しても row が増えない）

    const pending = ensureClipRowsLoaded(5, {
      isAborted: () => false,
      pollIntervalMs: 50,
      loadSettleTimeoutMs: 200,
    });
    const expectation = expect(pending).rejects.toThrow(/3\/5/);
    await vi.advanceTimersByTimeAsync(1000);
    await expectation;
  });

  it("Given isAborted=true When ensureClipRowsLoaded Then 即 return する（throw しない）", async () => {
    // count には届かないが aborted=true なら throw せず現在の rows を返す
    Array.from({ length: 2 }, () => addClipRow().row);

    const pending = ensureClipRowsLoaded(10, { isAborted: () => true });
    await vi.runAllTimersAsync();
    // throw せず resolve する
    const result = await pending;
    expect(result).toHaveLength(2); // 不足でも abort なら throw しない
  });

  it("Given count 件揃った後 When ensureClipRowsLoaded Then scrollTop が 0 に戻る", async () => {
    // count=3 ちょうど揃っている → scrollTop を 0 に戻してから返す
    Array.from({ length: 3 }, () => addClipRow().row);
    const scroller = getOrCreateScroller();

    // scrollTop stub
    let _scrollTop = 0;
    Object.defineProperty(scroller, "scrollTop", {
      configurable: true,
      get: () => _scrollTop,
      set: (v: number) => {
        _scrollTop = v;
      },
    });
    // 初期状態を非ゼロにして戻ることを確認
    _scrollTop = 500;

    const pending = ensureClipRowsLoaded(3, { isAborted: () => false });
    await vi.runAllTimersAsync();
    await pending;

    expect(_scrollTop).toBe(0);
  });

  it("Given .clip-browser-list-scroller が存在しない When ensureClipRowsLoaded Then fail-loud で throw する", async () => {
    // scroller 不在 = Suno の clip list コンテナ自体が変わった（#881）
    await expect(ensureClipRowsLoaded(1, { isAborted: () => false })).rejects.toThrow(/clip row が見つかりません/);
  });

  it("Given scroller はあるが clip row が 0 件 When ensureClipRowsLoaded Then fail-loud で throw する（#881 維持）", async () => {
    // scroller は健在だが multi-select を持つ row が 1 件も無い = selector 廃止等の UI 変更
    getOrCreateScroller();

    await expect(ensureClipRowsLoaded(1, { isAborted: () => false })).rejects.toThrow(/clip row が見つかりません/);
  });
});

/**
 * Suno の選択挙動を jsdom で模す: click されたら aria-label を "Deselect clip" へ遷移させる。
 * 実機では Suno の React handler がこの遷移を行う。verification poll はこの遷移を観測する。
 */
function selectOnClick(btn: HTMLButtonElement): void {
  btn.addEventListener("click", () => {
    btn.setAttribute("aria-label", "Deselect clip");
  });
}

/** Select clip / Deselect clip いずれのボタンも持たない row（UI 変更で button が消えた状況）。 */
function addRowWithoutSelectButton(): HTMLElement {
  const row = document.createElement("div");
  markBbox(row, 200, 60);
  getOrCreateScroller().appendChild(row);
  return row;
}

describe("multiSelectClips: click + selected 状態への遷移を verify", () => {
  it("Given click で Deselect clip へ遷移する rows When multiSelectClips Then 各ボタンを 1 回ずつ click し resolve する", async () => {
    const a = addClipRow();
    const b = addClipRow();
    const clicks: string[] = [];
    a.btn.addEventListener("click", () => clicks.push("a"));
    b.btn.addEventListener("click", () => clicks.push("b"));
    selectOnClick(a.btn);
    selectOnClick(b.btn);

    await expect(multiSelectClips([a.row, b.row])).resolves.toBeUndefined();

    expect(clicks).toEqual(["a", "b"]);
  });

  it("Given 既に選択済み (aria-label=Deselect clip) の row When multiSelectClips Then click せず resolve する（冪等）", async () => {
    // 選択済みボタンは aria-label="Deselect clip"。click 不要で既に verify を満たす。
    const selected = addClipRow({ selectLabel: "Deselect clip" });
    const onClick = vi.fn();
    selected.btn.addEventListener("click", onClick);

    await expect(multiSelectClips([selected.row])).resolves.toBeUndefined();

    expect(onClick).not.toHaveBeenCalled();
  });

  it("Given .multi-select-button wrapper が無い Grid 風 row When multiSelectClips Then Select clip button を click して selected 遷移を verify する", async () => {
    const { rows, buttons } = addAlternateViewRows(2);
    const clicks: string[] = [];
    buttons[0].addEventListener("click", () => clicks.push("a"));
    buttons[1].addEventListener("click", () => clicks.push("b"));
    selectOnClick(buttons[0]);
    selectOnClick(buttons[1]);

    await expect(multiSelectClips(rows)).resolves.toBeUndefined();

    expect(clicks).toEqual(["a", "b"]);
  });

  it("Given Select/Deselect どちらのボタンも無い row When multiSelectClips Then selector 不在で即 throw する（silent skip 撤廃）", async () => {
    const row = addRowWithoutSelectButton();

    await expect(multiSelectClips([row])).rejects.toThrow(/Select clip button/);
  });

  it("Given 空の rows When multiSelectClips Then 内部不変条件違反として throw する（0>=0 の silent resolve 防止）", async () => {
    // ID ベース row loader が row 0 件で先に throw する前提だが、万一 [] で到達しても silent resolve させない。
    await expect(multiSelectClips([])).rejects.toThrow(/内部不変条件違反/);
  });

  describe("verification poll: deadline 超過で fail-loud", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("Given click しても aria-label が遷移しない row When multiSelectClips Then expected 1 / got 0 で throw する", async () => {
      // selectOnClick を付けない = Suno handler に届かず未選択のまま（本 issue の silent fail 相当）。
      const a = addClipRow();

      const pending = multiSelectClips([a.row]);
      const expectation = expect(pending).rejects.toThrow(/verification failed: expected 1 selected, got 0/);
      await vi.advanceTimersByTimeAsync(1100);
      await expectation;
    });

    it("Given 2 row 中 1 件のみ遷移する（部分成功） When multiSelectClips Then expected 2 / got 1 で throw する", async () => {
      const ok = addClipRow();
      const fail = addClipRow();
      selectOnClick(ok.btn); // ok だけ遷移、fail は未選択のまま

      const pending = multiSelectClips([ok.row, fail.row]);
      const expectation = expect(pending).rejects.toThrow(/verification failed: expected 2 selected, got 1/);
      await vi.advanceTimersByTimeAsync(1100);
      await expectation;
    });
  });
});

describe("openAddToPlaylistDialogViaCmdP: Cmd+P で Add to Playlist dialog を開く", () => {
  it("Given dialog 表示中 When 実行する Then key=p + meta/ctrl の keydown を document に dispatch する", async () => {
    addPlaylistDialog();
    const dispatch = vi.spyOn(document, "dispatchEvent");

    await openAddToPlaylistDialogViaCmdP();

    const keydown = dispatch.mock.calls.map((c) => c[0]).find((e) => e.type === "keydown") as KeyboardEvent | undefined;
    expect(keydown).toBeDefined();
    expect(keydown?.key).toBe("p");
    expect(keydown?.metaKey || keydown?.ctrlKey).toBe(true); // Mac=metaKey / 他=ctrlKey のいずれか
    expect(keydown?.bubbles).toBe(true);
  });

  it("Given Add to Playlist dialog が可視 When 実行する Then その dialog を返す", async () => {
    const dialog = addPlaylistDialog();

    await expect(openAddToPlaylistDialogViaCmdP()).resolves.toBe(dialog);
  });

  it("Given cookie dialog (aria-label=Privacy) が先に在り該当テキストを含む When 実行する Then 除外し real dialog を返す", async () => {
    // 除外フィルタが無ければ DOM 先頭の cookie dialog を誤って拾う配置にする（受け入れ条件 11）。
    addPlaylistDialog({ text: "Add to Playlist", ariaLabel: "Privacy Preference Center", id: "ot-sdk-container" });
    const real = addPlaylistDialog({ text: "Add to Playlist" });

    await expect(openAddToPlaylistDialogViaCmdP()).resolves.toBe(real);
  });

  it("Given id が ot- で始まる dialog が先に在る When 実行する Then 除外し real dialog を返す", async () => {
    addPlaylistDialog({ text: "Add to Playlist", id: "ot-sdk-container" });
    const real = addPlaylistDialog({ text: "Add to Playlist" });

    await expect(openAddToPlaylistDialogViaCmdP()).resolves.toBe(real);
  });

  it("Given Add to Playlist を含まない dialog が先に在る When 実行する Then 該当 dialog を返す", async () => {
    addPlaylistDialog({ text: "Saved to Library" });
    const real = addPlaylistDialog({ text: "Add to Playlist" });

    await expect(openAddToPlaylistDialogViaCmdP()).resolves.toBe(real);
  });

  it("Given 非可視の該当 dialog が先に在る When 実行する Then strict isVisible で除外し可視 dialog を返す", async () => {
    addPlaylistDialog({ text: "Add to Playlist", visible: false });
    const real = addPlaylistDialog({ text: "Add to Playlist" });

    await expect(openAddToPlaylistDialogViaCmdP()).resolves.toBe(real);
  });
});

describe("fillPlaylistNameAndCreate: 名前注入 + Create Playlist click", () => {
  it("Given dialog と name When 実行する Then dialog 内 input に name を注入する", async () => {
    const { dialog, input } = addDialogWithForm();

    await fillPlaylistNameAndCreate(dialog, "rjn-dawn-cloud-fold");

    expect(input.value).toBe("rjn-dawn-cloud-fold");
  });

  it("Given dialog と name When 実行する Then input イベントを発火する（React 互換注入）", async () => {
    const { dialog, input } = addDialogWithForm();
    const onInput = vi.fn();
    input.addEventListener("input", onInput);

    await fillPlaylistNameAndCreate(dialog, "x");

    expect(onInput).toHaveBeenCalled();
  });

  it("Given dialog When 実行する Then Create Playlist ボタンを 1 回 click する", async () => {
    const { dialog, create } = addDialogWithForm();
    const onClick = vi.fn();
    create.addEventListener("click", onClick);

    await fillPlaylistNameAndCreate(dialog, "x");

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("Given dialog When 実行する Then Create 以外のボタン (Liked Songs) は click しない", async () => {
    const { dialog, liked } = addDialogWithForm();
    const onClick = vi.fn();
    liked.addEventListener("click", onClick);

    await fillPlaylistNameAndCreate(dialog, "x");

    expect(onClick).not.toHaveBeenCalled();
  });

  it("Given dialog 外にも Playlist Name input が在る When 実行する Then dialog scope のみ注入し外側は触らない", async () => {
    const { dialog, input } = addDialogWithForm();
    const outside = document.createElement("input");
    outside.type = "text";
    outside.placeholder = "Playlist Name";
    markBbox(outside, 200, 30);
    document.body.appendChild(outside);

    await fillPlaylistNameAndCreate(dialog, "scoped");

    expect(input.value).toBe("scoped");
    expect(outside.value).toBe("");
  });
});

describe("waitForPlaylistDialogClose: dialog 消滅まで待機", () => {
  const FAST = { pollIntervalMs: 10, timeoutMs: 1000 } as const;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given dialog が初めから無い When 待機する Then 即 resolve する", async () => {
    const pending = waitForPlaylistDialogClose({ isAborted: () => false, ...FAST });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given dialog 表示中 → 途中で消滅 When 待機する Then 消滅検知で resolve する", async () => {
    const dialog = addPlaylistDialog();

    const pending = waitForPlaylistDialogClose({ isAborted: () => false, ...FAST });
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs * 3);
    expect(settled).toBe(false); // 表示中は resolve しない

    dialog.remove();
    await vi.advanceTimersByTimeAsync(FAST.pollIntervalMs);

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given dialog が残り続ける When deadline 超過 Then timeout throw する", async () => {
    addPlaylistDialog();

    const pending = waitForPlaylistDialogClose({ isAborted: () => false, ...FAST });
    const expectation = expect(pending).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(FAST.timeoutMs + FAST.pollIntervalMs + 50);
    await expectation;
  });

  it("Given dialog 表示中でも isAborted=true When 待機する Then 即 resolve する（throw しない、停止対応）", async () => {
    addPlaylistDialog();

    const pending = waitForPlaylistDialogClose({ isAborted: () => true, ...FAST });
    await vi.advanceTimersByTimeAsync(0);

    await expect(pending).resolves.toBeUndefined();
  });
});

/**
 * 既存 dialog に playlist row を追加する。実機 Suno DOM 構造そのまま:
 *   <div>  ← wrapper (role/aria 不可視、React onClick handler 想定)
 *     <img />
 *     <div class="ml-4 font-sans">{name}</div>  ← label
 *   </div>
 * wrapper を返す（テスト側で onClick handler を付けて bubbling 発火を観測する）。
 */
function appendPlaylistRow(dialog: HTMLElement, name: string): HTMLDivElement {
  const wrapper = document.createElement("div");
  const img = document.createElement("img");
  const label = document.createElement("div");
  label.className = "ml-4 font-sans";
  label.textContent = name;
  wrapper.append(img, label);
  dialog.appendChild(wrapper);
  return wrapper;
}

describe("clickPlaylistRowByName: dialog 内 list の新規 row を click して clip を追加", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given 同名 row が dialog 内に 1 件 When click Then label click が bubbling で wrapper の onClick を発火する", async () => {
    const dialog = addPlaylistDialog();
    appendPlaylistRow(dialog, "Liked Songs");
    const target = appendPlaylistRow(dialog, "rjn | dawn-cloud-fold");
    const onClick = vi.fn();
    // Suno は wrapper div に React onClick を載せる構造。label click → bubbling で発火することを確認。
    target.addEventListener("click", onClick);

    const pending = clickPlaylistRowByName(dialog, "rjn | dawn-cloud-fold");
    await vi.advanceTimersByTimeAsync(0);
    await pending;

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("Given 同名 row が複数並ぶ When click Then DOM 順で最後（= 最新作成）の wrapper だけが bubbling 発火する", async () => {
    // Suno は Create Playlist で同名 playlist の重複作成を許容するため、再実行時に古い + 新規の 2 row が並ぶ。
    const dialog = addPlaylistDialog();
    const old = appendPlaylistRow(dialog, "rjn | dawn-cloud-fold");
    const fresh = appendPlaylistRow(dialog, "rjn | dawn-cloud-fold");
    const oldClick = vi.fn();
    const freshClick = vi.fn();
    old.addEventListener("click", oldClick);
    fresh.addEventListener("click", freshClick);

    const pending = clickPlaylistRowByName(dialog, "rjn | dawn-cloud-fold");
    await vi.advanceTimersByTimeAsync(0);
    await pending;

    expect(oldClick).not.toHaveBeenCalled();
    expect(freshClick).toHaveBeenCalledTimes(1);
  });

  it("Given 前方一致だけする近似名 row When click Then 触らず完全一致のみ click する", async () => {
    // 例: "DF | X" と "DF | X2" の取り違え防止。
    const dialog = addPlaylistDialog();
    const longer = appendPlaylistRow(dialog, "DF | X2");
    const target = appendPlaylistRow(dialog, "DF | X");
    const longerClick = vi.fn();
    const targetClick = vi.fn();
    longer.addEventListener("click", longerClick);
    target.addEventListener("click", targetClick);

    const pending = clickPlaylistRowByName(dialog, "DF | X");
    await vi.advanceTimersByTimeAsync(0);
    await pending;

    expect(longerClick).not.toHaveBeenCalled();
    expect(targetClick).toHaveBeenCalledTimes(1);
  });

  it("Given row 不在 → 途中で出現 When click Then poll で待って出現後に click する", async () => {
    const dialog = addPlaylistDialog();

    const pending = clickPlaylistRowByName(dialog, "appears-later");
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(300);
    expect(settled).toBe(false);

    const target = appendPlaylistRow(dialog, "appears-later");
    const onClick = vi.fn();
    target.addEventListener("click", onClick);
    await vi.advanceTimersByTimeAsync(200);
    await pending;

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("Given row が timeout まで出現しない When click Then throw する（silent skip しない）", async () => {
    const dialog = addPlaylistDialog();

    const pending = clickPlaylistRowByName(dialog, "never-shows");
    const expectation = expect(pending).rejects.toThrow(/never-shows/);
    // timeout 5s + 余裕
    await vi.advanceTimersByTimeAsync(6000);
    await expectation;
  });

  it("Given dialog 外に同名 row が在る When click Then dialog scope のみ判定し外側は無視する", async () => {
    const dialog = addPlaylistDialog();

    // dialog 外の偽 row（同名）
    const outside = document.createElement("div");
    const outsideLabel = document.createElement("div");
    outsideLabel.className = "ml-4 font-sans";
    outsideLabel.textContent = "rjn | dawn-cloud-fold";
    outside.appendChild(outsideLabel);
    document.body.appendChild(outside);
    const outsideClick = vi.fn();
    outside.addEventListener("click", outsideClick);

    const target = appendPlaylistRow(dialog, "rjn | dawn-cloud-fold");
    const targetClick = vi.fn();
    target.addEventListener("click", targetClick);

    const pending = clickPlaylistRowByName(dialog, "rjn | dawn-cloud-fold");
    await vi.advanceTimersByTimeAsync(0);
    await pending;

    expect(outsideClick).not.toHaveBeenCalled();
    expect(targetClick).toHaveBeenCalledTimes(1);
  });

  it("Given 同 row 内の label を click した時 When event.target を観察 Then label そのものが target になる（wrapper を直接 click しない）", async () => {
    // 仕様の明文化: click 対象は label。React の合成イベントは bubbling phase で onClick を捕捉するため、
    // wrapper に handler があれば e.target は label でも handler は発火する。
    const dialog = addPlaylistDialog();
    const wrapper = appendPlaylistRow(dialog, "x");
    let observedTarget: EventTarget | null = null;
    wrapper.addEventListener("click", (e) => {
      observedTarget = e.target;
    });

    const pending = clickPlaylistRowByName(dialog, "x");
    await vi.advanceTimersByTimeAsync(0);
    await pending;

    expect(observedTarget).not.toBe(wrapper);
    expect((observedTarget as HTMLElement | null)?.textContent).toBe("x");
  });
});
