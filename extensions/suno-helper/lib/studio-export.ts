import { setNativeValue } from "../../shared/dom";
import {
  attributeEqualsSelector,
  includesLabel,
  matchesLabel,
  PLAY_BUTTON_SELECTOR,
  SUNO_LABELS,
} from "../../shared/suno-labels";
import { sleep } from "../../shared/worker-sleep";
import { sendMessage } from "./messaging";

const STUDIO_CLIP_DRAG_TYPE = "application/x-suno-studio-clip";
const DOM_TIMEOUT_MS = 30_000;
const DOM_POLL_MS = 200;
const LIBRARY_LAZY_LOAD_WAIT_MS = 2_000;
const LIBRARY_TRANSITION_WAIT_MS = 500;
const LIBRARY_CLIP_SELECTOR = '[draggable="true"][data-clip-id]';
/** track 見出しの右クリックで context menu が開くまでの初回待ち。開かなければ ︙ ボタン click にフォールバックする (#5199)。 */
const TRACK_CONTEXT_MENU_FIRST_WAIT_MS = 5_000;
/** 配置済み clip の長さを再計測する上限。Suno 側の生成が終わるまでは短いまま置かれることがある (#5199)。 */
const PLACED_CLIP_VERIFY_WAIT_MS = 10_000;
/** 配置済み clip 長と library 曲長の比較で許容する秒差（表示の丸め誤差を吸収する）。 */
const PLACED_CLIP_LENGTH_TOLERANCE_SEC = 2;
/** clip 表示に含まれる "M:SS" 形式の曲長。 */
const CLIP_DURATION_TEXT_RE = /(\d+):(\d{2})/;
/** background 化された tab での描画遅延を吸収するための長めの待ち (#5219)。 */
const STUDIO_PATIENT_WAIT_MS = 60_000;

export interface StudioExportRequest {
  collectionId: string;
  clipIds: string[];
  /** clip ID → 曲タイトル。Studio Library の検索 fallback に使う (#5221)。 */
  clipTitleById?: Record<string, string>;
}

export interface StudioExportDeps {
  createEmptyProject: () => Promise<void>;
  renameProject: (name: string) => Promise<void>;
  openLibrary: () => Promise<void>;
  placeClipOnTrackAtStart: (
    clipId: string,
    trackIndex: number
  ) => Promise<string>;
  countPlacedClips: () => Promise<number>;
  readTrackNames: () => Promise<string[]>;
  openExportMenu: () => Promise<void>;
  clickMultitrackExport: () => Promise<void>;
}

type Button = HTMLButtonElement;

interface TrustedClickUntilOptions {
  postClickDelayMs?: number;
  recoverButton?: () => Promise<void>;
}

function isVisible(element: Element): boolean {
  if (!(element instanceof HTMLElement) || element.hidden) return false;
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return (
    element.getAttribute("aria-hidden") !== "true" &&
    style.display !== "none" &&
    style.visibility !== "hidden" &&
    rect.width > 0 &&
    rect.height > 0
  );
}

function describeElement(element: Element): string {
  const tag = element.tagName.toLowerCase();
  const id = element.id ? `#${element.id}` : "";
  const aria = element.getAttribute("aria-label");
  const ariaPart = aria ? ` [aria-label="${aria}"]` : "";
  const text = (element.textContent ?? "")
    .trim()
    .replace(/\s+/g, " ")
    .slice(0, 40);
  const textPart = text ? ` "${text}"` : "";
  return `<${tag}${id}>${ariaPart}${textPart}`;
}

function diagnoseHiddenElement(element: Element): string {
  if (!(element instanceof HTMLElement)) {
    return "要素は存在するが HTMLElement ではない";
  }
  if (element.hidden) return "要素は存在するが hidden 属性";
  if (element.getAttribute("aria-hidden") === "true") {
    return "要素は存在するが aria-hidden";
  }
  const style = getComputedStyle(element);
  if (style.display === "none") return "要素は存在するが display:none";
  if (style.visibility === "hidden") {
    return "要素は存在するが visibility:hidden";
  }
  const rect = element.getBoundingClientRect();
  return `要素は存在するがサイズ ${Math.round(rect.width)}x${Math.round(rect.height)}`;
}

