// 生成完了後の clip 一括 playlist 追加フロー (Cmd+P) に使う DOM 操作群 (#854)。
// order.md 実機 DOM 検証 (Step 0) で確定したセレクタ・操作仕様をこの 1 箇所に集約する
// （Suno の DOM は変わりうるため、壊れたら README / order.md を参照して更新する）。
// Style/Lyrics 注入系 (shared/dom.ts) とは責務が異なるため別モジュールに分ける。
import { setNativeValue, sleep } from "./dom";
import { isVisible } from "./visibility";

/** 生成完了済み clip-row（multi-select 対象）。`data-clip-status="complete"` で完了を識別 (#854)。 */
export const CLIP_ROW_COMPLETED_SELECTOR =
  '[data-testid="clip-row"][data-clip-status="complete"]';
/** 未選択の clip 選択ボタン。click すると aria-label が "Deselect clip" に切り替わる（= 冪等）。 */
export const SELECT_CLIP_BUTTON_SELECTOR =
  '.multi-select-button > button[aria-label="Select clip"]';
/** Add to Playlist dialog 内の playlist 名入力欄。 */
export const PLAYLIST_NAME_INPUT_SELECTOR =
  'input[placeholder="Playlist Name"]';

/** Add to Playlist dialog の見出しテキスト（React Aria auto-generated ID には依らず text content で判定）。 */
const PLAYLIST_DIALOG_HEADING = "Add to Playlist";
/** 新規 playlist 作成ボタンのラベル（case-insensitive substring match）。 */
const CREATE_PLAYLIST_BUTTON_TEXT = "create playlist";
/** Cmd+P 発火後に dialog 出現を待つ poll 間隔と上限 (ms)。 */
const DIALOG_OPEN_POLL_MS = 100;
const DIALOG_OPEN_TIMEOUT_MS = 5000;

/**
 * 可視な Add to Playlist dialog を 1 つ探す（OneTrust cookie consent dialog 除外フィルタ込み）。
 * 見つからなければ null。order.md: cookie dialog は id^="ot-" または aria-label が /privacy/i で除外する。
 */
function findPlaylistDialog(): HTMLElement | null {
  const dialogs = Array.from(
    document.querySelectorAll<HTMLElement>('[role="dialog"]'),
  );
  return (
    dialogs.find((dialog) => {
      if (!isVisible(dialog)) {
        return false;
      }
      if (dialog.id.startsWith("ot-")) {
        return false;
      }
      if (/privacy/i.test(dialog.getAttribute("aria-label") ?? "")) {
        return false;
      }
      return (dialog.textContent ?? "").includes(PLAYLIST_DIALOG_HEADING);
    }) ?? null
  );
}

/**
 * 完了済み clip-row を DOM 順（= 直近生成が先頭）で先頭から count 件取得する (#854)。
 * strict isVisible() で非可視 row を除外する（非マウント / display:none の残骸を弾く）。
 */
export function selectRecentCompletedClips(count: number): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(CLIP_ROW_COMPLETED_SELECTOR),
  )
    .filter(isVisible)
    .slice(0, count);
}

/**
 * 各 clip-row の未選択 Select clip ボタンを click して multi-select する (#854)。
 * 既に選択済み（aria-label="Deselect clip"）の row はセレクタにマッチせず click しない（冪等）。
 */
export async function multiSelectClips(rows: HTMLElement[]): Promise<void> {
  for (const row of rows) {
    row.querySelector<HTMLButtonElement>(SELECT_CLIP_BUTTON_SELECTOR)?.click();
  }
}

/**
 * Cmd+P (Mac=metaKey / 他=ctrlKey) を document に dispatch して Add to Playlist dialog を開き、
 * 出現した dialog を返す (#854)。cookie consent dialog は findPlaylistDialog の除外フィルタで拾わない。
 * 上限まで待っても出なければ throw（silent に続行しない）。
 */
export async function openAddToPlaylistDialogViaCmdP(): Promise<HTMLElement> {
  const isMac = navigator.platform.toLowerCase().includes("mac");
  document.dispatchEvent(
    new KeyboardEvent("keydown", {
      key: "p",
      metaKey: isMac,
      ctrlKey: !isMac,
      bubbles: true,
    }),
  );

  const deadline = Date.now() + DIALOG_OPEN_TIMEOUT_MS;
  for (;;) {
    const dialog = findPlaylistDialog();
    if (dialog) {
      return dialog;
    }
    if (Date.now() >= deadline) {
      throw new Error(
        "Add to Playlist dialog を検出できませんでした。Suno の UI 変更の可能性があります。",
      );
    }
    await sleep(DIALOG_OPEN_POLL_MS);
  }
}

/**
 * dialog 内の playlist 名入力欄へ name を注入し、Create Playlist ボタンを click する (#854)。
 * 入力欄 / ボタンが dialog scope に無ければ throw（silent skip しない）。注入は #807 の setNativeValue。
 */
export async function fillPlaylistNameAndCreate(
  dialog: HTMLElement,
  name: string,
): Promise<void> {
  const input = dialog.querySelector<HTMLInputElement>(
    PLAYLIST_NAME_INPUT_SELECTOR,
  );
  if (!input) {
    throw new Error("Playlist Name 入力欄が dialog 内に見つかりません。");
  }
  setNativeValue(input, name);

  const create = Array.from(
    dialog.querySelectorAll<HTMLButtonElement>("button"),
  ).find((btn) =>
    (btn.textContent ?? "").toLowerCase().includes(CREATE_PLAYLIST_BUTTON_TEXT),
  );
  if (!create) {
    throw new Error("Create Playlist ボタンが dialog 内に見つかりません。");
  }
  create.click();
}

export interface WaitForPlaylistDialogCloseOptions {
  /** 中断フラグ。true を返した時点で待機を打ち切り resolve する（throw しない、停止対応）。 */
  isAborted: () => boolean;
  pollIntervalMs: number;
  timeoutMs: number;
}

/**
 * Add to Playlist dialog の消滅（= playlist 作成完了）まで poll で待機する (#854)。
 *   - dialog が無くなったら resolve
 *   - isAborted() が true なら即 resolve（throw しない、停止対応）
 *   - deadline 超過で timeout throw
 */
export async function waitForPlaylistDialogClose(
  options: WaitForPlaylistDialogCloseOptions,
): Promise<void> {
  const deadline = Date.now() + options.timeoutMs;
  for (;;) {
    if (options.isAborted()) {
      return;
    }
    if (!findPlaylistDialog()) {
      return;
    }
    if (Date.now() >= deadline) {
      throw new Error("Add to Playlist dialog が閉じませんでした。");
    }
    await sleep(options.pollIntervalMs);
  }
}
