// distrokid.com/new フォームへの注入ロジック。
//
// テキスト注入は React 互換のネイティブ value setter + bubbling イベントで行う
// （React の制御 input は value プロパティを直接書き換えても onChange が走らないため、
//  prototype の native setter を使って React の value tracker を欺く）。
// ファイル注入（DataTransfer 経由）は jsdom 非対応のため Playwright が担保する。
//
// 送信系ボタン（「続ける」）は一切操作しない（規約遵守・要件 #7）。

import type { DistrokidProfile, ReleaseData, ReleasePayload } from "./types";

// 静的プロファイル 6 項目の注入先セレクタ（name 属性ベース）。
// distrokid.com の実 DOM 変更時はここを更新する（README の保守手順参照）。
export const PROFILE_SELECTORS: Record<keyof DistrokidProfile, string> = {
  artist_name: '[name="artist_name"]',
  language: '[name="language"]',
  main_genre: '[name="main_genre"]',
  songwriter: '[name="songwriter"]',
  apple_music_credit: '[name="apple_music_credit"]',
  track_type: '[name="track_type"]',
};

// 動的リリースデータのテキスト注入先セレクタ。
export const RELEASE_SELECTORS = {
  album_title: '[name="album_title"]',
  release_date: '[name="release_date"]',
} as const;

// ファイル注入先セレクタ（曲 / ジャケット）。
export const FILE_SELECTORS = {
  song_file: '[name="song_file"]',
  cover_file: '[name="cover_file"]',
} as const;

// 注入先フィールドが見つからないことを表す専用エラー。
// silent skip せず fail-loud にすることで DistroKid の UI 変更を即座に検知する。
export class FieldNotFoundError extends Error {
  constructor(selector: string) {
    super(`注入先フィールドが見つかりません: ${selector}`);
    this.name = "FieldNotFoundError";
  }
}

type ValueElement = HTMLInputElement | HTMLTextAreaElement;

// 要素種別に応じた prototype から native value setter を取り出す。
function nativeValueSetter(el: ValueElement): (value: string) => void {
  const prototype =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
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

// セレクタで value 要素を解決する。未検出なら fail-loud。
function requireField(root: ParentNode, selector: string): ValueElement {
  const el = root.querySelector<ValueElement>(selector);
  if (el === null) {
    throw new FieldNotFoundError(selector);
  }
  return el;
}

// 静的プロファイル 6 項目を全注入する。1 つでも欠ければ FieldNotFoundError。
export function injectProfile(
  root: ParentNode,
  profile: DistrokidProfile,
): void {
  for (const key of Object.keys(PROFILE_SELECTORS) as (keyof DistrokidProfile)[]) {
    const el = requireField(root, PROFILE_SELECTORS[key]);
    setNativeValue(el, profile[key]);
  }
}

// 動的リリースのテキスト（album_title 必須 / release_date は null ならスキップ）を注入する。
export function injectRelease(root: ParentNode, release: ReleaseData): void {
  const albumEl = requireField(root, RELEASE_SELECTORS.album_title);
  setNativeValue(albumEl, release.album_title);

  // release_date は null がデータ仕様上の正常値（未確定）。null なら注入欄の有無に関わらずスキップ。
  if (release.release_date !== null) {
    const dateEl = requireField(root, RELEASE_SELECTORS.release_date);
    setNativeValue(dateEl, release.release_date);
  }
}

// payload からテキスト系を一括注入する（ファイルは別経路: content.ts が injectFile を直接呼ぶ）。
// profile は payload.profile、album/date は payload.release から読む（envelope 取り違え防止）。
export function injectAll(root: ParentNode, payload: ReleasePayload): void {
  injectProfile(root, payload.profile);
  injectRelease(root, payload.release);
}

// <input type=file> へ DataTransfer 経由で File をセットし change を bubbles:true で発火する。
// （jsdom 非対応のため Playwright E2E でのみ検証される）
export function injectFile(input: HTMLInputElement, file: File): void {
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}
