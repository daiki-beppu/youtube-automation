// YouTube コミュニティ投稿 UI の DOM 操作を集約する。
// 実測 selector / event model: docs/research/community-helper-dom-map.md (#1708)。

import { isVisible } from "./visibility";

const FORM_SELECTOR = "ytd-backstage-post-dialog-renderer";
const TEXT_FIELD_SELECTOR =
  '#contenteditable-root[contenteditable="true"], textarea, input:not([type="file"])';
const IMAGE_INPUT_SELECTOR =
  '#dropzone input[type="file"][name="Filedata"][accept="image/*"]';
const IMAGE_THUMBNAIL_SELECTOR =
  "#thumbnail-images-container ytd-backstage-multi-image-thumbnail-renderer img.thumbnail-image[src]";
const OPERATION_MENU_SELECTOR = "#option-menu button:not([disabled])";
const MENU_ITEM_SELECTOR =
  "ytd-menu-popup-renderer ytd-menu-service-item-renderer";
const SCHEDULE_PANEL_SELECTOR = "#scheduling-panel";
const CALENDAR_MONTH_SELECTOR =
  'ytd-calendar-date-picker .calendar-month[role="listitem"]';
const TIME_OPTION_SELECTOR =
  'ytd-date-time-picker-renderer #time-listbox [role="option"]';
const POST_BUTTON_SELECTOR = "#submit-button button";
const DEFAULT_WAIT_TIMEOUT_MS = 10_000;
const TIME_OPTION_COUNT = 96;

interface ScheduleParts {
  day: number;
  hour: number;
  minute: number;
  month: number;
  offsetMinutes: number;
  year: number;
}

export interface ExpectedCommunityPostState {
  imageFilename: string | null;
  scheduledAt: string;
  text: string;
}

interface VerifiedImageAttachment {
  filename: string;
  mimeType: string;
  src: string;
  thumbnail: HTMLImageElement;
}

interface VerifiedSchedule {
  isoDate: string;
  selectedDay: HTMLElement;
  selectedOption: HTMLElement;
  targetMonth: number;
  targetYear: number;
}

const verifiedImages = new WeakMap<HTMLElement, VerifiedImageAttachment>();
const verifiedSchedules = new WeakMap<HTMLElement, VerifiedSchedule>();

class CommunityDomError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CommunityDomError";
  }
}

function openRoots(root: ParentNode): ParentNode[] {
  const roots: ParentNode[] = [root];
  if (root instanceof Element && root.shadowRoot) {
    roots.push(root.shadowRoot);
  }
  for (const scope of roots) {
    for (const element of scope.querySelectorAll("*")) {
      if (element.shadowRoot && !roots.includes(element.shadowRoot)) {
        roots.push(element.shadowRoot);
      }
    }
  }
  return roots;
}

function queryAll<T extends Element>(root: ParentNode, selector: string): T[] {
  return openRoots(root).flatMap((scope) => [
    ...(scope.querySelectorAll<T>(selector) ?? []),
  ]);
}

function resolveUniqueVisible<T extends HTMLElement>(
  root: ParentNode,
  selector: string,
  label: string
): T {
  const candidates = queryAll<T>(root, selector).filter(isVisible);
  if (candidates.length !== 1) {
    throw new CommunityDomError(
      `${label}を一意に解決できません: selector=${selector}, count=${candidates.length}`
    );
  }
  return candidates[0];
}

function resolveUnique<T extends Element>(
  root: ParentNode,
  selector: string,
  label: string
): T {
  const candidates = queryAll<T>(root, selector);
  if (candidates.length !== 1) {
    throw new CommunityDomError(
      `${label}を一意に解決できません: selector=${selector}, count=${candidates.length}`
    );
  }
  return candidates[0];
}

function resolveForm(root: ParentNode): HTMLElement {
  return resolveUniqueVisible(root, FORM_SELECTOR, "コミュニティ投稿フォーム");
}

function resolveCommentbox(form: ParentNode): HTMLElement {
  return resolveUniqueVisible(
    form,
    "ytd-commentbox#commentbox",
    "コミュニティ投稿 commentbox"
  );
}

