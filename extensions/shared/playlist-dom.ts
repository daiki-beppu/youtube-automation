// 生成完了後の clip 一括 playlist 追加フロー (Cmd+P) に使う DOM 操作群 (#854)。
// order.md 実機 DOM 検証 (Step 0) で確定したセレクタ・操作仕様をこの 1 箇所に集約する
// （Suno の DOM は変わりうるため、壊れたら README / order.md を参照して更新する）。
// Style/Lyrics 注入系 (shared/dom.ts) とは責務が異なるため別モジュールに分ける。
import { setNativeValue, sleep } from "./dom";
import { isVisible } from "./visibility";

/**
 * clip list のスクロールコンテナ (#881)。配下に（Emotion の中間ラッパ div を挟んで）
 * per-clip 要素が並び、各 clip が `.multi-select-button` を 1 つ内包する。
 *
 * Suno は `data-testid="clip-row"` を完全廃止したため、attribute 識別を捨て、
 * 安定して残っているこのコンテナ class + 配下の `.multi-select-button` 構造で row を判定する
 * （Emotion の hash 揺れする class には依存しない）。壊れたら order.md / README を参照して更新する。
 */
export const CLIP_LIST_SCROLLER_SELECTOR = ".clip-browser-list-scroller";
/** 各 clip が 1 つ内包する multi-select ボタンのラッパ。clip row の構造シグナル兼 row 導出の基点 (#881)。 */
const MULTI_SELECT_BUTTON_SELECTOR = ".multi-select-button";
const SELECT_CLIP_BUTTON_ANY_SELECTOR = 'button[aria-label="Select clip"]';
const DESELECT_CLIP_BUTTON_ANY_SELECTOR = 'button[aria-label="Deselect clip"]';
/** 未選択の clip 選択ボタン。click すると aria-label が "Deselect clip" に切り替わる（= 冪等）。 */
export const SELECT_CLIP_BUTTON_SELECTOR = `${MULTI_SELECT_BUTTON_SELECTOR} > button[aria-label="Select clip"]`;
/** 選択済みの clip ボタン。click 後にこの aria-label へ遷移したことを verify するシグナル（SELECT_CLIP_BUTTON_SELECTOR と対称）。 */
export const DESELECT_CLIP_BUTTON_SELECTOR = `${MULTI_SELECT_BUTTON_SELECTOR} > button[aria-label="Deselect clip"]`;
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
/** multi-select click 後、対象 row が selected 状態（aria-label="Deselect clip"）へ遷移したかを verify する poll 間隔と上限 (ms)。 */
const CLIP_SELECT_VERIFY_POLL_MS = 50;
const CLIP_SELECT_VERIFY_TIMEOUT_MS = 1000;
/** verify deadline を row 数でスケールする際の 1 row あたりの猶予 (ms/row、#924)。 */
const CLIP_SELECT_VERIFY_MS_PER_ROW = 50;
/** clip list の遅延ロードを bottom jump に依存させないための段階スクロール量。 */
const CLIP_LIST_LOAD_SCROLL_STEP_PX = 600;
type ClipListScrollIntent = "probe-intermediate" | "settle-bottom";

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

/** clip row が DOM 上に存在しないことが確定したときの fail-loud メッセージ (#881)。 */
const CLIP_ROW_NOT_FOUND_MESSAGE =
  "clip row が見つかりません。Suno の UI 変更の可能性があります。";

function resolveClipRowFromSelectButton(
  button: HTMLElement,
): HTMLElement | null {
  const multiSelectRow = button.closest(
    MULTI_SELECT_BUTTON_SELECTOR,
  )?.parentElement;
  if (multiSelectRow) {
    return multiSelectRow;
  }
  return button.closest<HTMLElement>("article");
}

function isScrollableClipContainer(element: HTMLElement): boolean {
  if (element === document.body || element === document.documentElement) {
    return false;
  }
  const overflowY = getComputedStyle(element).overflowY;
  if (
    overflowY === "auto" ||
    overflowY === "scroll" ||
    overflowY === "overlay"
  ) {
    return true;
  }
  return element.scrollHeight > element.clientHeight;
}