function diagnoseOcclusion(element: Element, x: number, y: number): string {
  if (typeof document.elementFromPoint !== "function") {
    return "要素は表示中（遮蔽判定不可）";
  }
  const top = document.elementFromPoint(x, y);
  if (
    !top ||
    top === element ||
    element.contains(top) ||
    top.contains(element)
  ) {
    return "要素は表示中（クリックは未反映）";
  }
  // overlay は Shadow DOM なので elementFromPoint は host 要素を返す。
  // WXT の shadow root host は <suno-helper-overlay> カスタム要素。
  const own = top.tagName.toLowerCase().includes("suno-helper");
  return own
    ? `要素は存在するが suno-helper パネルに遮蔽 (${describeElement(top)})`
    : `要素は存在するが他要素に遮蔽 (${describeElement(top)})`;
}

/**
 * タイムアウト時の切り分け証跡。対象が「存在しない」のか、存在するが
 * 非表示 / 画面外 / 他要素（suno-helper パネル含む）に遮蔽されているのかを
 * 1 行で返す。失敗ログだけで原因を識別できるようにする (#5198)。
 */
function diagnoseElement(element: Element | null): string {
  if (!element) return "要素なし";
  if (!isVisible(element)) return diagnoseHiddenElement(element);
  const rect = element.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) {
    return `要素は存在するが画面外 (x=${Math.round(x)}, y=${Math.round(y)})`;
  }
  return diagnoseOcclusion(element, x, y);
}

async function waitForElement<T extends Element>(
  find: () => T | null,
  description: string,
  timeoutMs = DOM_TIMEOUT_MS
): Promise<T> {
  const element = await waitForElementOrNull(find, timeoutMs);
  if (element) return element;
  throw new Error(
    `Studio の ${description} が見つかりません（${diagnoseElement(find())}）`
  );
}

/** timeout まで見つからなければ throw せず null を返す。フォールバック分岐に使う。 */
async function waitForElementOrNull<T extends Element>(
  find: () => T | null,
  timeoutMs: number
): Promise<T | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const element = find();
    if (element && isVisible(element)) return element;
    await sleep(DOM_POLL_MS);
  }
  return null;
}

function toLabelList(labels: string | readonly string[]): readonly string[] {
  return typeof labels === "string" ? [labels] : labels;
}

/** requireVisible=false はタイムアウト診断用。非表示ボタンも拾って理由を報告する。 */
function findButtonByName(
  names: string | readonly string[],
  requireVisible = true
): Button | null {
  const labels = toLabelList(names);
  return (
    Array.from(document.querySelectorAll<Button>("button")).find(
      (button) =>
        matchesLabel(button.textContent, labels) &&
        (!requireVisible || isVisible(button))
    ) ?? null
  );
}

/** ラベルの大小文字差や別表記で取りこぼさないよう、照合は常に case-insensitive とする。 */
function buttonByName(names: string | readonly string[]): Button | null {
  return findButtonByName(names);
}

function findButtonByAriaLabel(
  labels: string | readonly string[],
  requireVisible = true
): Button | null {
  const element = document.querySelector<Button>(
    attributeEqualsSelector("button", "aria-label", toLabelList(labels), {
      ignoreCase: true,
    })
  );
  return element && (!requireVisible || isVisible(element)) ? element : null;
}

function buttonByAriaLabel(labels: string | readonly string[]): Button | null {
  return findButtonByAriaLabel(labels);
}

export async function waitForTrackCount(
  expected: number
): Promise<HTMLElement[]> {
  // track は非同期に描画されるため、件数ぴったりではなく expected 以上を render lag
  // 吸収用の長めの窓で待つ。Add 系の overshoot 検知は click 側の == 判定が担う (#5219)。
  const find = () =>
    document.querySelectorAll<HTMLElement>("[data-track-id]").length >= expected
      ? document.querySelector<HTMLElement>("[data-track-id]")
      : null;
  const first = await waitForElementOrNull(find, STUDIO_PATIENT_WAIT_MS);
  if (!first) {
    // 見つからなければ track 一覧領域へ scroll を流して再 mount を促し、一度だけ retry する。
    document
      .querySelector<HTMLElement>("[data-studio-main-canvas]")
      ?.dispatchEvent(new Event("scroll", { bubbles: true }));
    await waitForElement(find, `track ${expected} 件以上`);
  }
  return Array.from(document.querySelectorAll<HTMLElement>("[data-track-id]"));
}

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value"
  )?.set;
  if (!setter) throw new Error("Studio の入力値を更新できません");
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