async function waitForUniqueVisible<T extends HTMLElement>(
  root: ParentNode,
  selector: string,
  label: string,
  timeoutMs = DEFAULT_WAIT_TIMEOUT_MS
): Promise<T> {
  const resolve = (): T | undefined => {
    const candidates = queryAll<T>(root, selector).filter(isVisible);
    if (candidates.length > 1) {
      throw new CommunityDomError(
        `${label}を一意に解決できません: selector=${selector}, count=${candidates.length}`
      );
    }
    return candidates[0];
  };
  const deadline = Date.now() + timeoutMs;
  while (Date.now() <= deadline) {
    const candidate = resolve();
    if (candidate) {
      return candidate;
    }
    await new Promise<void>((resolveDelay) => setTimeout(resolveDelay, 20));
  }
  throw new CommunityDomError(
    `${label}の表示を待機中にタイムアウトしました: selector=${selector}`
  );
}

async function waitForCondition(
  _root: ParentNode,
  condition: () => boolean,
  label: string,
  timeoutMs = DEFAULT_WAIT_TIMEOUT_MS
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() <= deadline) {
    if (condition()) {
      return;
    }
    await new Promise<void>((resolveDelay) => setTimeout(resolveDelay, 20));
  }
  throw new CommunityDomError(`${label}を待機中にタイムアウトしました`);
}

function parseScheduleParts(isoDate: string): ScheduleParts {
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|([+-])(\d{2}):(\d{2}))$/.exec(
      isoDate
    );
  if (!match) {
    throw new CommunityDomError(
      `予約日時は timezone 付き ISO 8601 で指定してください: ${isoDate}`
    );
  }
  const [
    ,
    yearText,
    monthText,
    dayText,
    hourText,
    minuteText,
    timezoneText,
    offsetSign,
    offsetHourText,
    offsetMinuteText,
  ] = match;
  const offsetMinutes = parseOffsetMinutes(
    timezoneText,
    offsetSign,
    offsetHourText,
    offsetMinuteText,
    isoDate
  );
  const parts = {
    day: Number(dayText),
    hour: Number(hourText),
    minute: Number(minuteText),
    month: Number(monthText),
    offsetMinutes,
    year: Number(yearText),
  };
  const date = new Date(
    Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute)
  );
  if (isInvalidScheduleDate(date, parts)) {
    throw new CommunityDomError(
      `予約日時が不正、または15分単位ではありません: ${isoDate}`
    );
  }
  return parts;
}

function parseOffsetMinutes(
  timezoneText: string,
  offsetSign: string | undefined,
  offsetHourText: string | undefined,
  offsetMinuteText: string | undefined,
  isoDate: string
): number {
  if (timezoneText === "Z") {
    return 0;
  }
  const hours = Number(offsetHourText);
  const minutes = Number(offsetMinuteText);
  const invalid = hours > 14 || minutes > 59 || (hours === 14 && minutes !== 0);
  if (invalid) {
    throw new CommunityDomError(
      `予約日時の timezone offset が不正です: ${isoDate}`
    );
  }
  return (offsetSign === "-" ? -1 : 1) * (hours * 60 + minutes);
}

function isInvalidScheduleDate(date: Date, parts: ScheduleParts): boolean {
  const datePartsMatch =
    date.getUTCFullYear() === parts.year &&
    date.getUTCMonth() === parts.month - 1 &&
    date.getUTCDate() === parts.day;
  const timeIsValid =
    parts.hour <= 23 && parts.minute <= 59 && parts.minute % 15 === 0;
  return !(datePartsMatch && timeIsValid);
}

function resolvePickerOffsetMinutes(form: ParentNode): number {
  const picker = resolveUniqueVisible<HTMLElement>(
    form,
    "ytd-date-time-picker-renderer #timezone-picker",
    "picker timezone"
  );
  const match = /GMT([+-])(\d{2})(\d{2})/.exec(picker.textContent ?? "");
  if (!match) {
    throw new CommunityDomError("picker timezone offset を読み取れません");
  }
  const [, sign, hourText, minuteText] = match;
  const hours = Number(hourText);
  const minutes = Number(minuteText);
  if (hours > 14 || minutes > 59 || (hours === 14 && minutes !== 0)) {
    throw new CommunityDomError("picker timezone offset が不正です");
  }
  return (sign === "-" ? -1 : 1) * (hours * 60 + minutes);
}

