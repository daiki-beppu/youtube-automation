// distrokid.com/new フォームへの注入ロジック（#813 で実 DOM 検証に基づき刷新）。
//
// セレクタは PR #803 の想像 name 属性ベースを撤廃し、実 DOM の id ベースへ刷新した
// （order.md「実 DOM 検証の証跡」参照）。track 系は index / uuid から生成する。
//
// テキスト / SELECT 注入は React 互換のネイティブ value setter + bubbling イベントで行う
// （React の制御要素は value を直接書き換えても onChange が走らないため、prototype の
//  native setter で React の value tracker を欺く）。ファイル注入（DataTransfer 経由）と
// AI 開示モーダルの展開待ち（MutationObserver）は jsdom 非対応のため Playwright が担保する。
//
// 隠し要素（type=hidden の #artistName 等）はテキスト/SELECT 解決時に isVisible で排除する。
// 注入先が見つからない場合は silent skip せず FieldNotFoundError で fail-loud。
// 送信系ボタン（「続ける」）は一切操作しない（規約遵守・スコープ外）。

import { isVisible } from "../../shared/visibility";
import type { AiDisclosure, DistrokidProfile, SongwriterName } from "./types";

// 静的プロファイルの SELECT 注入先（id ベース）。
export const PROFILE_SELECTORS = {
  language: "#language",
  main_genre: "#genrePrimary",
  sub_genre: "#genreSecondary",
} as const;

// アルバム名（アルバム時のみ存在。シングルモードでは要素不在 → skip）。
export const ALBUM_SELECTORS = {
  album_title: "#albumTitleInput",
} as const;

// リリース日（name="releaseDate" / type=date）。
export const RELEASE_DATE_SELECTOR = "#release-date-dp";

// ファイル注入先（ジャケット + track 別アップロード）。track は 1-indexed。
export const FILE_SELECTORS = {
  cover: "#artwork",
  trackByIndex: (i1: number) => `#js-track-upload-${i1}`,
} as const;

// track 別フィールド。タイトルは DOM order で解決した uuid、songwriter は 3 分割（1-indexed）。
export const TRACK_FIELD_SELECTORS = {
  titleByUuid: (uuid: string) => `[name="title_${uuid}"]`,
  songwriterByIndex: (i1: number) => ({
    first: `[name="songwriter_real_name_first${i1}"]`,
    middle: `[name="songwriter_real_name_middle${i1}"]`,
    last: `[name="songwriter_real_name_last${i1}"]`,
  }),
} as const;

// AI 開示フローの契約セレクタ（実 DOM 検証サマリ + tests/e2e fixture に基づく）。
export const AI_DISCLOSURE_SELECTORS = {
  yesRadio: "#ai-yes",
  modal: "#ai-modal",
  lyrics: '[name^="ai_lyrics_"]',
  music: '[name^="ai_music_"]',
  applyAll: '[id^="ai-apply-all-"]',
  saveButton: "#ai-save",
} as const;

// 新規リリース前提の assert 対象（previouslyReleased「いいえ(value=0)」）。
export const NEW_RELEASE_RADIO_SELECTOR = '[name^="previouslyReleased_"][value="0"]';

// track タイトル input の name 接頭辞（DOM order で uuid を列挙する基点）。
const TITLE_NAME_PREFIX = "title_";
const TITLE_NAME_SELECTOR = `[name^="${TITLE_NAME_PREFIX}"]`;

// AI モーダルの展開待ち上限 (ms)。MutationObserver が拾えなければ timeout で fail-loud。
export const AI_MODAL_TIMEOUT_MS = 5000;

// 注入先フィールドが見つからないことを表す専用エラー。
// silent skip せず fail-loud にすることで DistroKid の UI 変更を即座に検知する。
export class FieldNotFoundError extends Error {
  constructor(selector: string) {
    super(`注入先フィールドが見つかりません: ${selector}`);
    this.name = "FieldNotFoundError";
  }
}

type ValueElement = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

// 要素種別に応じた prototype から native value setter を取り出す。
function nativeValueSetter(el: ValueElement): (value: string) => void {
  const prototype =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  if (!descriptor?.set) {
    throw new Error("native value setter を解決できません");
  }
  const setter = descriptor.set;
  return (value: string) => setter.call(el, value);
}

