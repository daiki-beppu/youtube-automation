// @vitest-environment jsdom
//
// clip 一括 playlist 追加 (#854) の DOM 操作群 `shared/playlist-dom.ts` の回帰テスト。
// order.md 実機 DOM 検証 (Step 0) で確定したセレクタ・操作仕様を担保する:
//   - 完了 clip-row は `[data-testid="clip-row"][data-clip-status="complete"]` で識別
//   - multi-select は `.multi-select-button > button[aria-label="Select clip"]` を click（未選択のみマッチ）
//   - Cmd+P (Mac=metaKey / 他=ctrlKey) を document に dispatch して Add to Playlist dialog を開く
//   - dialog は text "Add to Playlist" を含む可視 `[role="dialog"]`。OneTrust cookie dialog
//     (id^="ot-" / aria-label が /privacy/i) は除外フィルタで拾わない
//   - dialog 内 `input[placeholder="Playlist Name"]` に setNativeValue、Create Playlist ボタンを click
//
// 契約 (draft が実装すべき public API、shared/playlist-dom.ts):
//   - CLIP_ROW_COMPLETED_SELECTOR: string = '[data-testid="clip-row"][data-clip-status="complete"]'
//   - SELECT_CLIP_BUTTON_SELECTOR: string = '.multi-select-button > button[aria-label="Select clip"]'
//   - PLAYLIST_NAME_INPUT_SELECTOR: string = 'input[placeholder="Playlist Name"]'
//   - selectRecentCompletedClips(count: number): HTMLElement[]
//   - multiSelectClips(rows: HTMLElement[]): Promise<void>
//   - openAddToPlaylistDialogViaCmdP(): Promise<HTMLElement>
//   - fillPlaylistNameAndCreate(dialog: HTMLElement, name: string): Promise<void>
//   - waitForPlaylistDialogClose(opts: { isAborted; pollIntervalMs; timeoutMs }): Promise<void>
//
// jsdom はレイアウトを行わず getBoundingClientRect が常に 0×0 を返すため、strict 可視判定
// 対象要素には markBbox (_helpers.ts) で bbox を擬似的に与える (dom.test.ts / queue.test.ts と同方針)。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CLIP_ROW_COMPLETED_SELECTOR,
  PLAYLIST_NAME_INPUT_SELECTOR,
  SELECT_CLIP_BUTTON_SELECTOR,
  clickPlaylistRowByName,
  fillPlaylistNameAndCreate,
  multiSelectClips,
  openAddToPlaylistDialogViaCmdP,
  selectRecentCompletedClips,
  waitForPlaylistDialogClose,
} from "../../shared/playlist-dom";
import { markBbox } from "./_helpers";

/**
 * clip-row を body に挿入する。
 *   - status: data-clip-status の値（"complete" で完了、"streaming" 等は未完了）
 *   - selectLabel: multi-select ボタンの aria-label（"Select clip"=未選択 / "Deselect clip"=選択済み）
 *   - visible=false: display:none + bbox 0×0（strict isVisible で除外される行）
 */
function addClipRow(opts: { status?: string; selectLabel?: string; visible?: boolean } = {}): {
  row: HTMLElement;
  btn: HTMLButtonElement;
} {
  const { status = "complete", selectLabel = "Select clip", visible = true } = opts;
  const row = document.createElement("div");
  row.setAttribute("data-testid", "clip-row");
  row.setAttribute("data-clip-status", status);

  const wrapper = document.createElement("div");
  wrapper.className = "multi-select-button";
  const btn = document.createElement("button");
  btn.setAttribute("aria-label", selectLabel);
  wrapper.appendChild(btn);
  row.appendChild(wrapper);
  document.body.appendChild(row);

  if (visible === false) {
    row.style.display = "none";
    markBbox(row, 0, 0);
  } else {
    markBbox(row, 200, 60);
  }
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
  it("Given CLIP_ROW_COMPLETED_SELECTOR When 読む Then 完了 clip-row の data 属性セレクタである", () => {
    expect(CLIP_ROW_COMPLETED_SELECTOR).toBe('[data-testid="clip-row"][data-clip-status="complete"]');
  });

  it("Given SELECT_CLIP_BUTTON_SELECTOR When 読む Then 未選択の Select clip ボタンセレクタである", () => {
    expect(SELECT_CLIP_BUTTON_SELECTOR).toBe('.multi-select-button > button[aria-label="Select clip"]');
  });

  it("Given PLAYLIST_NAME_INPUT_SELECTOR When 読む Then Playlist Name input セレクタである", () => {
    expect(PLAYLIST_NAME_INPUT_SELECTOR).toBe('input[placeholder="Playlist Name"]');
  });
});

