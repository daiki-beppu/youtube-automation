// 生成完了後の clip 一括 playlist 追加フロー (Cmd+P) に使う DOM 操作群 (#854)。
// order.md 実機 DOM 検証 (Step 0) で確定したセレクタ・操作仕様をこの 1 箇所に集約する
// （Suno の DOM は変わりうるため、壊れたら README / order.md を参照して更新する）。
// Style/Lyrics 注入系 (shared/dom.ts) とは責務が異なるため別モジュールに分ける。
import { setNativeValue, sleep } from "./dom";
import { isVisible } from "./visibility";

/**
 * clip-row（multi-select 対象）。生成中（streaming 等）も含めて拾う (#NEW)。
 *
 * Suno の挙動: multi-select は生成中の clip でも可能で、playlist 追加時に未完成な分は
 * 生成完了後に自動で playlist へ反映される。`data-clip-status="complete"` で絞ると、
 * 全 entries を generate キューに乗せた直後で「Suno が生成完了マークを付ける前」に
 * `addClipsToPlaylist` フェーズへ進んだ場合に 0 件選択となるため、status は問わない。
 */
export const CLIP_ROW_SELECTOR = '[data-testid="clip-row"]';
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
/** Create Playlist click 後に新規 playlist row が dialog 内 list に現れるのを待つ poll 間隔と上限 (ms)。 */
const PLAYLIST_ROW_APPEAR_POLL_MS = 100;
const PLAYLIST_ROW_APPEAR_TIMEOUT_MS = 5000;

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
 * clip-row を DOM 順（= 直近生成が先頭）で先頭から count 件取得する (#NEW)。
 * 生成中（streaming / queued 等）も含めて拾う — playlist 追加は未完了 clip でも可能で、
 * 生成完了後に自動で playlist へ反映されるため、status フィルタは設けない。
 * strict isVisible() で非可視 row を除外する（非マウント / display:none の残骸を弾く）。
 */
export function selectRecentClips(count: number): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(CLIP_ROW_SELECTOR))
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

/**
 * dialog 内 playlist row の label（playlist 名 text を持つ末端 `<div>`）を識別する CSS セレクタ。
 *
 * 実機 Suno dialog row 構造:
 *   <div>                                  ← row wrapper (React onClick handler、role/aria 不可視)
 *     <img />
 *     <div class="ml-4 font-sans">{name}</div>  ← この div を狙う
 *   </div>
 *
 * playlist 名は attribute (aria-label / data-*) ではなく **text content のみ** で識別される。
 * `ml-4 font-sans` は Tailwind utility だが現状で最も安定したシグナル（壊れたら #859 のように
 * 再 snippet 取得して定数を直す）。click は label に直接行い、bubbling で row wrapper の React
 * onClick handler に届く想定。
 */
export const PLAYLIST_ROW_LABEL_SELECTOR = "div.ml-4.font-sans";

/**
 * dialog 内の playlist 一覧から name と完全一致する label を DOM 順で全て返す (#NEW)。
 *
 * - text は **完全一致**（前方一致だと "DF | X" と "DF | X2" を取り違える）。
 * - 同名 row 複数時は呼び出し側が DOM 順で最後 = 最新を選ぶ想定で配列で返す
 *   （Suno は Create Playlist で重複作成を許容するため、テスト残骸の古い同名 row が並ぶことがある）。
 */
function findPlaylistRowsByName(
  dialog: HTMLElement,
  name: string,
): HTMLElement[] {
  return Array.from(
    dialog.querySelectorAll<HTMLElement>(PLAYLIST_ROW_LABEL_SELECTOR),
  ).filter((el) => (el.textContent ?? "").trim() === name);
}

/**
 * Create Playlist click 直後、dialog 内 list に新規 playlist row が現れるのを poll で待ち、
 * その row を click して選択中 clip を新規 playlist に追加する (#NEW)。
 *
 * Suno の Cmd+P dialog 仕様: 「Create Playlist」ボタンは新規 playlist を **空で作成するのみ**で、
 * 選択中 clip は追加されない。clip を入れるには、作成直後に dialog 内 list に表示される
 * 該当 playlist row を改めて click する必要がある。
 *
 * 同名 playlist が複数並ぶ場合（Suno は重複名を許容）、DOM 順で **最後の row**（= 直前に作成した最新）
 * を click する。これにより、前回テスト等で残っていた古い同名 playlist には触らない。
 *
 * 期限内に row が出現しなければ throw（silent skip しない）。
 */
export async function clickPlaylistRowByName(
  dialog: HTMLElement,
  name: string,
): Promise<void> {
  const deadline = Date.now() + PLAYLIST_ROW_APPEAR_TIMEOUT_MS;
  for (;;) {
    const rows = findPlaylistRowsByName(dialog, name);
    if (rows.length > 0) {
      rows[rows.length - 1].click();
      return;
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `Playlist "${name}" 行が dialog 内 list に出現しませんでした。Suno の UI 変更の可能性があります。`,
      );
    }
    await sleep(PLAYLIST_ROW_APPEAR_POLL_MS);
  }
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