function assertPickerTimezone(form: ParentNode, parts: ScheduleParts): void {
  const pickerOffset = resolvePickerOffsetMinutes(form);
  if (pickerOffset !== parts.offsetMinutes) {
    throw new CommunityDomError(
      `予約日時と picker の timezone が一致しません: payload=${parts.offsetMinutes}, picker=${pickerOffset}`
    );
  }
}

async function resolveTargetMonth(
  form: ParentNode,
  parts: ScheduleParts,
  now: Date,
  currentPickerOffsetMinutes: number
): Promise<HTMLElement> {
  const months = queryAll<HTMLElement>(form, CALENDAR_MONTH_SELECTOR);
  const todayIndex = months.findIndex((month) =>
    month.querySelector(".calendar-day.today")
  );
  if (todayIndex < 0) {
    throw new CommunityDomError("calendar の today month を解決できません");
  }
  const pickerNow = new Date(
    now.getTime() + currentPickerOffsetMinutes * 60_000
  );
  if (Number.isNaN(pickerNow.getTime())) {
    throw new CommunityDomError("現在日時が不正です");
  }
  const delta =
    (parts.year - pickerNow.getUTCFullYear()) * 12 +
    (parts.month - 1 - pickerNow.getUTCMonth());
  const target = months[todayIndex + delta];
  if (target) {
    return target;
  }
  if (delta === 0) {
    throw new CommunityDomError(
      `対象月が calendar の描画範囲外です: monthOffset=${delta}`
    );
  }
  const direction = delta > 0 ? "next" : "prev";
  const button = resolveUniqueVisible<HTMLElement>(
    form,
    `ytd-calendar-date-picker #${direction}-month button`,
    `${direction} month button`
  );
  for (let count = 0; count < Math.abs(delta); count += 1) {
    const before = queryAll<HTMLElement>(form, CALENDAR_MONTH_SELECTOR).map(
      (month) => ({ month, text: month.textContent })
    );
    button.click();
    await waitForCondition(
      form,
      () => {
        const after = queryAll<HTMLElement>(form, CALENDAR_MONTH_SELECTOR);
        return (
          after.length !== before.length ||
          after.some(
            (month, index) =>
              month !== before[index]?.month ||
              month.textContent !== before[index]?.text
          )
        );
      },
      `${direction} month の Polymer state 反映`
    );
  }
  const container = resolveUniqueVisible<HTMLElement>(
    form,
    "ytd-calendar-date-picker .calendar-container",
    "calendar viewport"
  );
  const viewportTop = container.getBoundingClientRect().top;
  const activeMonths = queryAll<HTMLElement>(
    form,
    CALENDAR_MONTH_SELECTOR
  ).filter((month) => {
    const rect = month.getBoundingClientRect();
    return (
      isVisible(month) && rect.top <= viewportTop && rect.bottom > viewportTop
    );
  });
  if (activeMonths.length !== 1) {
    throw new CommunityDomError(
      `移動後の active month を一意に解決できません: count=${activeMonths.length}`
    );
  }
  return activeMonths[0];
}

export function resolveCommunityTextField(
  root: ParentNode = document
): HTMLElement {
  return resolveUniqueVisible(
    resolveCommentbox(resolveForm(root)),
    TEXT_FIELD_SELECTOR,
    "コミュニティ投稿本文"
  );
}

function readEditorText(editor: HTMLElement): string {
  return editor instanceof HTMLInputElement ||
    editor instanceof HTMLTextAreaElement
    ? editor.value
    : (editor.textContent ?? "");
}

export async function setCommunityText(
  text: string,
  root: ParentNode = document
): Promise<void> {
  const form = resolveForm(root);
  const editor = resolveCommunityTextField(root);
  editor.focus();
  if (
    editor instanceof HTMLInputElement ||
    editor instanceof HTMLTextAreaElement
  ) {
    const prototype =
      editor instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : HTMLTextAreaElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (!setter) {
      throw new CommunityDomError(
        "投稿本文の native value setter がありません"
      );
    }
    setter.call(editor, text);
  } else {
    editor.textContent = text;
  }
  editor.dispatchEvent(
    new InputEvent("input", {
      bubbles: true,
      data: text || null,
      inputType: text ? "insertText" : "deleteContentBackward",
    })
  );
  await waitForCondition(
    form,
    () => {
      const submit = queryAll<HTMLButtonElement>(
        resolveCommentbox(form),
        POST_BUTTON_SELECTOR
      )[0];
      const submitMatches = submit
        ? text
          ? !submit.disabled && submit.getAttribute("aria-disabled") !== "true"
          : submit.disabled || submit.getAttribute("aria-disabled") === "true"
        : true;
      return readEditorText(editor) === text && submitMatches;
    },
    "投稿本文の Polymer state 反映"
  );
}

