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
const CLIP_ROW_SONG_ID_DATA_KEY = "songId";
const CLIP_ROW_CLIP_ID_DATA_KEY = "clipId";
const CLIP_ROW_SONG_LINK_SELECTOR = 'a[href*="/song/"]';
const SONG_HREF_ID_RE = /\/song\/([^/?#]+)/;
/**
 * Suno CDN 画像 URL から clip UUID を抽出する正規表現。
 * src/data-src は `cdn2.suno.ai/image_<UUID>.jpeg` or `image_large_<UUID>.jpeg` 形式。
 * data-songId / data-clipId / song リンクが全廃された新 DOM での唯一の clip ID ソース。
 */
const CLIP_IMAGE_UUID_RE =
  /image_(?:large_)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i;
const GRID_CARD_MAX_ANCESTOR_DEPTH = 10;
const GRID_CARD_MIN_SIBLINGS = 2;
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
/** verify deadline を row 数でスケールする際の 1 row あたりの猶予 (ms/row、#924 → #1050 で 50→100 に倍増)。 */
const CLIP_SELECT_VERIFY_MS_PER_ROW = 100;
/** Cmd+P 発火の最大リトライ回数 (#1050)。dialog が開かない場合に再発火する。 */
const CMD_P_MAX_RETRIES = 3;
/** clip row 内の曲タイトル表示要素。実機 DOM 調査 (2026-06-23) で確認済み。 */
const CLIP_ROW_TITLE_SELECTOR = 'span[role="button"][aria-label^="Play "]';
/** clip list の遅延ロードを bottom jump に依存させないための段階スクロール量。 */
const CLIP_LIST_LOAD_SCROLL_STEP_PX = 600;
/** scrollAndMultiSelectByIds: 各スクロールステップ後に仮想 DOM が描画されるのを待つ猶予 (ms)。 */
const VIRTUAL_SCROLL_RENDER_WAIT_MS = 200;
/** scrollAndMultiSelectByIds: 全スクロール後に未発見 ID がある場合の再スキャン上限回数。 */
const VIRTUAL_SCROLL_RETRY_PASSES = 2;
/** loadSettleTimeoutMs のデフォルト基準値 (ms)。 */
const SETTLE_BASE_MS = 3000;
/** loadSettleTimeoutMs を targetIds.length でスケールする係数 (ms/clip)。 */
const SETTLE_PER_CLIP_MS = 200;
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

/**
 * 要素が clip card のコンテンツ（画像やリンク）を含むか判定する。
 * bare wrapper（.multi-select-button のみを内包する中間 div）と
 * 実 clip card を区別するための構造シグナル。Emotion class には依存しない。
 */
function hasClipContent(el: HTMLElement): boolean {
  return (
    el.querySelector("img") !== null || el.querySelector("a[href]") !== null
  );
}

function resolveClipRowFromSelectButton(
  button: HTMLElement,
): HTMLElement | null {
  const multiSelectWrapper = button.closest(MULTI_SELECT_BUTTON_SELECTOR);
  if (!multiSelectWrapper) {
    const articleRow = button.closest<HTMLElement>("article");
    if (articleRow) {
      return articleRow;
    }
    return resolveGridCardFromSelectButton(button);
  }
  const parent = multiSelectWrapper.parentElement;
  if (!parent) {
    return button.closest<HTMLElement>("article");
  }
  // 旧 DOM: parent が clip card 本体（img / a[href] を含む）→ そのまま返す。
  // 新 DOM: parent が bare wrapper（.multi-select-button のみ）→ 1 段上の clip card を返す。
  if (hasClipContent(parent)) {
    return parent;
  }
  const grandparent = parent.parentElement;
  if (grandparent) {
    return grandparent;
  }
  return parent;
}

function resolveGridCardFromSelectButton(
  button: HTMLElement,
): HTMLElement | null {
  let candidate: HTMLElement | null = button.parentElement;
  for (
    let depth = 0;
    candidate && depth < GRID_CARD_MAX_ANCESTOR_DEPTH;
    depth++
  ) {
    const parent = candidate.parentElement;
    if (!parent) {
      break;
    }
    const siblings = Array.from(parent.children);
    if (
      siblings.length >= GRID_CARD_MIN_SIBLINGS &&
      siblings.every(
        (sibling) =>
          sibling.querySelectorAll(SELECT_CLIP_BUTTON_ANY_SELECTOR).length +
            sibling.querySelectorAll(DESELECT_CLIP_BUTTON_ANY_SELECTOR)
              .length ===
          1,
      )
    ) {
      return candidate;
    }
    candidate = parent;
  }
  return null;
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

function extractSongIdFromHref(href: string): string | null {
  const match = SONG_HREF_ID_RE.exec(href);
  return match ? match[1] : null;
}

function extractClipIdFromImageUrl(url: string): string | null {
  const match = CLIP_IMAGE_UUID_RE.exec(url);
  return match ? match[1] : null;
}

function collectClipRowIds(row: HTMLElement): Set<string> {
  const ids = new Set<string>();
  const songId = row.dataset[CLIP_ROW_SONG_ID_DATA_KEY];
  const clipId = row.dataset[CLIP_ROW_CLIP_ID_DATA_KEY];
  if (songId) {
    ids.add(songId);
  }
  if (clipId) {
    ids.add(clipId);
  }
  for (const link of row.querySelectorAll<HTMLAnchorElement>(
    CLIP_ROW_SONG_LINK_SELECTOR,
  )) {
    const id = extractSongIdFromHref(link.href);
    if (id) {
      ids.add(id);
    }
  }
  // 既存経路で ID が見つからなかった場合、画像 URL から UUID を抽出する。
  // Suno が data-songId / data-clipId / song リンクを全廃した新 DOM での fallback。
  if (ids.size === 0) {
    for (const img of row.querySelectorAll<HTMLImageElement>("img")) {
      const uuid =
        extractClipIdFromImageUrl(img.src) ??
        extractClipIdFromImageUrl(img.dataset.src ?? "");
      if (uuid) {
        ids.add(uuid);
        break;
      }
    }
  }
  return ids;
}

export function collectClipRowTitle(row: HTMLElement): string | null {
  return (
    row.querySelector(CLIP_ROW_TITLE_SELECTOR)?.textContent?.trim() || null
  );
}

function findRowsByClipIds(
  rows: HTMLElement[],
  targetIds: string[],
  titleFallbackMap?: Map<string, string>,
): HTMLElement[] {
  const rowById = new Map<string, HTMLElement>();
  for (const row of rows) {
    for (const id of collectClipRowIds(row)) {
      if (!rowById.has(id)) {
        rowById.set(id, row);
      }
    }
  }

  const foundRows: HTMLElement[] = [];
  const seenRows = new Set<HTMLElement>();
  const unmatchedIds: string[] = [];

  for (const id of targetIds) {
    const row = rowById.get(id);
    if (row && !seenRows.has(row)) {
      foundRows.push(row);
      seenRows.add(row);
    } else if (!row) {
      unmatchedIds.push(id);
    }
  }

  if (
    unmatchedIds.length > 0 &&
    titleFallbackMap &&
    titleFallbackMap.size > 0
  ) {
    const rowsByTitle = new Map<string, HTMLElement[]>();
    for (const row of rows) {
      const title = collectClipRowTitle(row);
      if (title) {
        const list = rowsByTitle.get(title) ?? [];
        list.push(row);
        rowsByTitle.set(title, list);
      }
    }
    for (const id of unmatchedIds) {
      const title = titleFallbackMap.get(id);
      if (!title) continue;
      const candidates = rowsByTitle.get(title);
      if (!candidates) continue;
      for (const row of candidates) {
        if (!seenRows.has(row)) {
          foundRows.push(row);
          seenRows.add(row);
          break;
        }
      }
    }
  }

  return foundRows;
}

function listMissingClipIds(
  rows: HTMLElement[],
  targetIds: string[],
  titleFallbackMap?: Map<string, string>,
): string[] {
  const foundIds = new Set<string>();
  for (const row of rows) {
    for (const id of collectClipRowIds(row)) {
      foundIds.add(id);
    }
  }
  const missing = targetIds.filter((id) => !foundIds.has(id));
  if (
    missing.length === 0 ||
    !titleFallbackMap ||
    titleFallbackMap.size === 0
  ) {
    return missing;
  }
  const titleSet = new Set<string>();
  for (const row of rows) {
    const title = collectClipRowTitle(row);
    if (title) titleSet.add(title);
  }
  return missing.filter((id) => {
    const title = titleFallbackMap.get(id);
    return !title || !titleSet.has(title);
  });
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
  /** スクロール後、追加 row のロードを待つ上限 (ms)。既定は targetIds.length でスケール。 */
  loadSettleTimeoutMs?: number;
  /** clip ID → 曲タイトルの Map。ID マッチ失敗時にタイトルで row を逆引きするフォールバック。 */
  titleFallbackMap?: Map<string, string>;
}

export async function ensureClipRowsLoadedByIds(
  targetIds: string[],
  options: EnsureClipRowsLoadedOptions,
): Promise<HTMLElement[]> {
  const uniqueTargetIds = Array.from(new Set(targetIds));
  if (uniqueTargetIds.length === 0) {
    throw new Error("playlist 対象の clip ID がありません。");
  }

  const {
    isAborted,
    pollIntervalMs = 100,
    loadSettleTimeoutMs = SETTLE_BASE_MS +
      uniqueTargetIds.length * SETTLE_PER_CLIP_MS,
    titleFallbackMap,
  } = options;

  const scroller = document.querySelector<HTMLElement>(
    CLIP_LIST_SCROLLER_SELECTOR,
  );
  if (!scroller) {
    throw new Error(CLIP_ROW_NOT_FOUND_MESSAGE);
  }

  const allFound = (r: HTMLElement[]) =>
    listMissingClipIds(r, uniqueTargetIds, titleFallbackMap).length === 0;

  let rows = collectLoadedClipRows(scroller);

  for (;;) {
    const foundRows = findRowsByClipIds(
      rows,
      uniqueTargetIds,
      titleFallbackMap,
    );
    if (isAborted()) {
      return foundRows;
    }
    if (allFound(rows)) {
      restoreClipListHead(scroller);
      return foundRows;
    }

    const prevCount = rows.length;
    scrollClipListTowardBottom(scroller, "probe-intermediate");

    const settleDeadline = Date.now() + loadSettleTimeoutMs;
    for (;;) {
      await sleep(pollIntervalMs);
      rows = collectLoadedClipRows(scroller);
      const nextFoundRows = findRowsByClipIds(
        rows,
        uniqueTargetIds,
        titleFallbackMap,
      );
      if (isAborted()) {
        return nextFoundRows;
      }
      if (allFound(rows)) {
        break;
      }
      if (rows.length > prevCount) {
        break;
      }
      if (Date.now() >= settleDeadline) {
        const missing = listMissingClipIds(
          rows,
          uniqueTargetIds,
          titleFallbackMap,
        ).join(", ");
        throw new Error(
          `playlist 対象 clip row が見つかりませんでした。missing clip ID: ${missing}`,
        );
      }
      scrollClipListTowardBottom(scroller, "settle-bottom");
    }
  }
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
 * - rows が空配列なら内部不変条件違反として即 throw（呼び出し側で row 0 件は
 *   row loader が先に fail-loud throw する前提。万一 0 件で到達したら silent
 *   resolve させない）(#881, #924)。
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

export interface ScrollAndMultiSelectOptions {
  isAborted: () => boolean;
  titleFallbackMap?: Map<string, string>;
  renderWaitMs?: number;
}

/**
 * 仮想スクロール対応の clip multi-select (#1251)。
 *
 * Suno のクリップリストは仮想スクロールを使い、ビューポート内の 15-25 行だけ DOM に存在する。
 * 旧 `ensureClipRowsLoadedByIds` + `multiSelectClips` は全 target row が同時に DOM に揃う
 * ことを前提としていたが、仮想化ではそれが不可能。
 *
 * この関数はリストをトップからボトムまでスクロールしながら、各ビューポートで target ID に
 * マッチする row を発見次第 Select click する。Suno は選択状態を内部 state で保持するため、
 * row がスクロールアウトしても選択は維持される。
 */
export async function scrollAndMultiSelectByIds(
  targetIds: string[],
  options: ScrollAndMultiSelectOptions,
): Promise<number> {
  const uniqueTargetIds = new Set(targetIds);
  if (uniqueTargetIds.size === 0) {
    throw new Error("playlist 対象の clip ID がありません。");
  }

  const {
    isAborted,
    titleFallbackMap,
    renderWaitMs = VIRTUAL_SCROLL_RENDER_WAIT_MS,
  } = options;

  const scroller = document.querySelector<HTMLElement>(
    CLIP_LIST_SCROLLER_SELECTOR,
  );
  if (!scroller) {
    throw new Error(CLIP_ROW_NOT_FOUND_MESSAGE);
  }

  const foundIds = new Set<string>();
  const titleMatchedIds = new Set<string>();
  const titleMatchedRows = new WeakSet<HTMLElement>();

  async function selectMatchingRows(): Promise<void> {
    const buttons = scroller!.querySelectorAll<HTMLElement>(
      `${SELECT_CLIP_BUTTON_ANY_SELECTOR}, ${DESELECT_CLIP_BUTTON_ANY_SELECTOR}`,
    );
    const seen = new Set<HTMLElement>();
    for (const button of buttons) {
      const row = resolveClipRowFromSelectButton(button);
      if (!row || seen.has(row) || !isVisible(row)) continue;
      seen.add(row);

      const rowIds = collectClipRowIds(row);
      let matched = false;
      const matchedIds: string[] = [];
      let titleMatchedId: string | undefined;
      for (const id of rowIds) {
        if (uniqueTargetIds.has(id)) {
          matchedIds.push(id);
          matched = true;
        }
      }
      if (!matched && titleFallbackMap && titleFallbackMap.size > 0) {
        const title = collectClipRowTitle(row);
        if (title) {
          for (const [id, t] of titleFallbackMap) {
            if (
              t === title &&
              uniqueTargetIds.has(id) &&
              !foundIds.has(id) &&
              !titleMatchedIds.has(id) &&
              !titleMatchedRows.has(row)
            ) {
              titleMatchedId = id;
              matched = true;
              break;
            }
          }
        }
      }
      if (!matched) continue;

      const markMatched = (): void => {
        for (const id of matchedIds) {
          foundIds.add(id);
        }
        if (titleMatchedId) {
          titleMatchedIds.add(titleMatchedId);
          titleMatchedRows.add(row);
        }
      };

      if (row.querySelector(DESELECT_CLIP_BUTTON_ANY_SELECTOR)) {
        markMatched();
        continue;
      }
      const selectBtn = row.querySelector<HTMLButtonElement>(
        SELECT_CLIP_BUTTON_ANY_SELECTOR,
      );
      if (selectBtn) {
        selectBtn.click();
        let verified = false;
        for (let attempt = 0; attempt < 3; attempt++) {
          await sleep(50);
          if (row.querySelector(DESELECT_CLIP_BUTTON_ANY_SELECTOR)) {
            verified = true;
            break;
          }
          if (attempt < 2) selectBtn.click();
        }
        if (!verified) {
          throw new Error("clip row selection verification failed");
        }
        markMatched();
      }
    }
  }

  const allFound = () =>
    foundIds.size + titleMatchedIds.size >= uniqueTargetIds.size;

  for (let pass = 0; pass <= VIRTUAL_SCROLL_RETRY_PASSES; pass++) {
    scroller.scrollTop = 0;
    scroller.dispatchEvent(new Event("scroll"));
    await sleep(renderWaitMs);

    const step = Math.max(scroller.clientHeight, CLIP_LIST_LOAD_SCROLL_STEP_PX);
    const maxScroll = scroller.scrollHeight - scroller.clientHeight;

    for (let pos = 0; pos <= maxScroll; pos += step) {
      if (isAborted()) return foundIds.size + titleMatchedIds.size;

      scroller.scrollTop = Math.min(pos, maxScroll);
      scroller.dispatchEvent(new Event("scroll"));
      await sleep(renderWaitMs);

      await selectMatchingRows();

      if (allFound()) break;
    }

    if (allFound()) break;
  }

  restoreClipListHead(scroller);

  if (!allFound()) {
    const missing = [...uniqueTargetIds]
      .filter((id) => !foundIds.has(id) && !titleMatchedIds.has(id))
      .join(", ");
    throw new Error(
      `playlist 対象 clip row が見つかりませんでした。missing clip ID: ${missing}`,
    );
  }

  return foundIds.size + titleMatchedIds.size;
}

export interface ReadSelectedClipIdsOptions {
  isAborted: () => boolean;
  expectedClipCount?: number;
  renderWaitMs?: number;
  /** 走査 pass 数の上限（既定: VIRTUAL_SCROLL_RETRY_PASSES + 1 = 3）。
   * 余剰選択ガードのような best-effort 用途では 1 に絞り、毎 run の全 3 pass コストを避ける (#1411)。 */
  maxScanPasses?: number;
  /** 選択数がこの値を「超えた」時点で走査を打ち切る (#1411)。
   * 余剰検知が目的の場合、超過確定後に残りを全走査する価値が無いため。 */
  stopAboveCount?: number;
  /** ID を解決できない選択 row を throw せず skip する (#1411)。
   * 件数の下限比較のみが目的のガード用途向け（採用用途では従来どおり fail-loud）。 */
  skipUnresolvedIds?: boolean;
}

/**
 * ユーザーが Suno UI 上で手動選択した clip ID を採用するため、選択済み row を全スクロールで読む。
 *
 * Suno の clip list は仮想スクロールのため、現在 viewport にある row だけを読むと不足する。
 * scrollAndMultiSelectByIds と同じく top → bottom を走査し、row が再マウントされた時点の
 * aria-label="Deselect clip" から選択状態を検出する。ID は data/song href/image URL fallback の
 * 既存抽出ロジックを使う。
 */
export async function readSelectedClipIds(
  options: ReadSelectedClipIdsOptions,
): Promise<string[]> {
  const {
    isAborted,
    expectedClipCount,
    renderWaitMs = VIRTUAL_SCROLL_RENDER_WAIT_MS,
    maxScanPasses = VIRTUAL_SCROLL_RETRY_PASSES + 1,
    stopAboveCount,
    skipUnresolvedIds = false,
  } = options;

  const scroller = document.querySelector<HTMLElement>(
    CLIP_LIST_SCROLLER_SELECTOR,
  );
  if (!scroller) {
    throw new Error(CLIP_ROW_NOT_FOUND_MESSAGE);
  }

  const selectedIds = new Set<string>();

  function collectVisibleSelectedRows(): void {
    const buttons = scroller!.querySelectorAll<HTMLElement>(
      DESELECT_CLIP_BUTTON_ANY_SELECTOR,
    );
    const seenRows = new Set<HTMLElement>();
    for (const button of buttons) {
      const row = resolveClipRowFromSelectButton(button);
      if (!row || seenRows.has(row) || !isVisible(row)) continue;
      seenRows.add(row);
      const rowIds = collectClipRowIds(row);
      const firstId = rowIds.values().next().value as string | undefined;
      if (!firstId) {
        if (skipUnresolvedIds) {
          // 件数の下限比較のみが目的の呼び出し（余剰選択ガード）では、ID 劣化 row を
          // 数え漏らしても under-detection に留まる。placeholder で数えると仮想スクロールの
          // 再マウントで同一 row を重複カウントし false-positive になるため skip する。
          continue;
        }
        throw new Error(
          "選択中 clip の ID を解決できません。Suno の UI 変更の可能性があります。",
        );
      }
      selectedIds.add(firstId);
    }
  }

  const enoughSelected = () =>
    expectedClipCount !== undefined && selectedIds.size >= expectedClipCount;
  const exceededStopCount = () =>
    stopAboveCount !== undefined && selectedIds.size > stopAboveCount;
  const scanDone = () => isAborted() || enoughSelected() || exceededStopCount();

  for (let pass = 0; pass < maxScanPasses; pass++) {
    scroller.scrollTop = 0;
    scroller.dispatchEvent(new Event("scroll"));
    await sleep(renderWaitMs);
    collectVisibleSelectedRows();
    if (scanDone()) break;

    const step = Math.max(scroller.clientHeight, CLIP_LIST_LOAD_SCROLL_STEP_PX);
    const maxScroll = scroller.scrollHeight - scroller.clientHeight;

    for (let pos = 0; pos <= maxScroll; pos += step) {
      if (scanDone()) break;
      scroller.scrollTop = Math.min(pos, maxScroll);
      scroller.dispatchEvent(new Event("scroll"));
      await sleep(renderWaitMs);
      collectVisibleSelectedRows();
    }

    if (scanDone()) break;
  }

  restoreClipListHead(scroller);

  const ids = Array.from(selectedIds);
  if (ids.length === 0) {
    throw new Error(
      "選択中の clip がありません。Suno で対象曲を選択してから再実行してください。",
    );
  }
  if (expectedClipCount !== undefined && ids.length !== expectedClipCount) {
    throw new Error(
      `選択中 clip 数が一致しません: expected ${expectedClipCount}, got ${ids.length}`,
    );
  }
  return ids;
}

/**
 * Cmd+P (Mac=metaKey / 他=ctrlKey) を document に dispatch して Add to Playlist dialog を開き、
 * 出現した dialog を返す (#854)。cookie consent dialog は findPlaylistDialog の除外フィルタで拾わない。
 * 上限まで待っても出なければ throw（silent に続行しない）。
 */
export async function openAddToPlaylistDialogViaCmdP(
  dispatchCmdP?: () => Promise<void>,
): Promise<HTMLElement> {
  for (let attempt = 0; attempt < CMD_P_MAX_RETRIES; attempt++) {
    if (dispatchCmdP) {
      await dispatchCmdP();
    } else {
      const isMac = navigator.platform.toLowerCase().includes("mac");
      document.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "p",
          metaKey: isMac,
          ctrlKey: !isMac,
          bubbles: true,
        }),
      );
    }

    const deadline = Date.now() + DIALOG_OPEN_TIMEOUT_MS;
    for (;;) {
      const dialog = findPlaylistDialog();
      if (dialog) {
        return dialog;
      }
      if (Date.now() >= deadline) {
        break;
      }
      await sleep(DIALOG_OPEN_POLL_MS);
    }

    if (attempt < CMD_P_MAX_RETRIES - 1) {
      console.warn(
        `[suno-helper] Cmd+P attempt ${attempt + 1}/${CMD_P_MAX_RETRIES} failed — retrying after 500ms`,
      );
      await sleep(500);
    }
  }

  throw new Error(
    `Add to Playlist dialog を ${CMD_P_MAX_RETRIES} 回試行しても検出できませんでした。clip が selected 状態であることを確認してください。Suno の UI 変更の可能性があります。`,
  );
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