function resolveScrollableAncestor(element: HTMLElement): HTMLElement | null {
  let current = element.parentElement;
  while (current) {
    if (isScrollableClipContainer(current)) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

function resolveClipListScroller(): HTMLElement | null {
  const explicit = document.querySelector<HTMLElement>(
    CLIP_LIST_SCROLLER_SELECTOR,
  );
  if (explicit && collectClipRowsFromSelectButtons(explicit).length > 0) {
    return explicit;
  }

  const buttons = document.querySelectorAll<HTMLElement>(
    `${SELECT_CLIP_BUTTON_ANY_SELECTOR}, ${DESELECT_CLIP_BUTTON_ANY_SELECTOR}`,
  );
  for (const button of buttons) {
    const row = resolveClipRowFromSelectButton(button);
    if (!row || !isVisible(row)) {
      continue;
    }
    const scroller = resolveScrollableAncestor(row);
    if (scroller && collectClipRowsFromSelectButtons(scroller).length > 0) {
      return scroller;
    }
  }
  return explicit;
}

function collectClipRowsFromSelectButtons(root: ParentNode): HTMLElement[] {
  const buttons = root.querySelectorAll<HTMLElement>(
    `${SELECT_CLIP_BUTTON_ANY_SELECTOR}, ${DESELECT_CLIP_BUTTON_ANY_SELECTOR}`,
  );
  const seen = new Set<HTMLElement>();
  const rows: HTMLElement[] = [];
  for (const button of buttons) {
    const row = resolveClipRowFromSelectButton(button);
    if (!row || seen.has(row)) {
      continue;
    }
    seen.add(row);
    if (isVisible(row)) {
      rows.push(row);
    }
  }
  return rows;
}

/**
 * scroller 配下のロード済み clip row を DOM 順（= 直近生成が先頭）で全件収集する内部ヘルパ。
 *
 * row は **multi-select ボタンを基点に per-clip 粒度で導出する**。
 * `.clip-browser-list-scroller` 配下の Select/Deselect ボタンを全件取得し、各ボタンの
 * `closest('.multi-select-button')?.parentElement`（= その clip の row 要素）を DOM 順で
 * 重複排除しながら収集する。生成中 / 完了は区別しない（playlist 追加は未完了 clip でも可能で、
 * 生成完了後に自動反映されるため status は問わない）。strict isVisible() で非可視 row を除外する。
 *
 * `:scope > div`（scroller 直下 div を row とする素朴な実装）は採らない: 実機の
 * `scroller > 中間ラッパ div > per-clip div ...`（order.md L26）構造下では中間ラッパ 1 件に
 * 潰れ、全 clip が 1 row に collapse して `multiSelectClips` が先頭 1 ボタンしか click できない。
 * ボタン基点の祖先導出はネスト深度・Emotion hash 非依存で per-clip 粒度を保証する。
 *
 * 0 件の場合は `CLIP_ROW_NOT_FOUND_MESSAGE` で throw（fail-loud、#881 維持）。
 */
function collectLoadedClipRows(scroller: HTMLElement): HTMLElement[] {
  const rows = collectClipRowsFromSelectButtons(scroller);
  if (rows.length === 0) {
    throw new Error(CLIP_ROW_NOT_FOUND_MESSAGE);
  }
  return rows;
}

function scrollClipListTowardBottom(
  scroller: HTMLElement,
  intent: ClipListScrollIntent,
): void {
  const maxScrollTop = Math.max(
    0,
    scroller.scrollHeight - scroller.clientHeight,
  );
  const currentScrollTop = Math.max(
    0,
    Math.min(scroller.scrollTop, maxScrollTop),
  );
  const step = Math.max(scroller.clientHeight, CLIP_LIST_LOAD_SCROLL_STEP_PX);
  const nextScrollTop = currentScrollTop + step;
  if (maxScrollTop === 0) {
    scroller.scrollTop = 0;
  } else if (nextScrollTop >= maxScrollTop && intent === "probe-intermediate") {
    scroller.scrollTop =
      currentScrollTop + (maxScrollTop - currentScrollTop) / 2;
  } else if (nextScrollTop >= maxScrollTop) {
    scroller.scrollTop = maxScrollTop;
  } else {
    scroller.scrollTop = nextScrollTop;
  }
  scroller.dispatchEvent(new Event("scroll"));
}

function restoreClipListHead(scroller: HTMLElement): void {
  scroller.scrollTop = 0;
  scroller.dispatchEvent(new Event("scroll"));
}

export interface EnsureClipRowsLoadedOptions {
  /** 中断フラグ。true で即 return（throw しない。呼び出し側が aborted を再チェック）。 */
  isAborted: () => boolean;
  /** ロード判定の poll 間隔 (ms)。既定 100。 */
  pollIntervalMs?: number;
  /** スクロール後、追加 row のロードを待つ上限 (ms)。既定 3000。 */
  loadSettleTimeoutMs?: number;
}

/**
 * 遅延ロードの clip list を底方向へ段階スクロールし、count 件の row がロードされるまで進める (#924)。
 * 戻り値はロード済み row の先頭 count 件（DOM 順 = 直近生成が先頭）。
 * リスト末尾（追加ロードが止まる）まで進めても不足する場合は
 * 「X/Y 件」を含むメッセージで fail-loud throw する（従来の silent slice を廃止）。
 *
 * 現在の Suno では bottom jump がロード条件から外れることがあるため、まず中間位置の
 * scroll event で追加ロードを促す。増えなければ同じ待機内で末尾到達も試し、
 * 中間位置だけに反応する loader と末尾だけに反応する loader の両方を扱う。
 *
 * fail-loud (#881): コンテナ不在または row 0 件は即 throw する（空配列を返さない）。
 * 追加ロードが止まった（リスト末尾）のに count に届かない場合も fail-loud throw する
 * （silent slice を廃止し、追加漏れを検出境界で即顕在化させる）。
 */
export async function ensureClipRowsLoaded(
  count: number,
  options: EnsureClipRowsLoadedOptions,
): Promise<HTMLElement[]> {
  const {
    isAborted,
    pollIntervalMs = 100,
    loadSettleTimeoutMs = 3000,
  } = options;

  const scroller = resolveClipListScroller();
  if (!scroller) {
    throw new Error(CLIP_ROW_NOT_FOUND_MESSAGE);
  }

  // 初回 row 収集: 0 件なら fail-loud throw（#881 維持）
  let rows = collectLoadedClipRows(scroller);

  for (;;) {
    // 中断: 現時点の先頭 count 件（不足していても）を返して即終了
    if (isAborted()) {
      return rows.slice(0, count);
    }

    // 十分な row がロードされた: scrollTop を 0 に戻して先頭 count 件を返す
    // （multi-select や Cmd+P 操作を初期表示位置で行うため、スクロールを元に戻す）
    if (rows.length >= count) {
      restoreClipListHead(scroller);
      return rows.slice(0, count);
    }

    const prevCount = rows.length;
    scrollClipListTowardBottom(scroller, "probe-intermediate");

    // 追加 row のロードを poll で待つ
    const settleDeadline = Date.now() + loadSettleTimeoutMs;
    for (;;) {
      await sleep(pollIntervalMs);
      if (isAborted()) {
        // 中断: ロード待ち中でも即終了
        rows = collectLoadedClipRows(scroller);
        return rows.slice(0, count);
      }
      rows = collectLoadedClipRows(scroller);
      if (rows.length > prevCount) {
        // 追加ロードを検出: 外側ループに戻って再評価
        break;
      }
      if (Date.now() >= settleDeadline) {
        // リスト末尾到達（追加ロードが止まった）のに不足
        throw new Error(
          `clip row が ${rows.length}/${count} 件しかロードできませんでした。生成済み clip が不足しているか、Suno の UI 変更の可能性があります。`,
        );
      }
      scrollClipListTowardBottom(scroller, "settle-bottom");
    }
  }
}

/**
 * 各 clip-row の未選択 Select clip ボタンを click し、対象 row 全てが selected 状態
 * （aria-label="Deselect clip"）へ遷移したことを poll で verify する (#854, #878)。
 *
 * silent fail 撤廃 (#878): 旧実装は `querySelector(...)?.click()` で
 *   - Select clip ボタン不在 → silent skip
 *   - click が Suno handler に届かず未選択のまま → 検知なし
 * を許し、0 件選択でも void resolve していた。これが後段の Add to Playlist dialog 検出
 * timeout という代理症状で初めて顕在化していたため、選択側で fail-loud にする。
 *
 * - rows が空配列なら内部不変条件違反として即 throw（呼び出し側で row 0 件は ensureClipRowsLoaded
 *   （内部の collectLoadedClipRows）が先に fail-loud throw する前提。万一 0 件で到達したら
 *   `0 >= 0` で silent resolve させない）(#881, #924)。
 * - 既に選択済み（Deselect clip 在）の row は idempotent に skip（click しない）。
 * - Select clip ボタンが無く、かつ未選択（Deselect も無い）row は UI 変更とみなし即 throw。
 * - 全 click 後、対象 row が deadline 内に Deselect clip へ遷移しなければ throw。
 */
export async function multiSelectClips(rows: HTMLElement[]): Promise<void> {
  if (rows.length === 0) {
    throw new Error(
      "multiSelectClips に空の rows が渡されました（内部不変条件違反）。",
    );
  }
  for (const row of rows) {
    if (row.querySelector(DESELECT_CLIP_BUTTON_ANY_SELECTOR)) {
      continue;
    }
    const button = row.querySelector<HTMLButtonElement>(
      SELECT_CLIP_BUTTON_ANY_SELECTOR,
    );
    if (!button) {
      throw new Error(
        "Select clip button が見つかりません。Suno の UI 変更の可能性があります。",
      );
    }
    button.click();
  }

  // 大規模 collection（60-80 件など）では 1 秒では全 row の selected 遷移が間に合わないリスクがある。
  // row 数でスケールし、最低でも CLIP_SELECT_VERIFY_TIMEOUT_MS を確保する（#924）。
  const deadline =
    Date.now() +
    Math.max(
      CLIP_SELECT_VERIFY_TIMEOUT_MS,
      rows.length * CLIP_SELECT_VERIFY_MS_PER_ROW,
    );
  for (;;) {
    const selected = rows.filter((row) =>
      row.querySelector(DESELECT_CLIP_BUTTON_ANY_SELECTOR),
    ).length;
    if (selected >= rows.length) {
      return;
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `Clip multi-select verification failed: expected ${rows.length} selected, got ${selected}`,
      );
    }
    await sleep(CLIP_SELECT_VERIFY_POLL_MS);
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
        "Add to Playlist dialog を検出できませんでした。clip が selected 状態であることを確認してください。Suno の UI 変更の可能性があります。",
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