// native setter で値をセットし、input / change を bubbles:true で発火する（React 互換）。
export function setNativeValue(el: ValueElement, value: string): void {
  nativeValueSetter(el)(value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

// セレクタに一致する可視のテキスト/SELECT 要素を返す（無ければ null）。
// type=hidden や祖先 display:none の隠し要素を isVisible で排除する。
function findVisibleField(root: ParentNode, selector: string): ValueElement | null {
  return (
    Array.from(root.querySelectorAll<ValueElement>(selector)).filter(isVisible)[0] ?? null
  );
}

// 可視要素を要求する。未検出（または隠し要素のみ）なら fail-loud。
function requireVisibleField(root: ParentNode, selector: string): ValueElement {
  const el = findVisibleField(root, selector);
  if (el === null) {
    throw new FieldNotFoundError(selector);
  }
  return el;
}

// 静的プロファイル（language / main_genre 必須、sub_genre は任意）を注入する。
export function injectProfile(root: ParentNode, profile: DistrokidProfile): void {
  setNativeValue(requireVisibleField(root, PROFILE_SELECTORS.language), profile.language);
  setNativeValue(requireVisibleField(root, PROFILE_SELECTORS.main_genre), profile.main_genre);
  if (profile.sub_genre !== null) {
    setNativeValue(requireVisibleField(root, PROFILE_SELECTORS.sub_genre), profile.sub_genre);
  }
}

// アルバム名を注入する。album_title 欄はアルバム時のみ存在するため、不在なら skip（シングルモード）。
export function injectAlbumTitle(root: ParentNode, albumTitle: string): void {
  const el = findVisibleField(root, ALBUM_SELECTORS.album_title);
  if (el !== null) {
    setNativeValue(el, albumTitle);
  }
}

// リリース日を注入する（未確定 = null なら注入しない）。
export function injectReleaseDate(root: ParentNode, releaseDate: string | null): void {
  if (releaseDate === null) {
    return;
  }
  setNativeValue(requireVisibleField(root, RELEASE_DATE_SELECTOR), releaseDate);
}

// track タイトル input を DOM order で列挙し uuid 一覧を返す（track の解決基点）。
// セレクタが name^="title_" を保証するため el.name は常に接頭辞付きの非空文字列。
export function resolveTrackUuids(root: ParentNode): string[] {
  return Array.from(root.querySelectorAll<HTMLInputElement>(TITLE_NAME_SELECTOR)).map((el) =>
    el.name.slice(TITLE_NAME_PREFIX.length),
  );
}

// 指定 uuid の track タイトルを注入する。
export function injectTrackTitle(root: ParentNode, uuid: string, title: string): void {
  setNativeValue(requireVisibleField(root, TRACK_FIELD_SELECTORS.titleByUuid(uuid)), title);
}

// 指定 track（1-indexed）に songwriter（3 分割）を注入する。middle は null なら skip。
export function injectSongwriter(
  root: ParentNode,
  index1: number,
  songwriter: SongwriterName,
): void {
  const sel = TRACK_FIELD_SELECTORS.songwriterByIndex(index1);
  setNativeValue(requireVisibleField(root, sel.first), songwriter.first);
  setNativeValue(requireVisibleField(root, sel.last), songwriter.last);
  if (songwriter.middle !== null) {
    setNativeValue(requireVisibleField(root, sel.middle), songwriter.middle);
  }
}

// <input type=file> へ DataTransfer 経由で File をセットし change を bubbles:true で発火する。
// （jsdom 非対応のため Playwright E2E でのみ検証される）
export function injectFile(input: HTMLInputElement, file: File): void {
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

// file input は hidden（#artwork / pre-mount track input）のため isVisible は適用しない。
function requireFileInput(root: ParentNode, selector: string): HTMLInputElement {
  const input = root.querySelector<HTMLInputElement>(selector);
  if (input === null) {
    throw new FieldNotFoundError(selector);
  }
  return input;
}

// 指定 track（1-indexed）に曲ファイルを注入する。
export function injectTrackFile(root: ParentNode, index1: number, file: File): void {
  injectFile(requireFileInput(root, FILE_SELECTORS.trackByIndex(index1)), file);
}

// ジャケットを注入する。
export function injectCover(root: ParentNode, file: File): void {
  injectFile(requireFileInput(root, FILE_SELECTORS.cover), file);
}

// 新規リリース前提（previouslyReleased が「いいえ(value=0)」で checked）を assert する。
// 過去公開リリースへの対応はスコープ外（別 issue）のため、想定外なら fail-loud。
export function assertNewRelease(root: ParentNode): void {
  const noRadios = Array.from(
    root.querySelectorAll<HTMLInputElement>(NEW_RELEASE_RADIO_SELECTOR),
  );
  if (noRadios.length === 0) {
    throw new FieldNotFoundError(NEW_RELEASE_RADIO_SELECTOR);
  }
  if (!noRadios.every((radio) => radio.checked)) {
    throw new Error(
      "previouslyReleased が「いいえ(新規)」で checked ではありません（過去公開対応はスコープ外）",
    );
  }
}

// MutationObserver で要素の出現を待つ（polling ではなく変更通知で検知）。
function waitForElement(
  root: ParentNode,
  selector: string,
  timeoutMs: number,
): Promise<HTMLElement> {
  const existing = root.querySelector<HTMLElement>(selector);
  if (existing !== null) {
    return Promise.resolve(existing);
  }
  // Document はそのまま、Element はその要素を subtree 監視する（content では document を渡す）。
  const observeTarget: Node = root instanceof Document ? root : (root as Element);
  return new Promise((resolve, reject) => {
    const observer = new MutationObserver(() => {
      const found = root.querySelector<HTMLElement>(selector);
      if (found !== null) {
        observer.disconnect();
        clearTimeout(timer);
        resolve(found);
      }
    });
    const timer = setTimeout(() => {
      observer.disconnect();
      reject(new FieldNotFoundError(selector));
    }, timeoutMs);
    observer.observe(observeTarget, { childList: true, subtree: true });
  });
}

function requireCheckbox(root: ParentNode, selector: string): HTMLInputElement {
  const el = root.querySelector<HTMLInputElement>(selector);
  if (el === null) {
    throw new FieldNotFoundError(selector);
  }
  return el;
}

// checkbox を目標状態へ合わせる。click で React 互換に checked 切替 + change を発火する。
function setCheckbox(el: HTMLInputElement, checked: boolean): void {
  if (el.checked !== checked) {
    el.click();
  }
}

// AI 開示フロー: 「はい」radio → モーダル待機 → checkbox 注入 → 「保存する」commit。
// enabled=false なら何もしない（Suno 以外の人手素材チャンネル等）。
export async function injectAiDisclosure(root: ParentNode, ai: AiDisclosure): Promise<void> {
  if (!ai.enabled) {
    return;
  }
  // 「はい」を選択するとモーダルが展開する（送信系ではない）。
  const yesRadio = root.querySelector<HTMLInputElement>(AI_DISCLOSURE_SELECTORS.yesRadio);
  if (yesRadio === null) {
    throw new FieldNotFoundError(AI_DISCLOSURE_SELECTORS.yesRadio);
  }
  yesRadio.click();

  const modal = await waitForElement(root, AI_DISCLOSURE_SELECTORS.modal, AI_MODAL_TIMEOUT_MS);

  setCheckbox(requireCheckbox(modal, AI_DISCLOSURE_SELECTORS.lyrics), ai.lyrics);
  setCheckbox(requireCheckbox(modal, AI_DISCLOSURE_SELECTORS.music), ai.composition);

  // 「音声すべて / 音声の一部」は name 属性なし → モーダル内 checkbox の DOM order で識別する
  // （order: [歌詞, 作曲, 音声すべて, 音声の一部, apply_all] の 3・4 番目）。
  const checkboxes = Array.from(
    modal.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
  );
  const fullAudio = checkboxes[2];
  const partialAudio = checkboxes[3];
  if (fullAudio === undefined || partialAudio === undefined) {
    throw new FieldNotFoundError(`${AI_DISCLOSURE_SELECTORS.modal} の音声 AI checkbox`);
  }
  setCheckbox(fullAudio, ai.full_audio);
  setCheckbox(partialAudio, ai.partial_audio);

  setCheckbox(requireCheckbox(modal, AI_DISCLOSURE_SELECTORS.applyAll), ai.apply_to_all);

  // モーダル内 commit（wizard 進行ではないので規約 OK）。
  const save = modal.querySelector<HTMLButtonElement>(AI_DISCLOSURE_SELECTORS.saveButton);
  if (save === null) {
    throw new FieldNotFoundError(AI_DISCLOSURE_SELECTORS.saveButton);
  }
  save.click();
}