export function resolveImageUploadInput(
  root: ParentNode = document
): HTMLInputElement {
  return resolveUnique(
    resolveCommentbox(resolveForm(root)),
    IMAGE_INPUT_SELECTOR,
    "コミュニティ投稿画像 input"
  );
}

export async function attachImage(
  blob: Blob,
  filename: string,
  root: ParentNode = document,
  timeoutMs = DEFAULT_WAIT_TIMEOUT_MS
): Promise<void> {
  if (!(blob.type.startsWith("image/") && filename.trim())) {
    throw new CommunityDomError(
      "投稿画像には image MIME とファイル名が必要です"
    );
  }
  const form = resolveForm(root);
  const commentbox = resolveCommentbox(form);
  const input = resolveImageUploadInput(root);
  const thumbnailsBefore = new Map(
    queryAll<HTMLImageElement>(commentbox, IMAGE_THUMBNAIL_SELECTOR).map(
      (thumbnail) => [thumbnail, thumbnail.src]
    )
  );
  const transfer = new DataTransfer();
  transfer.items.add(new File([blob], filename, { type: blob.type }));
  input.files = transfer.files;
  if (
    input.files?.length !== 1 ||
    input.files[0].name !== filename ||
    input.files[0].type !== blob.type
  ) {
    throw new CommunityDomError(
      "投稿画像の file input readback に失敗しました"
    );
  }
  input.dispatchEvent(new Event("change", { bubbles: true }));
  let verifiedThumbnail: HTMLImageElement | undefined;
  await waitForCondition(
    commentbox,
    () => {
      verifiedThumbnail = queryAll<HTMLImageElement>(
        commentbox,
        IMAGE_THUMBNAIL_SELECTOR
      ).find(
        (thumbnail) =>
          Boolean(thumbnail.src) &&
          thumbnailsBefore.get(thumbnail) !== thumbnail.src
      );
      return Boolean(verifiedThumbnail);
    },
    "投稿画像 thumbnail",
    timeoutMs
  );
  if (!verifiedThumbnail) {
    throw new CommunityDomError("投稿画像 thumbnail を検証できません");
  }
  verifiedImages.set(form, {
    filename,
    mimeType: blob.type,
    src: verifiedThumbnail.src,
    thumbnail: verifiedThumbnail,
  });
}

export async function openSchedulePicker(
  root: ParentNode = document
): Promise<void> {
  const form = resolveForm(root);
  const commentbox = resolveCommentbox(form);
  resolveUniqueVisible<HTMLButtonElement>(
    commentbox,
    OPERATION_MENU_SELECTOR,
    "投稿操作メニュー"
  ).click();
  await waitForCondition(
    root,
    () => queryAll<HTMLElement>(root, MENU_ITEM_SELECTOR).some(isVisible),
    "投稿操作メニュー項目の表示"
  );
  const scheduleItems = queryAll<HTMLElement>(root, MENU_ITEM_SELECTOR).filter(
    (item) =>
      isVisible(item) &&
      item.getAttribute("aria-disabled") !== "true" &&
      !item.hasAttribute("disabled") &&
      !item.querySelector('[disabled], [aria-disabled="true"]') &&
      /投稿のスケジュールを設定|schedule (?:post|publication)/i.test(
        item.textContent?.trim() ?? ""
      )
  );
  if (scheduleItems.length !== 1) {
    throw new CommunityDomError(
      `schedule menu item を一意に解決できません: count=${scheduleItems.length}`
    );
  }
  const [scheduleItem] = scheduleItems;
  scheduleItem.click();
  await waitForUniqueVisible(
    commentbox,
    SCHEDULE_PANEL_SELECTOR,
    "日時 picker"
  );
}