export function commitStudioInputValue(
  input: HTMLInputElement,
  value: string
): void {
  setInputValue(input, value);
  // 現行 Studio の rename 入力は Enter keydown/keyup でのみ確定する。
  // blur だけだと編集が破棄される (#5221)。
  const init: KeyboardEventInit = { key: "Enter", bubbles: true };
  input.dispatchEvent(new KeyboardEvent("keydown", init));
  input.dispatchEvent(new KeyboardEvent("keyup", init));
  input.blur();
}

export function dispatchStudioPointerClick(element: HTMLElement): void {
  const rect = element.getBoundingClientRect();
  const common = {
    bubbles: true,
    cancelable: true,
    composed: true,
    clientX: rect.left + rect.width / 2,
    clientY: rect.top + rect.height / 2,
    button: 0,
  };
  const pointer = {
    ...common,
    pointerId: 1,
    pointerType: "mouse",
    isPrimary: true,
  };
  element.dispatchEvent(new PointerEvent("pointerover", pointer));
  element.dispatchEvent(new PointerEvent("pointerenter", pointer));
  element.dispatchEvent(new MouseEvent("mouseover", common));
  element.dispatchEvent(new MouseEvent("mouseenter", common));
  element.dispatchEvent(
    new PointerEvent("pointerdown", { ...pointer, buttons: 1 })
  );
  element.dispatchEvent(new MouseEvent("mousedown", { ...common, buttons: 1 }));
  element.dispatchEvent(new PointerEvent("pointerup", pointer));
  element.dispatchEvent(new MouseEvent("mouseup", common));
  element.dispatchEvent(new MouseEvent("click", common));
}

/**
 * track 見出しへの右クリック sequence。track の ︙ ボタン
 * (button.track-menu-reveal[data-context-menu-trigger]) は hover-only で幅 0 のため
 * 通常 click では開けず、heading への contextmenu 系 event が正規の開き方 (#5199)。
 */
export function dispatchStudioContextMenu(element: HTMLElement): void {
  const rect = element.getBoundingClientRect();
  const common = {
    bubbles: true,
    cancelable: true,
    composed: true,
    clientX: rect.left + rect.width / 2,
    clientY: rect.top + rect.height / 2,
    button: 2,
  };
  const pointer = {
    ...common,
    pointerId: 1,
    pointerType: "mouse",
    isPrimary: true,
  };
  element.dispatchEvent(
    new PointerEvent("pointerdown", { ...pointer, buttons: 2 })
  );
  element.dispatchEvent(new MouseEvent("mousedown", { ...common, buttons: 2 }));
  element.dispatchEvent(new MouseEvent("contextmenu", common));
  element.dispatchEvent(new MouseEvent("mouseup", { ...common, buttons: 0 }));
}

async function dispatchTrustedStudioClick(element: HTMLElement): Promise<void> {
  const rect = element.getBoundingClientRect();
  await sendMessage("sendTrustedClick", {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  });
}

export async function clickStudioButtonUntil<T extends HTMLElement>(
  buttonName: string | readonly string[],
  findResult: () => T | null,
  description: string,
  clickMode: "trusted" | "pointer" = "trusted",
  timeoutMs = DOM_TIMEOUT_MS
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = findResult();
    if (result && isVisible(result)) return result;
    const button = buttonByName(buttonName);
    if (button && !button.disabled) {
      if (clickMode === "pointer") {
        dispatchStudioPointerClick(button);
      } else {
        await dispatchTrustedStudioClick(button);
      }
    }
    await sleep(DOM_POLL_MS);
  }
  const button = findButtonByName(buttonName, false);
  const buttonDiagnosis =
    button === null
      ? "ボタンなし"
      : button.disabled
        ? "ボタンは無効"
        : diagnoseElement(button);
  throw new Error(
    `Studio の ${description} が見つかりません（${diagnoseElement(findResult())}。ボタン: ${buttonDiagnosis}）`
  );
}

export async function clickStudioAriaButtonUntil<T extends HTMLElement>(
  ariaLabel: string | readonly string[],
  findResult: () => T | null,
  description: string,
  options: TrustedClickUntilOptions = {}
): Promise<T> {
  const deadline = Date.now() + DOM_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const result = findResult();
    if (result && isVisible(result)) return result;
    const button = buttonByAriaLabel(ariaLabel);
    if (button && !button.disabled) {
      await dispatchTrustedStudioClick(button);
      if (options.postClickDelayMs) {
        await sleep(options.postClickDelayMs);
      }
    } else if (options.recoverButton) {
      await options.recoverButton();
    }
    await sleep(DOM_POLL_MS);
  }
  const button = findButtonByAriaLabel(ariaLabel, false);
  const buttonDiagnosis =
    button === null
      ? "ボタンなし"
      : button.disabled
        ? "ボタンは無効"
        : diagnoseElement(button);
  throw new Error(
    `Studio の ${description} が見つかりません（${diagnoseElement(findResult())}。ボタン: ${buttonDiagnosis}）`
  );
}