describe("selectRecentCompletedClips: 完了 clip-row を先頭から count 件取得", () => {
  it("Given 完了 5 件 When count=40 Then 完了 5 件を DOM 順で返す", () => {
    const rows = Array.from({ length: 5 }, () => addClipRow().row);

    expect(selectRecentCompletedClips(40)).toEqual(rows);
  });

  it("Given 完了 3 + streaming 2 When 取得する Then complete のみ 3 件を返す（未完了を除外）", () => {
    const c1 = addClipRow({ status: "complete" }).row;
    addClipRow({ status: "streaming" });
    const c2 = addClipRow({ status: "complete" }).row;
    addClipRow({ status: "streaming" });
    const c3 = addClipRow({ status: "complete" }).row;

    expect(selectRecentCompletedClips(40)).toEqual([c1, c2, c3]);
  });

  it("Given 完了 5 件 When count=3 Then 先頭 3 件だけ返す", () => {
    const rows = Array.from({ length: 5 }, () => addClipRow().row);

    expect(selectRecentCompletedClips(3)).toEqual(rows.slice(0, 3));
  });

  it("Given 非可視の完了 row が混在 When 取得する Then strict isVisible で除外する", () => {
    const visible = addClipRow({ status: "complete" }).row;
    addClipRow({ status: "complete", visible: false });

    expect(selectRecentCompletedClips(40)).toEqual([visible]);
  });

  it("Given 完了 row が無い When 取得する Then 空配列を返す", () => {
    addClipRow({ status: "streaming" });

    expect(selectRecentCompletedClips(40)).toEqual([]);
  });
});

describe("multiSelectClips: 各 row の Select clip ボタンを click", () => {
  it("Given Select clip ボタンを持つ rows When multiSelectClips Then 各ボタンを 1 回ずつ click する", async () => {
    const a = addClipRow();
    const b = addClipRow();
    const clicks: string[] = [];
    a.btn.addEventListener("click", () => clicks.push("a"));
    b.btn.addEventListener("click", () => clicks.push("b"));

    await multiSelectClips([a.row, b.row]);

    expect(clicks).toEqual(["a", "b"]);
  });

  it("Given 既に選択済み (aria-label=Deselect clip) の row When multiSelectClips Then click しない（冪等）", async () => {
    // 選択済みボタンは aria-label="Deselect clip" になり Select clip セレクタにマッチしない。
    const selected = addClipRow({ selectLabel: "Deselect clip" });
    const onClick = vi.fn();
    selected.btn.addEventListener("click", onClick);

    await multiSelectClips([selected.row]);

    expect(onClick).not.toHaveBeenCalled();
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
 * 既存 dialog に playlist row（実機 DOM: `<button|role=button> <img/> <div class="ml-4 font-sans">{name}</div> </>`）
 * を追加する。append=true で「Create Playlist click 直後に list へ新規 row が現れた」状態を再現する。
 */
function appendPlaylistRow(
  dialog: HTMLElement,
  name: string,
  opts: { useRoleButton?: boolean } = {},
): HTMLButtonElement | HTMLDivElement {
  const wrapper = opts.useRoleButton ? document.createElement("div") : document.createElement("button");
  if (opts.useRoleButton) {
    wrapper.setAttribute("role", "button");
  }
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

  it("Given 同名 row が dialog 内に 1 件 When click Then その button wrapper を click する", async () => {
    const dialog = addPlaylistDialog();
    appendPlaylistRow(dialog, "Liked Songs");
    const target = appendPlaylistRow(dialog, "rjn | dawn-cloud-fold");
    const onClick = vi.fn();
    target.addEventListener("click", onClick);

    const pending = clickPlaylistRowByName(dialog, "rjn | dawn-cloud-fold");
    await vi.advanceTimersByTimeAsync(0);
    await pending;

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("Given 同名 row が複数並ぶ When click Then DOM 順で最後（= 最新作成）を click する", async () => {
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
    appendPlaylistRow(dialog, "Liked Songs");

    // dialog 外の偽 row（同名）
    const outside = document.createElement("button");
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

  it("Given 親 wrapper が role=button (div) の row When click Then その wrapper を click する", async () => {
    const dialog = addPlaylistDialog();
    const target = appendPlaylistRow(dialog, "role-button-row", {
      useRoleButton: true,
    });
    const onClick = vi.fn();
    target.addEventListener("click", onClick);

    const pending = clickPlaylistRowByName(dialog, "role-button-row");
    await vi.advanceTimersByTimeAsync(0);
    await pending;

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