export async function setScheduleDateTime(
  isoDate: string,
  root: ParentNode = document,
  now: Date = new Date()
): Promise<void> {
  const parts = parseScheduleParts(isoDate);
  const form = resolveForm(root);
  const commentbox = resolveCommentbox(form);
  resolveUniqueVisible(commentbox, SCHEDULE_PANEL_SELECTOR, "日時 picker");
  const currentPickerOffsetMinutes = resolvePickerOffsetMinutes(commentbox);

  resolveUniqueVisible<HTMLElement>(
    commentbox,
    "ytd-calendar-date-picker #date-picker",
    "日付 picker"
  ).click();
  await waitForUniqueVisible<HTMLElement>(
    commentbox,
    "ytd-calendar-date-picker .calendar-container",
    "calendar viewport"
  );

  const month = await resolveTargetMonth(
    commentbox,
    parts,
    now,
    currentPickerOffsetMinutes
  );
  const days = [...month.querySelectorAll<HTMLElement>(".calendar-day")].filter(
    (day) =>
      !day.classList.contains("disabled") &&
      !day.classList.contains("invisible") &&
      day.textContent?.trim() === String(parts.day)
  );
  if (days.length !== 1) {
    throw new CommunityDomError(
      `対象日を一意に解決できません: day=${parts.day}, count=${days.length}`
    );
  }
  const dateLabel = resolveUnique<HTMLElement>(
    commentbox,
    "ytd-calendar-date-picker #date-label-text",
    "日付 label"
  );
  const dateLabelBefore = dateLabel.textContent;
  const dateWasSelected = days[0].classList.contains("selected");
  days[0].click();
  await waitForCondition(
    commentbox,
    () =>
      days[0].classList.contains("selected") &&
      (dateWasSelected || dateLabel.textContent !== dateLabelBefore) &&
      !queryAll<HTMLElement>(
        commentbox,
        'ytd-calendar-date-picker [invalid], ytd-calendar-date-picker [aria-invalid="true"]'
      ).some(isVisible),
    "日付の Polymer state 反映"
  );
  assertPickerTimezone(commentbox, parts);

  resolveUniqueVisible<HTMLElement>(
    commentbox,
    "ytd-date-time-picker-renderer #time-picker",
    "時刻 picker"
  ).click();
  await waitForCondition(
    commentbox,
    () =>
      queryAll<HTMLElement>(commentbox, TIME_OPTION_SELECTOR).filter(isVisible)
        .length === TIME_OPTION_COUNT,
    "時刻 option の表示"
  );
  const options = queryAll<HTMLElement>(
    commentbox,
    TIME_OPTION_SELECTOR
  ).filter(isVisible);
  if (options.length !== TIME_OPTION_COUNT) {
    throw new CommunityDomError(
      `時刻 option 数が不正です: expected=${TIME_OPTION_COUNT}, actual=${options.length}`
    );
  }
  const optionIndex = parts.hour * 4 + parts.minute / 15;
  const timeLabel = resolveUnique<HTMLElement>(
    commentbox,
    "ytd-date-time-picker-renderer #time-label-text",
    "時刻 label"
  );
  const timeLabelBefore = timeLabel.textContent;
  const timeWasSelected =
    options[optionIndex].getAttribute("aria-selected") === "true";
  options[optionIndex].click();
  await waitForCondition(
    commentbox,
    () =>
      options[optionIndex].getAttribute("aria-selected") === "true" &&
      (timeWasSelected || timeLabel.textContent !== timeLabelBefore),
    "時刻の Polymer state 反映"
  );
  verifiedSchedules.set(form, {
    isoDate,
    selectedDay: days[0],
    selectedOption: options[optionIndex],
    targetMonth: parts.month,
    targetYear: parts.year,
  });
}

export function resolvePostButton(
  root: ParentNode = document
): HTMLButtonElement {
  return resolveUniqueVisible(
    resolveCommentbox(resolveForm(root)),
    POST_BUTTON_SELECTOR,
    "投稿確定ボタン"
  );
}

