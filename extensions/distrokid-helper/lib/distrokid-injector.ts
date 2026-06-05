// distrokid.com/new フォームへの注入ロジック（#866 で実機 DOM 再検証）。
//
// 静的プロファイル / album / release date / 曲 / songwriter / cover は #813 の id ベース
// セレクタを継続。AI 開示は #866 で fixture-driven な想像 selector（#ai-yes / #ai-modal /
// [name^="ai_lyrics_"] / apply-all checkbox / save button）が実 DOM と完全に乖離していたこと
// が判明したため、実 DOM 準拠の uuid-driven 関数群に置換した:
//   - 「はい/いいえ」: [name="ai_gate_<uuid>"][value="0"|"1"] radio
//   - 歌詞 / 作曲: [name="ai_lyrics_<uuid>"] / [name="ai_music_<uuid>"] checkbox（display:none で隠れる）
//   - 部分的 AI 音声: [name="ai_partial_audio_type_<uuid>"][value="vocals"|"instruments"] radio
//   - apply_to_all checkbox は実 DOM に存在しない → 全 track をループで個別注入することで代替
//
// テキスト / SELECT 注入は React 互換のネイティブ value setter + bubbling イベントで行う
// （React の制御要素は value を直接書き換えても onChange が走らないため、prototype の
//  native setter で React の value tracker を欺く）。ファイル注入（DataTransfer 経由）は
// jsdom 非対応のため Playwright が担保する。
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

// AI 開示の uuid-driven セレクタ群（実 DOM 検証 #866 に基づく）。
// 全 track の uuid は resolveTrackUuids() で title_<uuid> input から DOM order に解決する。
export const AI_DISCLOSURE_SELECTORS = {
  // 「はい / いいえ」radio。デフォルトは「いいえ (value=0)」が checked。
  gateByUuid: (uuid: string) => ({
    no: `[name="ai_gate_${uuid}"][value="0"]`,
    yes: `[name="ai_gate_${uuid}"][value="1"]`,
  }),
  // 「はい」選択時に展開される歌詞 / 作曲 checkbox（initial は display:none の親に隠れている）。
  lyricsByUuid: (uuid: string) => `[name="ai_lyrics_${uuid}"]`,
  compositionByUuid: (uuid: string) => `[name="ai_music_${uuid}"]`,
  // 部分的 AI 音声の種別 radio。100% AI 楽曲では選ばない（partial_audio_type=null）。
  partialAudioTypeByUuid: (uuid: string, type: "vocals" | "instruments") =>
    `[name="ai_partial_audio_type_${uuid}"][value="${type}"]`,
} as const;

// 新規リリース前提の assert 対象（previouslyReleased「いいえ(value=0)」）。
export const NEW_RELEASE_RADIO_SELECTOR = '[name^="previouslyReleased_"][value="0"]';

// track タイトル input の name 接頭辞（DOM order で uuid を列挙する基点）。
const TITLE_NAME_PREFIX = "title_";
const TITLE_NAME_SELECTOR = `[name^="${TITLE_NAME_PREFIX}"]`;

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

// radio / checkbox を目標状態へ合わせる。click で React 互換に checked 切替 + change を発火する。
// 既に目標状態なら no-op（重複 click を避ける）。
function setChecked(el: HTMLInputElement, checked: boolean): void {
  if (el.checked !== checked) {
    el.click();
  }
}

function requireInput(root: ParentNode, selector: string): HTMLInputElement {
  const el = root.querySelector<HTMLInputElement>(selector);
  if (el === null) {
    throw new FieldNotFoundError(selector);
  }
  return el;
}

// 1 track 分の AI 開示を注入する（全 track 共通の ai 設定を適用）。
//
// 実 DOM では「はい」radio click 時点で歌詞 / 作曲 / partial_audio_type の親 div の
// display:none が外れる仕掛けだが、checkbox / radio 自体は最初から DOM 内にあるため、
// MutationObserver で展開待ちする必要はない（hidden な checkbox に対する el.click() も
// React 制御コンポーネントには届く）。
function injectAiDisclosureForTrack(root: ParentNode, uuid: string, ai: AiDisclosure): void {
  const gate = AI_DISCLOSURE_SELECTORS.gateByUuid(uuid);
  setChecked(requireInput(root, ai.enabled ? gate.yes : gate.no), true);
  if (!ai.enabled) {
    return;
  }
  setChecked(requireInput(root, AI_DISCLOSURE_SELECTORS.lyricsByUuid(uuid)), ai.lyrics);
  setChecked(requireInput(root, AI_DISCLOSURE_SELECTORS.compositionByUuid(uuid)), ai.composition);
  if (ai.partial_audio_type !== null) {
    setChecked(
      requireInput(
        root,
        AI_DISCLOSURE_SELECTORS.partialAudioTypeByUuid(uuid, ai.partial_audio_type),
      ),
      true,
    );
  }
}

// AI 開示注入: 全 track の uuid を DOM order で解決し、各 track に同じ ai 設定を適用する。
// enabled=false でも各 track の「いいえ」radio を明示的に確定させる（人手 default に頼らない）。
export function injectAiDisclosure(root: ParentNode, ai: AiDisclosure): void {
  const uuids = resolveTrackUuids(root);
  if (uuids.length === 0) {
    throw new FieldNotFoundError(TITLE_NAME_SELECTOR);
  }
  for (const uuid of uuids) {
    injectAiDisclosureForTrack(root, uuid, ai);
  }
}