function findLibraryScroller(element: Element): HTMLElement | null {
  let current: HTMLElement | null = element.parentElement;
  while (current) {
    if (
      getComputedStyle(current).overflowY === "auto" &&
      current.clientHeight > 0
    ) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

function countLibraryClips(): number {
  return document.querySelectorAll(LIBRARY_CLIP_SELECTOR).length;
}

function findLibrarySearchInput(): HTMLInputElement | null {
  return (
    Array.from(
      document.querySelectorAll<HTMLInputElement>("input[placeholder]")
    ).find(
      (input) =>
        isVisible(input) &&
        includesLabel(
          input.getAttribute("placeholder"),
          SUNO_LABELS.librarySearchPlaceholder
        )
    ) ?? null
  );
}

async function scrollLibraryForClip(
  scroller: HTMLElement,
  selector: string,
  deadline: number
): Promise<HTMLElement | null> {
  scroller.scrollTop = 0;
  while (Date.now() < deadline) {
    const clip = document.querySelector<HTMLElement>(selector);
    if (clip && isVisible(clip)) return clip;
    const before = scroller.scrollTop;
    const beforeHeight = scroller.scrollHeight;
    const beforeClipCount = countLibraryClips();
    scroller.scrollTop = Math.min(
      scroller.scrollHeight,
      before + Math.max(200, scroller.clientHeight * 0.8)
    );
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    await sleep(DOM_POLL_MS);
    if (scroller.scrollTop !== before) continue;

    const lazyLoadDeadline = Math.min(
      deadline,
      Date.now() + LIBRARY_LAZY_LOAD_WAIT_MS
    );
    let libraryGrew = false;
    while (Date.now() < lazyLoadDeadline) {
      if (
        scroller.scrollHeight > beforeHeight ||
        countLibraryClips() > beforeClipCount
      ) {
        libraryGrew = true;
        break;
      }
      await sleep(DOM_POLL_MS);
    }
    if (!libraryGrew) break;
  }
  return null;
}

// Studio Library / In Project / /create の一覧は ~20 件表示で infinite scroll が
// 効かず clip 件数が多いと scroll だけでは対象が描画されない (#5221)。
// タイトルが分かる clip は Library 検索で単体描画してから拾う。
async function findLibraryClipByTitleSearch(
  title: string,
  selector: string
): Promise<HTMLElement | null> {
  const search = findLibrarySearchInput();
  if (!search) return null;
  const deadline = Date.now() + LIBRARY_LAZY_LOAD_WAIT_MS;
  setNativeValue(search, title);
  try {
    while (Date.now() < deadline) {
      const clip = document.querySelector<HTMLElement>(selector);
      if (clip && isVisible(clip)) return clip;
      await sleep(DOM_POLL_MS);
    }
    return null;
  } finally {
    setNativeValue(search, "");
  }
}

export async function findLibraryClip(
  clipId: string,
  title?: string
): Promise<HTMLElement> {
  const selector = `[draggable="true"][data-clip-id="${CSS.escape(clipId)}"]`;
  const firstVisibleClip = await waitForElement(
    () => document.querySelector<HTMLElement>(LIBRARY_CLIP_SELECTOR),
    "Library の clip 一覧"
  );
  const scroller = findLibraryScroller(firstVisibleClip);
  if (!scroller)
    throw new Error("Studio の Library scroll 領域が見つかりません");
  const clip = await scrollLibraryForClip(
    scroller,
    selector,
    Date.now() + DOM_TIMEOUT_MS
  );
  if (clip) return clip;
  const searched = title
    ? await findLibraryClipByTitleSearch(title, selector)
    : null;
  if (searched) return searched;
  throw new Error(
    `Studio Library に clip ${clipId} が見つかりません` +
      (title
        ? ""
        : "（タイトル不明のため検索 fallback も使えません）。Studio で対象曲が見える一覧を開いてから再実行してください")
  );
}

function dispatchClipDrop(
  source: HTMLElement,
  track: HTMLElement,
  clipId: string
): void {
  const dropTarget = document.querySelector<HTMLElement>(
    "[data-studio-main-canvas]"
  )?.parentElement;
  if (!dropTarget) throw new Error("Studio の timeline が見つかりません");
  const dataTransfer = new DataTransfer();
  const trackRect = track.getBoundingClientRect();
  const dropTargetRect = dropTarget.getBoundingClientRect();
  const clientX = dropTargetRect.left + trackRect.width + 10;
  const clientY = trackRect.top + trackRect.height / 2;
  const event = (type: string, target: HTMLElement): void => {
    target.dispatchEvent(
      new DragEvent(type, {
        bubbles: true,
        cancelable: true,
        dataTransfer,
        clientX,
        clientY,
      })
    );
  };
  event("dragstart", source);
  if (dataTransfer.getData(STUDIO_CLIP_DRAG_TYPE) !== clipId) {
    throw new Error(`Studio clip ${clipId} の drag data を作成できません`);
  }
  event("dragenter", dropTarget);
  event("dragover", dropTarget);
  event("drop", dropTarget);
  event("dragend", source);
}

function libraryClipTitle(source: HTMLElement, clipId: string): string {
  // Studio Library の再生ボタン。aria-label が "Play" 単独と "Play <曲名>" / "<曲名>を再生"
  // 系のどちらでも拾えるよう、完全一致ラベルと PLAY_BUTTON_SELECTOR を併用する (#5209)。
  const playButton = source.querySelector<HTMLButtonElement>(
    `${attributeEqualsSelector("button", "aria-label", SUNO_LABELS.studioPlay, { ignoreCase: true })}, ${PLAY_BUTTON_SELECTOR}`
  );
  const title = playButton?.parentElement?.nextElementSibling
    ?.querySelector<HTMLElement>(":scope > span")
    ?.textContent?.trim();
  if (!title) {
    throw new Error(`Studio Library の clip ${clipId} から曲名を読めません`);
  }
  return title;
}

function trackHeading(track: HTMLElement): HTMLElement | null {
  return (
    Array.from(track.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (element) => element.textContent?.trim()
    ) ?? null
  );
}

function trackName(track: HTMLElement): string | null {
  return trackHeading(track)?.textContent?.trim() ?? null;
}

/**
 * Rename click で開く入力欄。focus を持つため document.activeElement でも拾える。
 * 従来の body 直下走査（value が現行名と一致する input）と併用する (#5199)。
 */
function findRenameTrackInput(currentName: string): HTMLInputElement | null {
  const active = document.activeElement;
  if (
    active instanceof HTMLInputElement &&
    isVisible(active) &&
    active.value === currentName
  ) {
    return active;
  }
  const direct = Array.from(document.body.children).find(
    (element): element is HTMLInputElement =>
      element instanceof HTMLInputElement &&
      element.value === currentName &&
      isVisible(element)
  );
  if (direct) return direct;
  return active instanceof HTMLInputElement && isVisible(active)
    ? active
    : null;
}

export async function renameTrack(
  track: HTMLElement,
  name: string
): Promise<void> {
  const heading = trackHeading(track);
  const currentName = heading?.textContent?.trim() ?? null;
  if (!currentName || !heading) {
    throw new Error("Studio の track 名を読めません");
  }
  dispatchStudioContextMenu(heading);
  // 大小文字揺れ ("Rename Track" / "Rename track") は照合の case-insensitive で吸収する (#5198, #5209)。
  let renameButton = await waitForElementOrNull(
    () => buttonByName(SUNO_LABELS.studioRenameTrack),
    TRACK_CONTEXT_MENU_FIRST_WAIT_MS
  );
  if (!renameButton) {
    // 右クリックで開かない環境向けのフォールバック。幅 0 の ︙ ボタンを pointer click する。
    const menu = track.querySelector<HTMLButtonElement>(
      'button.track-menu-reveal[data-context-menu-trigger="true"]'
    );
    if (menu) dispatchStudioPointerClick(menu);
    renameButton = await waitForElement(
      () => buttonByName(SUNO_LABELS.studioRenameTrack),
      "Rename Track ボタン"
    );
  }
  dispatchStudioPointerClick(renameButton);
  const input = await waitForElement(
    () => findRenameTrackInput(currentName),
    "track 名入力"
  );
  commitStudioInputValue(input, name);
  await waitForElement(
    () => (trackName(track) === name ? track : null),
    `track 名 ${name}`
  );
}

/** clip 要素の text から "M:SS" の曲長を秒で読む。表示が無ければ null。 */
function clipDurationSeconds(element: HTMLElement): number | null {
  const toSeconds = (match: RegExpMatchArray) =>
    Number(match[1]) * 60 + Number(match[2]);
  // 曲長 badge らしい要素（text 全体が M:SS）を優先し、見つからなければ
  // clip 全体の text から最初の M:SS 表記を拾う。
  const badge = Array.from(element.querySelectorAll<HTMLElement>("*")).find(
    (child) => {
      const text = child.textContent?.trim();
      return text !== undefined && /^\d+:\d{2}$/.test(text);
    }
  );
  const match =
    badge?.textContent?.trim().match(CLIP_DURATION_TEXT_RE) ??
    element.textContent?.match(CLIP_DURATION_TEXT_RE);
  if (!match) return null;
  return toSeconds(match);
}

/**
 * 配置済み clip の長さを library 曲長と照合する (#5199)。
 * Suno が曲を仕上げる前に配置すると約 2 分で切れた clip が置かれ、書き出し WAV も
 * その長さで無音になる。配置後の長さが library 曲長より短いままなら bounded に
 * 再計測して、伸びなければ operator 向けに明示的なエラーで止める。
 * 戻り値: true = 照合できた / false = clip 要素や曲長表示を読めず検証不能。
 */
export async function verifyPlacedClipLength(
  track: HTMLElement,
  clipId: string,
  expectedSeconds: number | null
): Promise<boolean> {
  if (expectedSeconds === null) return false;
  const selector = `[data-clip-id="${CSS.escape(clipId)}"]`;
  const deadline = Date.now() + PLACED_CLIP_VERIFY_WAIT_MS;
  let measured = false;
  let placedSeconds: number | null = null;
  while (Date.now() < deadline) {
    const placed =
      track.querySelector<HTMLElement>(selector) ??
      document.querySelector<HTMLElement>(
        `[data-studio-main-canvas] ${selector}`
      );
    if (placed) {
      const seconds = clipDurationSeconds(placed);
      if (seconds !== null) {
        measured = true;
        placedSeconds = seconds;
        if (seconds + PLACED_CLIP_LENGTH_TOLERANCE_SEC >= expectedSeconds) {
          return true;
        }
      }
    }
    await sleep(DOM_POLL_MS);
  }
  if (!measured) return false;
  throw new Error(
    `Studio に配置した clip の長さがライブラリの曲長より短いままです（placed ${placedSeconds}s / library ${expectedSeconds}s）。Suno 側の生成完了を待ってから再実行してください`
  );
}

/**
 * project 領域が空（track 1 件以下・clip 0 件）になるまで待つ (#5219)。
 * 内容を持つ既存の Untitled Project が開いたままなら、そのまま rename すると
 * 上書きするため非空が続く限り待ち、timeout で観測件数つきの明示的エラーにする。
 */
export async function waitForEmptyStudioProject(): Promise<void> {
  const deadline = Date.now() + DOM_TIMEOUT_MS;
  let trackCount = 0;
  let clipCount = 0;
  for (;;) {
    trackCount = document.querySelectorAll("[data-track-id]").length;
    clipCount = document.querySelectorAll(
      "[data-track-id] [data-clip-id]"
    ).length;
    if (clipCount === 0 && trackCount <= 1) return;
    if (Date.now() >= deadline) {
      throw new Error(
        `内容を持つ Untitled Project（track ${trackCount} 件 / clip ${clipCount} 件）が開かれました。Studio で新規の空 project を作成してから再実行してください。`
      );
    }
    await sleep(DOM_POLL_MS);
  }
}

/**
 * Library を開き All Songs の clip 一覧へ辿る。Library は前回開いた workspace を
 * 記憶して直接その一覧を開くことがあり、その場合 Library トップの All Songs は
 * 存在しない。Go back があればトップへ戻ってから All Songs を探す (#5198)。
 */
export async function openStudioLibraryAllSongs(): Promise<HTMLElement> {
  // 「開いた」ことの確認は All Songs または workspace 内の Go back のどちらかで行う。
  await clickStudioAriaButtonUntil(
    SUNO_LABELS.studioOpenLibrary,
    () =>
      buttonByName(SUNO_LABELS.studioAllSongs) ??
      buttonByAriaLabel(SUNO_LABELS.studioGoBack),
    "All Songs / Go back ボタン"
  );
  // workspace 内に開いた場合は Go back で Library トップへ戻る。トップで開いた
  // 場合は All Songs が即座に見つかり、Go back はクリックしない。
  await clickStudioAriaButtonUntil(
    SUNO_LABELS.studioGoBack,
    () => buttonByName(SUNO_LABELS.studioAllSongs),
    "All Songs ボタン",
    { postClickDelayMs: LIBRARY_TRANSITION_WAIT_MS }
  );
  return clickStudioButtonUntil(
    SUNO_LABELS.studioAllSongs,
    () =>
      document.querySelector<HTMLElement>('[draggable="true"][data-clip-id]'),
    "Library の clip 一覧",
    "pointer"
  );
}

export function createBrowserStudioExportDeps(
  request?: StudioExportRequest
): StudioExportDeps {
  // 配置済み clip に曲長表示が無い DOM では verifyPlacedClipLength が毎回
  // タイムアウトまで待ってしまうため、初回の検証不能をもって以後の照合を止める (#5199)。
  let placedClipLengthCheckEnabled = true;
  return {
    async createEmptyProject() {
      const location = new URL(window.location.href);
      if (
        location.origin !== "https://suno.com" ||
        location.pathname !== "/studio"
      ) {
        throw new Error("Studio ページを開けませんでした");
      }
      await clickStudioAriaButtonUntil(
        SUNO_LABELS.studioProjectMenu,
        () => buttonByName(SUNO_LABELS.studioNewProject),
        "New Project ボタン"
      );
      await clickStudioButtonUntil(
        SUNO_LABELS.studioNewProject,
        () => buttonByName(SUNO_LABELS.studioNewEmptyProject),
        "New empty project ボタン"
      );
      await clickStudioButtonUntil(
        SUNO_LABELS.studioNewEmptyProject,
        () => {
          const menu = buttonByAriaLabel(SUNO_LABELS.studioProjectMenu);
          return menu &&
            matchesLabel(menu.textContent, SUNO_LABELS.studioUntitledProject)
            ? menu
            : null;
        },
        "空 project"
      );
      // 新規 empty project は track 1 件・clip 0 件で始まる。内容を持つ既存の
      // Untitled Project が開いたまま rename すると上書きするため、空になるまで
      // 待ってから検証する (#5219)。
      await waitForEmptyStudioProject();
    },
    async renameProject(name) {
      await clickStudioAriaButtonUntil(
        SUNO_LABELS.studioProjectMenu,
        () => buttonByName(SUNO_LABELS.studioRename),
        "Rename ボタン"
      );
      const input = await clickStudioButtonUntil(
        SUNO_LABELS.studioRename,
        () =>
          document.querySelector<HTMLInputElement>(
            attributeEqualsSelector(
              "input",
              "aria-label",
              SUNO_LABELS.studioProjectName,
              { ignoreCase: true }
            )
          ),
        "Project name 入力",
        "trusted",
        STUDIO_PATIENT_WAIT_MS
      );
      commitStudioInputValue(input, name);
      await waitForElement(
        () =>
          buttonByAriaLabel(
            SUNO_LABELS.studioProjectMenu
          )?.textContent?.trim() === name
            ? buttonByAriaLabel(SUNO_LABELS.studioProjectMenu)
            : null,
        `project 名 ${name}`
      );
    },
    async openLibrary() {
      await openStudioLibraryAllSongs();
    },
    async placeClipOnTrackAtStart(clipId, trackIndex) {
      if (trackIndex > 0) {
        await clickStudioAriaButtonUntil(
          SUNO_LABELS.studioAddNewTrack,
          () => buttonByAriaLabel(SUNO_LABELS.studioAddAudioTrack),
          "Add Audio track ボタン"
        );
        // The menu animates from the trigger. Its item is already "visible"
        // before the final transform settles, so clicking immediately can hit
        // the backdrop at the stale center point and only close the menu.
        await sleep(500);
        await clickStudioAriaButtonUntil(
          SUNO_LABELS.studioAddAudioTrack,
          () =>
            document.querySelectorAll<HTMLElement>("[data-track-id]").length ===
            trackIndex + 1
              ? document.querySelector<HTMLElement>("[data-track-id]")
              : null,
          `track ${trackIndex + 1} 件`,
          {
            // Track creation is asynchronous. Waiting before the next poll
            // prevents duplicate Add Audio actions from overshooting the
            // expected count when Studio is under load.
            postClickDelayMs: 1_000,
            // A click during the closing edge of the menu animation can only
            // dismiss the menu. Reopen it so the action itself can be retried.
            recoverButton: async () => {
              const trigger = buttonByAriaLabel(SUNO_LABELS.studioAddNewTrack);
              if (trigger && !trigger.disabled) {
                await dispatchTrustedStudioClick(trigger);
                await sleep(500);
              }
            },
          }
        );
      }
      const tracks = await waitForTrackCount(trackIndex + 1);
      const source = await findLibraryClip(
        clipId,
        request?.clipTitleById?.[clipId]
      );
      const title = libraryClipTitle(source, clipId);
      const expectedSeconds = clipDurationSeconds(source);
      dispatchClipDrop(source, tracks[trackIndex], clipId);
      await renameTrack(tracks[trackIndex], title);
      if (placedClipLengthCheckEnabled) {
        placedClipLengthCheckEnabled = await verifyPlacedClipLength(
          tracks[trackIndex],
          clipId,
          expectedSeconds
        );
        if (!placedClipLengthCheckEnabled) {
          console.warn(
            `[suno-helper] clip ${clipId} の配置後の長さを計測できません。以後の曲長照合をスキップします`
          );
        }
      }
      return title;
    },
    async countPlacedClips() {
      // In Project 一覧は ~20 件表示上限があるため、配置済み clip は
      // timeline 側の track 内 [data-clip-id] 要素から数える (#5221)。
      return document.querySelectorAll("[data-track-id] [data-clip-id]").length;
    },
    async readTrackNames() {
      return Array.from(
        document.querySelectorAll<HTMLElement>("[data-track-id]")
      ).map((track, index) => {
        const name = trackName(track);
        if (!name) {
          throw new Error(`Studio の track ${index + 1} 名を読めません`);
        }
        return name;
      });
    },
    async openExportMenu() {
      await clickStudioAriaButtonUntil(
        SUNO_LABELS.studioExportMenu,
        () => buttonByName(SUNO_LABELS.studioMultitrack),
        "Multitrack export ボタン"
      );
    },
    async clickMultitrackExport() {
      const button = await waitForElement(
        () => buttonByName(SUNO_LABELS.studioMultitrack),
        "Multitrack export ボタン"
      );
      if (button.disabled || button.getAttribute("aria-disabled") === "true") {
        throw new Error(
          "Studio の Multitrack export が利用できません。Premier プランを確認してください"
        );
      }
      dispatchStudioPointerClick(button);
    },
  };
}

export async function exportStudioMultitrack(
  request: StudioExportRequest,
  deps: StudioExportDeps
): Promise<void> {
  if (request.clipIds.length === 0) {
    throw new Error("Studio export に必要な clip ID がありません");
  }
  await deps.createEmptyProject();
  await deps.renameProject(request.collectionId);
  await deps.openLibrary();
  const expectedTrackNames: string[] = [];
  for (const [trackIndex, clipId] of request.clipIds.entries()) {
    expectedTrackNames.push(
      await deps.placeClipOnTrackAtStart(clipId, trackIndex)
    );
  }
  const placedCount = await deps.countPlacedClips();
  if (placedCount !== request.clipIds.length) {
    throw new Error(
      `Studio track 数が一致しません: expected ${request.clipIds.length}, got ${placedCount}`
    );
  }
  const actualTrackNames = await deps.readTrackNames();
  for (const [index, expectedName] of expectedTrackNames.entries()) {
    const actualName = actualTrackNames[index];
    if (actualName !== expectedName) {
      throw new Error(
        `Studio track 名が一致しません: track ${index + 1} expected ${expectedName}, got ${actualName}`
      );
    }
  }
  await deps.openExportMenu();
  await deps.clickMultitrackExport();
}

export function performStudioMultitrackExport(
  request: StudioExportRequest
): Promise<void> {
  return exportStudioMultitrack(
    request,
    createBrowserStudioExportDeps(request)
  );
}

/** 開いた Studio tab の id を返す。呼び出し側は ZIP 完了後に必ず closeStudioExportTab で閉じる。 */
export async function requestStudioMultitrackExport(
  request: StudioExportRequest
): Promise<number> {
  const result = await sendMessage("startStudioExport", request);
  if (!result?.ok) {
    throw new Error(result?.message ?? "Studio export を開始できませんでした");
  }
  return result.studioTabId;
}

/** tab の close 失敗は download 結果を左右しないため warn に留める。 */
export async function closeStudioExportTab(studioTabId: number): Promise<void> {
  await sendMessage("closeStudioExport", { studioTabId }).catch(
    (error: unknown) => {
      console.warn("[suno-helper] closeStudioExport 中継失敗:", error);
    }
  );
}