function assertScheduleReadback(
  form: HTMLElement,
  commentbox: HTMLElement,
  expectedIsoDate: string,
  parts: ScheduleParts
): void {
  const verified = verifiedSchedules.get(form);
  if (!verified) {
    throw new CommunityDomError("予約日の readback が payload と一致しません");
  }
  assertDateReadback(verified, expectedIsoDate, parts);
  assertTimeReadback(verified, commentbox, parts);
}

function assertDateReadback(
  verified: VerifiedSchedule,
  expectedIsoDate: string,
  parts: ScheduleParts
): void {
  const identityMatches =
    verified.isoDate === expectedIsoDate &&
    verified.targetYear === parts.year &&
    verified.targetMonth === parts.month;
  const selectedDayMatches =
    verified.selectedDay.isConnected &&
    verified.selectedDay.classList.contains("selected") &&
    verified.selectedDay.textContent?.trim() === String(parts.day);
  if (!(identityMatches && selectedDayMatches)) {
    throw new CommunityDomError("予約日の readback が payload と一致しません");
  }
}

function assertTimeReadback(
  verified: VerifiedSchedule,
  commentbox: HTMLElement,
  parts: ScheduleParts
): void {
  const selectedOptions = queryAll<HTMLElement>(
    commentbox,
    `${TIME_OPTION_SELECTOR}[aria-selected="true"]`
  );
  const allOptions = queryAll<HTMLElement>(commentbox, TIME_OPTION_SELECTOR);
  const optionIndex = parts.hour * 4 + parts.minute / 15;
  const timeMatches =
    selectedOptions.length === 1 &&
    allOptions.indexOf(selectedOptions[0]) === optionIndex &&
    selectedOptions[0] === verified.selectedOption &&
    verified.selectedOption.isConnected;
  if (!timeMatches) {
    throw new CommunityDomError(
      "予約時刻の readback が payload と一致しません"
    );
  }
}

function assertImageReadback(
  form: HTMLElement,
  commentbox: HTMLElement,
  expectedFilename: string | null
): void {
  const verified = verifiedImages.get(form);
  const thumbnails = queryAll<HTMLImageElement>(
    commentbox,
    IMAGE_THUMBNAIL_SELECTOR
  );
  const matches = expectedFilename
    ? verified?.filename === expectedFilename &&
      verified.thumbnail.isConnected &&
      verified.thumbnail.src === verified.src &&
      thumbnails.includes(verified.thumbnail)
    : !verified && thumbnails.length === 0;
  if (!matches) {
    throw new CommunityDomError(
      "投稿画像の readback が payload と一致しません"
    );
  }
}

function isCompletedReset(
  form: HTMLElement,
  commentbox: HTMLElement,
  button: HTMLButtonElement,
  editor: HTMLElement
): boolean {
  const collapsed =
    commentbox.hasAttribute("hidden") ||
    getComputedStyle(commentbox).display === "none";
  const nodesRemainConnected =
    form.isConnected &&
    commentbox.isConnected &&
    button.isConnected &&
    editor.isConnected;
  return (
    nodesRemainConnected &&
    collapsed &&
    button.disabled &&
    readEditorText(editor) === ""
  );
}

export async function clickPost(
  expected: ExpectedCommunityPostState,
  root: ParentNode = document,
  timeoutMs = DEFAULT_WAIT_TIMEOUT_MS
): Promise<void> {
  const form = resolveForm(root);
  const commentbox = resolveCommentbox(form);
  const button = resolvePostButton(root);
  const editor = resolveCommunityTextField(root);
  const parts = parseScheduleParts(expected.scheduledAt);
  assertPickerTimezone(commentbox, parts);
  resolveUniqueVisible(commentbox, SCHEDULE_PANEL_SELECTOR, "日時 picker");
  if (readEditorText(editor) !== expected.text) {
    throw new CommunityDomError(
      "投稿本文の readback が payload と一致しません"
    );
  }
  assertScheduleReadback(form, commentbox, expected.scheduledAt, parts);
  assertImageReadback(form, commentbox, expected.imageFilename);
  if (button.disabled || button.getAttribute("aria-disabled") === "true") {
    throw new CommunityDomError("投稿確定ボタンが無効です");
  }
  button.click();
  await waitForCondition(
    root,
    () => isCompletedReset(form, commentbox, button, editor),
    "投稿フォームの reset",
    timeoutMs
  );
}
