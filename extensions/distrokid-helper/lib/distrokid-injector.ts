// distrokid.com/new フォームへの注入ロジック（#877 で実機 DOM 再検証）。
//
// 静的プロファイル / album / release date / 曲 / songwriter / cover は #813 の id ベース
// セレクタを継続。AI 開示は #877 で「inline 展開ではなく SweetAlert2 modal で開く」ことが
// 判明したため、track ごとの inline 注入を破棄し modal フローへ刷新した:
//   - 「はい/いいえ」: [name="ai_gate_<uuid>"][value="0"|"1"] radio（「はい」で modal が mount）
//   - modal (.ai-credits-swal-modal) を MutationObserver で待ち、内部で歌詞 / 作曲 /
//     録音範囲 (.distroAiRecordingScope) / partial 種別 / アーティスト種別
//     (.distroAiArtistPersona) / apply-all (#ai-apply-all-1) を設定して保存ボタンを click
//   - apply-all により 25 track 全部へ DistroKid 側が伝播するため、modal は 1st track 分 1 回だけ開く
//
// テキスト / SELECT 注入は React 互換のネイティブ value setter + bubbling イベントで行う
// （React の制御要素は value を直接書き換えても onChange が走らないため、prototype の
//  native setter で React の value tracker を欺く）。ファイル注入（DataTransfer 経由）は
// jsdom 非対応のため Playwright が担保する。
//
// 隠し要素（type=hidden の #artistName 等）はテキスト/SELECT 解決時に isVisible で排除する。
// 注入先が見つからない場合は silent skip せず FieldNotFoundError で fail-loud。
// 送信系ボタン（「続ける」）は一切操作しない（規約遵守・スコープ外）。
//
// #888 で実 DOM 再検証に基づき以下を追加:
//   (A) AI 開示 modal の段階的 trigger: 録音範囲 radio は name=null のため class+track+value で
//       紐付ける。full check で artist_persona radio が dynamic inject されるため MutationObserver
//       で出現を待つ。partial check で種別 radio が visible 化する。apply-all は album mode のみ存在。
//       modal 内 input は click + bubbles:true の change dispatch で段階的 trigger を確実に発火する。
//   (B) トラック数 select（#howManySongsOnThisAlbum）に曲数を set し、track 行（title_<uuid>）の
//       生成完了を MutationObserver で待ってから後続注入へ進む（順序保証）。
//   (C) Apple Music クレジット: 「クレジットを追加」を 1 回 click して全 track の入力欄を visible 化し、
//       各 track の performer/producer へ profile.artist を優先注入する。
//       profile.artist 未設定・旧 payload で欠落時は #artistName（アカウント登録名）に fallback する。

import { isVisible } from "../../shared/visibility";
import type { AiDisclosure, DistrokidProfile, DistrokidProfileCredits, SongwriterName } from "./types";

// 静的プロファイルの注入先。
export const PROFILE_SELECTORS = {
  artist: 'input[name="bandname"]',
  language: "#language",
  main_genre: "#genrePrimary",
  sub_genre: "#genreSecondary",
} as const;

// main genre 変更後、DistroKid が secondary genre の option を再生成するまでの待ち上限（ms）（#1407）。
const GENRE_SECONDARY_OPTION_WAIT_TIMEOUT_MS = 10_000;

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

// AI 開示の gate radio（modal を開く / disabled 時に「いいえ」を確定する）。
// 全 track の uuid は resolveTrackUuids() で title_<uuid> input から DOM order に解決する。
export const AI_DISCLOSURE_SELECTORS = {
  // 「はい / いいえ」radio。デフォルトは「いいえ (value=0)」が checked。
  // 「はい (value=1)」を click すると SweetAlert2 modal が mount する（#877）。
  gateByUuid: (uuid: string) => ({
    no: `[name="ai_gate_${uuid}"][value="0"]`,
    yes: `[name="ai_gate_${uuid}"][value="1"]`,
  }),
} as const;

// modal を操作する track 番号（1-indexed）。modal は 1st track の gate「はい」で開き、
// 録音範囲は track 単位の radio（track 属性）で設定する。apply-all が全 track へ伝播する。
const MODAL_TRACK = 1;

// AI 開示 modal（SweetAlert2 ベース）内のセレクタ群（実 DOM 再検証 #877 / #888 に基づく）。
// modal は 1st track の gate「はい」で 1 回だけ開き、apply-all checkbox で全 track へ伝播する。
// 段階的 trigger（#888）: full check で artist_persona radio が dynamic inject され、
// partial check で partial 種別 radio が visible 化する。apply-all は album mode のみ存在する。
export const AI_MODAL_SELECTORS = {
  // modal ルート（role="dialog"）。mount/unmount を MutationObserver で待つ基点。
  modal: ".ai-credits-swal-modal",
  // 歌詞 / 作曲 AI checkbox（uuid は modal を開いた 1st track のもの）。
  lyricsByUuid: (uuid: string) => `[name="ai_lyrics_${uuid}"]`,
  musicByUuid: (uuid: string) => `[name="ai_music_${uuid}"]`,
  // 録音物の AI 範囲 radio（"full"=音声すべて / "partial"=音声の一部）。
  // 実 DOM では name 属性が null のため、class + track 番号 + value で紐付ける（#888）。
  recordingScopeByTrack: (track1: number, scope: "full" | "partial") =>
    `[class*="distroAiRecordingScope"][track="${track1}"][value="${scope}"]`,
  // partial 録音時の種別 radio（partial 選択後に visible 化する）。
  partialAudioTypeByUuid: (uuid: string, type: "vocals" | "instruments") =>
    `[name="ai_partial_audio_type_${uuid}"][value="${type}"]`,
  // アーティスト種別 radio（value="0"=人間 / "1"=AI ペルソナ）。full check 後に dynamic inject。
  artistPersonaByUuid: (uuid: string, value: "0" | "1") => `[name="ai_artist_persona_${uuid}_0"][value="${value}"]`,
  // 「Apply these selections to all songs on this release」checkbox（album mode のみ存在）。
  applyAll: "#ai-apply-all-1",
  // 「保存する」ボタン（送信系ではない・modal を閉じるだけ）。
  saveButton: "button.swal2-confirm.ai-modal-btn-save",
} as const;

// AI 開示 modal の mount/unmount / 段階的 inject 待ち上限（ms）。超過したら fail-loud。
export const AI_MODAL_WAIT_TIMEOUT_MS = 10_000;

// トラック数 select（#888）。DistroKid /new は album/single radio ではなく曲数 dropdown で
// track 数を決める。value を set + change 発火で track 行が生成される。
export const TRACK_COUNT_SELECTOR = "#howManySongsOnThisAlbum";

// track 行（title_<uuid> input）の生成完了を待つ上限（ms）。超過したら fail-loud。
export const TRACK_ROW_WAIT_TIMEOUT_MS = 10_000;

// Apple Music クレジット用 fallback アーティスト名（アカウント登録の hidden 値）。
// profile.artist 未設定の後方互換用。BGM チャンネルは演奏者 = プロデューサー = アーティスト名の前提（#888）。
export const ARTIST_NAME_SELECTOR = "#artistName";

// Apple Music クレジット（演奏者 / プロデューサー）入力欄（#888 / #919）。track は 1-indexed。
//
// 各 track には credit 行が 2 つあり、performer 行（演奏者）と producer 行（プロデューサー）
// で構成される。各行は name 欄（input type=text）と role 欄（select、86 / 40 options）の
// ペア。role 欄は `dk-searchable-select__native` クラスで `display:none` に隠され、上に
// DistroKid 独自の searchable dropdown UI（`.dk-searchable-select__input`）が乗る設計
// （実 DOM 検証済み・#919）。ネイティブ `<select>` の `selectedIndex` 変更 + `change` event
// dispatch で独自 UI 側の表示テキストも同期されるため、`setSelectValue` だけで完結する。
export const APPLE_CREDIT_SELECTORS = {
  // 全 track 共通の展開トリガー。click で全 track の credit 入力欄が visible 化する。
  addTrigger: ".requirements-item-title",
  // .requirements-item-title は複数あり得るため textContent で絞り込む。
  addTriggerText: "クレジットを追加",
  performerNameByTrack: (track1: number) => `#track-${track1}-performer-1-name`,
  performerRoleByTrack: (track1: number) => `#track-${track1}-performer-1-role`,
  producerNameByTrack: (track1: number) => `#track-${track1}-producer-1-name`,
  producerRoleByTrack: (track1: number) => `#track-${track1}-producer-1-role`,
} as const;

// credit trigger（「クレジットを追加」）の可視化待ち上限（ms）（#923）。
// checkAllStores() 後、DistroKid 側が Apple Music ストア check に応じて credit trigger を
// re-render するまでの待ち上限。既存定数（AI_MODAL_WAIT_TIMEOUT_MS / TRACK_ROW_WAIT_TIMEOUT_MS）
// に合わせ 10_000 ms とし、実機の遅延に対して安全側を取る。
export const CREDIT_TRIGGER_WAIT_TIMEOUT_MS = 10_000;

// 続けるボタン（#919）。フィル完了後、確認ボタンが視界に入るよう scrollIntoView する。
// 規約遵守でクリックは行わない（送信は必ず人間が押す）。
export const DONE_BUTTON_SELECTOR = "#doneButton";

// 実配信先ストア checkbox 群（#923）。DistroKid のデフォルトは全ストア check。
// name="store" は upsell（shazam / audiomack）と共有されるため id^="chk" で区別する（#923）。
export const STORE_SELECTORS = {
  distribution: 'input[type="checkbox"][name="store"][id^="chk"]',
} as const;

// 配信除外ストア（#928）。check 時に確認ポップアップが表示され自動フィルを阻害するため、
// check せず、checked なら uncheck して配信外を保証する（運用上もこの 2 ストアへは配信しない）。
export const EXCLUDED_STORE_IDS = ["chksnap", "chkroblox"] as const;

// オプション（upsell）checkbox 群（#923）。
// name="store" は実配信先 26 個と共有されるが、実配信先は id^="chk" を持つため
// :not([id^="chk"]) で shazam（ディスカバリーパック）/ audiomack のみ対象にする（#923）。
export const UPSELL_SELECTORS = {
  store: 'input[type="checkbox"][name="store"]:not([id^="chk"])',
  extras: 'input[type="checkbox"][name="extras"]',
} as const;

// 新規リリース前提の assert 対象（previouslyReleased「いいえ(value=0)」）。
export const NEW_RELEASE_RADIO_SELECTOR = '[name^="previouslyReleased_"][value="0"]';

// track タイトル input の name 接頭辞（DOM order で uuid を列挙する基点）。
const TITLE_NAME_PREFIX = "title_";
const TITLE_NAME_SELECTOR = `[name^="${TITLE_NAME_PREFIX}"]`;

// リロードで直るエラーへのリロード案内（#923）。VisibilityTimeoutError / ModalTimeoutError /
// TrackCountTimeoutError の message 末尾に付加し、ユーザーがリロードで再試行できるようにする。
export const RELOAD_GUIDANCE = "ページをリロードして最初からやり直してください。";

// 注入先フィールドが見つからないことを表す専用エラー。
// silent skip せず fail-loud にすることで DistroKid の UI 変更を即座に検知する。
export class FieldNotFoundError extends Error {
  constructor(selector: string) {
    super(`注入先フィールドが見つかりません: ${selector}`);
    this.name = "FieldNotFoundError";
  }
}

// <select> の option lookup が失敗したことを表す専用エラー。
// 拡張は payload に option.value または option.text を送るが、実機の <option> 一覧に該当が
// 無い場合に発火する。DistroKid 本体の submit handler は jQuery .val() が null になると
// `.trim()` で crash するため、silent skip せず fail-loud にして config と実機 UI の不整合を
// 即座に検知する（#888 第2回 retest で判明）。
export class OptionNotFoundError extends Error {
  constructor(selector: string, payloadValue: string, optionLabels?: readonly string[]) {
    const options =
      optionLabels === undefined
        ? ""
        : ` / options=[${optionLabels.length === 0 ? "(empty)" : optionLabels.join(" / ")}]`;
    super(`<select> に該当 option がありません: ${selector} / payload="${payloadValue}"${options}`);
    this.name = "OptionNotFoundError";
  }
}

// AI 開示 modal の mount/unmount が制限時間内に観測できなかったことを表す専用エラー。
// silent skip せず fail-loud にすることで DistroKid の UI 変更を即座に検知する。
export class ModalTimeoutError extends Error {
  constructor(selector: string) {
    super(`AI 開示 modal の状態変化を待てませんでした: ${selector}。${RELOAD_GUIDANCE}`);
    this.name = "ModalTimeoutError";
  }
}

// トラック数 select 変更後に track 行が制限時間内に生成されなかったことを表す専用エラー。
// silent skip せず fail-loud にすることで DistroKid の UI 変更を即座に検知する。
export class TrackCountTimeoutError extends Error {
  constructor(selector: string, expected: number) {
    super(`track 行の生成を待てませんでした: ${selector}（期待数=${expected}）。${RELOAD_GUIDANCE}`);
    this.name = "TrackCountTimeoutError";
  }
}

// 要素の可視化が制限時間内に観測できなかったことを表す専用エラー（#923）。
// silent skip せず fail-loud にすることで DistroKid の UI 変更を即座に検知する。
export class VisibilityTimeoutError extends Error {
  constructor(selector: string) {
    super(`要素の可視化を待てませんでした: ${selector}。${RELOAD_GUIDANCE}`);
    this.name = "VisibilityTimeoutError";
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
// <select> は payload と option の一致判定が必要なため setSelectValue に委譲する。
// 単純な el.value = payload では payload が option.value と不一致の場合 selectedIndex が
// -1 のままになり、DistroKid 本体の submit handler 内で jQuery .val() == null → null.trim()
// crash する（#888 第2回 retest で判明）。
export function setNativeValue(el: ValueElement, value: string): void {
  if (el instanceof HTMLSelectElement) {
    setSelectValue(el, value);
    return;
  }
  nativeValueSetter(el)(value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

// <select> option の値マッチ用 normalize。全角→半角（NFKC）+ ／→/ + 小文字化 + trim で
// 日本語 UI（"R&B／ソウル"）と payload 表記（"r&b/soul"）の差を最大限吸収する。
function normalizeOptionText(s: string): string {
  return s.normalize("NFKC").replace(/／/g, "/").toLowerCase().trim();
}

function selectSelector(el: HTMLSelectElement): string {
  return el.id ? `#${el.id}` : el.tagName.toLowerCase();
}

function selectOptionLabels(el: HTMLSelectElement): string[] {
  return Array.from(el.options).map((o) => o.text.trim() || o.value || "(blank)");
}

// 優先順: option.value 完全一致 → option.text 完全一致（normalize）→ option.text 部分一致
// （normalize、placeholder value="" は除外）。一致無しなら OptionNotFoundError で fail-loud。
function findSelectOptionIndex(el: HTMLSelectElement, payloadValue: string): number {
  const target = normalizeOptionText(payloadValue);
  const opts = Array.from(el.options);
  let idx = findExactSelectOptionIndex(el, payloadValue);
  if (idx === -1) {
    idx = opts.findIndex((o) => {
      if (o.value === "") return false;
      const t = normalizeOptionText(o.text);
      return t.includes(target) || target.includes(t);
    });
  }
  return idx;
}

// 依存 dropdown の readiness 判定は曖昧な部分一致を使わない。
// "テクノ" を待っている途中に "ハードコア／ハードテクノ" が先に出ても、完全一致の
// option が現れるまで待つ必要がある。
function findExactSelectOptionIndex(el: HTMLSelectElement, payloadValue: string): number {
  const target = normalizeOptionText(payloadValue);
  const opts = Array.from(el.options);
  let idx = opts.findIndex((o) => o.value === payloadValue);
  if (idx === -1) {
    idx = opts.findIndex((o) => normalizeOptionText(o.text) === target);
  }
  return idx;
}

// <select> に対して payload 値で option を選ぶ。
function setSelectValue(el: HTMLSelectElement, payloadValue: string): void {
  const idx = findSelectOptionIndex(el, payloadValue);
  if (idx === -1) {
    throw new OptionNotFoundError(selectSelector(el), payloadValue, selectOptionLabels(el));
  }
  el.selectedIndex = idx;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

// セレクタに一致する可視のテキスト/SELECT 要素を返す（無ければ null）。
// type=hidden や祖先 display:none の隠し要素を isVisible で排除する。
function findVisibleField(root: ParentNode, selector: string): ValueElement | null {
  return Array.from(root.querySelectorAll<ValueElement>(selector)).filter(isVisible)[0] ?? null;
}

// 可視要素を要求する。未検出（または隠し要素のみ）なら fail-loud。
function requireVisibleField(root: ParentNode, selector: string): ValueElement {
  const el = findVisibleField(root, selector);
  if (el === null) {
    throw new FieldNotFoundError(selector);
  }
  return el;
}

function findVisibleSelectWithOption(
  root: ParentNode,
  selector: string,
  payloadValue: string,
): HTMLSelectElement | null {
  const el = findVisibleField(root, selector);
  if (!(el instanceof HTMLSelectElement)) {
    return null;
  }
  return findExactSelectOptionIndex(el, payloadValue) === -1 ? null : el;
}

function mutationTouchesSelector(mutation: MutationRecord, selector: string, current: Element | null): boolean {
  const target = mutation.target;
  if (current !== null && (target === current || current.contains(target) || target.contains(current))) {
    return true;
  }
  for (const node of [...mutation.addedNodes, ...mutation.removedNodes]) {
    if (!(node instanceof Element)) {
      continue;
    }
    if (node.matches(selector) || node.querySelector(selector) !== null) {
      return true;
    }
    if (current !== null && (node === current || node.contains(current) || current.contains(node))) {
      return true;
    }
  }
  return false;
}

// 依存 dropdown の option 再生成を待つ（#1407）。
// #genrePrimary の change 後、#genreSecondary は非同期に populate されるため、
// payload と一致する option が現れてから setNativeValue する。
function waitForSelectOption(
  root: ParentNode,
  selector: string,
  payloadValue: string,
  timeoutMs: number,
  options: { requireSelectorMutation?: boolean } = {},
): Promise<HTMLSelectElement> {
  const initial = requireVisibleField(root, selector);
  if (!(initial instanceof HTMLSelectElement)) {
    throw new FieldNotFoundError(selector);
  }
  if (options.requireSelectorMutation !== true) {
    const existing = findVisibleSelectWithOption(root, selector, payloadValue);
    if (existing !== null) {
      return Promise.resolve(existing);
    }
  }
  const observeRoot = ownerDocumentOf(root).body ?? ownerDocumentOf(root);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      observer.disconnect();
      const current = findVisibleField(root, selector);
      const options = current instanceof HTMLSelectElement ? selectOptionLabels(current) : [];
      reject(new OptionNotFoundError(selector, payloadValue, options));
    }, timeoutMs);
    const observer = new MutationObserver((mutations) => {
      if (
        options.requireSelectorMutation === true &&
        !mutations.some((mutation) => mutationTouchesSelector(mutation, selector, findVisibleField(root, selector)))
      ) {
        return;
      }
      const found = findVisibleSelectWithOption(root, selector, payloadValue);
      if (found !== null) {
        clearTimeout(timer);
        observer.disconnect();
        resolve(found);
      }
    });
    observer.observe(observeRoot, { childList: true, subtree: true, characterData: true, attributes: true });
  });
}

// 静的プロファイル（artist / sub_genre は任意、language / main_genre は必須）を注入する。
export async function injectProfile(root: ParentNode, profile: DistrokidProfile): Promise<void> {
  if (profile.artist.trim() !== "") {
    setNativeValue(requireVisibleField(root, PROFILE_SELECTORS.artist), profile.artist.trim());
  }
  setNativeValue(requireVisibleField(root, PROFILE_SELECTORS.language), profile.language);
  setNativeValue(requireVisibleField(root, PROFILE_SELECTORS.main_genre), profile.main_genre);
  if (profile.sub_genre !== null) {
    const subGenre = await waitForSelectOption(
      root,
      PROFILE_SELECTORS.sub_genre,
      profile.sub_genre,
      GENRE_SECONDARY_OPTION_WAIT_TIMEOUT_MS,
      { requireSelectorMutation: true },
    );
    setNativeValue(subGenre, profile.sub_genre);
  }
}

// アルバム名を注入する（#919）。
//
// `#albumTitleInput` は `<input type=text>` で id 一意。type=hidden ではないため
// findVisibleField の isVisible filter は不要。`setTrackCount` 直後は DistroKid 内部の
// re-layout 中で `getBoundingClientRect` が一時的に 0×0 になることがあり、isVisible が
// false 判定して silent skip するレースが #919 retest で観測されたため、id ベースで直接
// 取得して fail-loud にする。input は track 数が 1 のとき非マウントになる可能性があるため、
// 不在は ConfigError ではなく FieldNotFoundError として上位に伝播させる。
export function injectAlbumTitle(root: ParentNode, albumTitle: string): void {
  setNativeValue(requireInput(root, ALBUM_SELECTORS.album_title), albumTitle);
}

// リリース日を注入する（#919 / #932）。未確定 = null なら注入しない（フォーム空のまま）。
//
// `#release-date-dp` は `<input type=date>` で id 一意。同じく `injectAlbumTitle` と
// 同じ理由で isVisible filter を外し id 直接取得に変更した（race condition 回避）。
//
// DistroKid の契約プランによってはリリース日指定 UI 自体が出ない場合があるため、
// 値ありで要素不在のときは FieldNotFoundError を投げずに warn + skip してフィルを続行する（#932）。
export function injectReleaseDate(root: ParentNode, releaseDate: string | null): void {
  if (releaseDate === null) {
    return;
  }
  const el = root.querySelector<HTMLInputElement>(RELEASE_DATE_SELECTOR);
  if (el === null) {
    // リリース日指定は DistroKid の契約プランによって UI 自体が出ないため、
    // 不在はプラン非対応とみなし warn + skip する（フィル全体は止めない）（#932）。
    console.warn(
      `[distrokid-helper] リリース日フィールドが見つからないため skip します（プラン非対応の可能性）: ${RELEASE_DATE_SELECTOR}（#932）`,
    );
    return;
  }
  setNativeValue(el, releaseDate);
}

// 重要事項 checkbox の id 一覧（常時可視・rect 0×0 レースを回避するため id 直接取得）（#923）。
const IMPORTANT_TERMS_REQUIRED_IDS = [
  "#areyousurepromoservices",
  "#areyousurerecorded",
  "#areyousureotherartist",
  "#areyousuretandc",
] as const;

// 条件付き重要事項 checkbox のセレクタ（ストア選択に連動して可視化）（#923）。
const IMPORTANT_TERMS_CONDITIONAL_SELECTOR = 'input[type="checkbox"].areyousure';

// 重要事項 checkbox（重要事項・利用規約等）を check する（#923）。
// required 4 個は id 直接取得（isVisible 非依存）で確実に check する（bbox 0 レース回避）。
// conditional は .areyousure を列挙し required id を除外した上で可視のもののみ check する
// （不可視はストア未選択等で DistroKid が要求していない状態なので触らない）。
export function acceptImportantTerms(root: ParentNode): void {
  // required 4 個を id で直接 check（bbox 0 レース回避）
  for (const id of IMPORTANT_TERMS_REQUIRED_IDS) {
    setChecked(requireInput(root, id), true);
  }
  // conditional: .areyousure を列挙し、required id を除外した上で可視のもののみ check
  const requiredIds = new Set(IMPORTANT_TERMS_REQUIRED_IDS.map((id) => id.slice(1)));
  const conditionals = Array.from(root.querySelectorAll<HTMLInputElement>(IMPORTANT_TERMS_CONDITIONAL_SELECTOR)).filter(
    (cb) => !requiredIds.has(cb.id) && isVisible(cb),
  );
  for (const cb of conditionals) {
    setChecked(cb, true);
  }
}

// 続けるボタン（`#doneButton`）を視界へスクロールする（#919）。
// フィル完了直後はページ上端のアルバム情報部分にスクロール位置がある運用が多いため、
// 25 トラック分の長いフォームの最下部にある送信ボタンが見えず、人間が「フィル終わったが
// 何も起きない」と誤認する UX バグを防ぐ。要素不在は無音 skip（送信ボタンは DistroKid 側の
// UI 変更で id が変わる可能性があり、scroll は補助的 UX のため致命ではない）。
// 規約遵守でクリックは行わない（送信は必ず人間が押す・本拡張のスコープ外）。
export function scrollToDoneButton(root: ParentNode): void {
  const btn = root.querySelector<HTMLElement>(DONE_BUTTON_SELECTOR);
  if (btn !== null) {
    btn.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

// 全 upsell checkbox を強制 uncheck し、請求額が 0 ドルになる状態を保証する（#919）。
// レガシーパック / ディスカバリーパック / ストアマキシマイザー / DistroVid / 音量正規化 等の
// 有料オプションを誤クリックから守る。配下に upsell 不在なら何もしない（forEach の空配列）。
// 将来 config 化（`profile.upsells.legacy_pack` 等で opt-in）する想定だが、現状は全強制 uncheck。
export function uncheckUpsells(root: ParentNode): void {
  const all = [
    ...Array.from(root.querySelectorAll<HTMLInputElement>(UPSELL_SELECTORS.store)),
    ...Array.from(root.querySelectorAll<HTMLInputElement>(UPSELL_SELECTORS.extras)),
  ];
  for (const cb of all) {
    setChecked(cb, false);
  }
}

// 配信先ストア checkbox を check する（#923 / #928）。
// DistroKid のデフォルトは全ストア check だが、過去のバグで uncheck 状態になることがある。
// Apple Music が checked でないと credit 入力欄が不可視になり、後続の injectAppleMusicCredits が
// 失敗する原因になる（順序依存あり）（#923）。
// 対象が 0 件なら FieldNotFoundError で fail-loud（DistroKid UI 変更の即検知）。
//
// EXCLUDED_STORE_IDS（chksnap / chkroblox）に該当する checkbox は check せず、
// 事前に checked の場合は uncheck して配信外を保証する（#928）。
// check 時に確認ポップアップが表示されるため自動フィルを阻害し、運用上も配信しない。
// なお Snapchat（#chksnap）が unchecked のままになるため、条件付き重要事項
// #areyousuresnap は不可視のまま残り、acceptImportantTerms の isVisible フィルタで
// 自然にスキップされる（実装変更不要）。
export function checkAllStores(root: ParentNode): void {
  const checkboxes = Array.from(root.querySelectorAll<HTMLInputElement>(STORE_SELECTORS.distribution));
  if (checkboxes.length === 0) {
    throw new FieldNotFoundError(STORE_SELECTORS.distribution);
  }
  const excluded = new Set<string>(EXCLUDED_STORE_IDS);
  for (const cb of checkboxes) {
    if (excluded.has(cb.id)) {
      setChecked(cb, false);
    } else {
      setChecked(cb, true);
    }
  }
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
export function injectSongwriter(root: ParentNode, index1: number, songwriter: SongwriterName): void {
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
  const noRadios = Array.from(root.querySelectorAll<HTMLInputElement>(NEW_RELEASE_RADIO_SELECTOR));
  if (noRadios.length === 0) {
    throw new FieldNotFoundError(NEW_RELEASE_RADIO_SELECTOR);
  }
  if (!noRadios.every((radio) => radio.checked)) {
    throw new Error("previouslyReleased が「いいえ(新規)」で checked ではありません（過去公開対応はスコープ外）");
  }
}

// radio / checkbox を目標状態へ合わせる。目標と異なるときだけ click して checked を切り替える
// （既に目標状態なら no-op で重複 click を避ける）。gate radio のように click 自体が副作用を
// 起こす（modal mount 等）要素はこれで足りる。
//
// modal 内 input（#888）は dispatchChange=true を渡す。DistroKid 側の段階的 trigger（persona
// inject / partial 種別 visible 化）は bubbles:true の change を要求するため、click のネイティブ
// change に加えて明示 dispatch して確実に発火させる。
function setChecked(el: HTMLInputElement, checked: boolean, dispatchChange = false): void {
  if (el.checked !== checked) {
    el.click();
  }
  if (dispatchChange) {
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function requireInput(root: ParentNode, selector: string): HTMLInputElement {
  return requireElement<HTMLInputElement>(root, selector);
}

// セレクタに一致する要素を要求する。未検出なら fail-loud。
function requireElement<T extends Element>(root: ParentNode, selector: string): T {
  const el = root.querySelector<T>(selector);
  if (el === null) {
    throw new FieldNotFoundError(selector);
  }
  return el;
}

// root の所属 Document を解決する（MutationObserver の observe 対象を決めるため）。
function ownerDocumentOf(root: ParentNode): Document {
  if (root instanceof Document) {
    return root;
  }
  const doc = (root as Element | DocumentFragment).ownerDocument;
  if (doc === null) {
    throw new Error("root の Document を解決できません");
  }
  return doc;
}

// selector に一致する要素の出現を待つ（既に在れば即解決）。制限時間超過で ModalTimeoutError。
export function waitForElement(root: ParentNode, selector: string, timeoutMs: number): Promise<HTMLElement> {
  const existing = root.querySelector<HTMLElement>(selector);
  if (existing !== null) {
    return Promise.resolve(existing);
  }
  const observeRoot = ownerDocumentOf(root).body ?? ownerDocumentOf(root);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      observer.disconnect();
      reject(new ModalTimeoutError(selector));
    }, timeoutMs);
    const observer = new MutationObserver(() => {
      const found = root.querySelector<HTMLElement>(selector);
      if (found !== null) {
        clearTimeout(timer);
        observer.disconnect();
        resolve(found);
      }
    });
    observer.observe(observeRoot, { childList: true, subtree: true });
  });
}

// 要素が DOM から除去されるのを待つ（既に外れていれば即解決）。制限時間超過で ModalTimeoutError。
export function waitForRemoval(el: Element, timeoutMs: number): Promise<void> {
  if (!el.isConnected) {
    return Promise.resolve();
  }
  const observeRoot = el.ownerDocument.body ?? el.ownerDocument;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      observer.disconnect();
      reject(new ModalTimeoutError(AI_MODAL_SELECTORS.modal));
    }, timeoutMs);
    const observer = new MutationObserver(() => {
      if (!el.isConnected) {
        clearTimeout(timer);
        observer.disconnect();
        resolve();
      }
    });
    observer.observe(observeRoot, { childList: true, subtree: true });
  });
}

// selector に一致する要素が count 個に達するのを待つ（既に満たせば即解決）。
// 制限時間超過で TrackCountTimeoutError（fail-loud）。
export function waitForElementCount(
  root: ParentNode,
  selector: string,
  count: number,
  timeoutMs: number,
): Promise<void> {
  const reached = () => root.querySelectorAll(selector).length >= count;
  if (reached()) {
    return Promise.resolve();
  }
  const observeRoot = ownerDocumentOf(root).body ?? ownerDocumentOf(root);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      observer.disconnect();
      reject(new TrackCountTimeoutError(selector, count));
    }, timeoutMs);
    const observer = new MutationObserver(() => {
      if (reached()) {
        clearTimeout(timer);
        observer.disconnect();
        resolve();
      }
    });
    observer.observe(observeRoot, { childList: true, subtree: true });
  });
}

// 指定要素が可視になるのを待つ（既に可視なら即解決）。制限時間超過で VisibilityTimeoutError。
// checkAllStores() 後に credit trigger が visible 化するまでの待機に使用する（#923）。
export function waitForElementVisible(el: HTMLElement, timeoutMs: number): Promise<void> {
  if (isVisible(el)) {
    return Promise.resolve();
  }
  const observeRoot = el.ownerDocument.body ?? el.ownerDocument;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      observer.disconnect();
      reject(new VisibilityTimeoutError(el.id ? `#${el.id}` : el.tagName.toLowerCase()));
    }, timeoutMs);
    const observer = new MutationObserver(() => {
      if (isVisible(el)) {
        clearTimeout(timer);
        observer.disconnect();
        resolve();
      }
    });
    observer.observe(observeRoot, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["style", "class", "hidden"],
    });
  });
}

// トラック数 select に曲数を set し、track 行（title_<uuid>）の生成完了を待つ（#888）。
// value 変更だけでは onchange handler が動かないため change を bubbles:true で発火する。
// 行生成を待ってから後続の注入（プロファイル / タイトル / credit）へ進む（順序保証）。
export async function setTrackCount(root: ParentNode, count: number): Promise<void> {
  setNativeValue(requireElement<HTMLSelectElement>(root, TRACK_COUNT_SELECTOR), String(count));
  await waitForElementCount(root, TITLE_NAME_SELECTOR, count, TRACK_ROW_WAIT_TIMEOUT_MS);
}

// アカウント登録のアーティスト名（#artistName hidden）を解決する。未登録なら fail-loud。
function requireArtistName(root: ParentNode): string {
  const el = root.querySelector<HTMLInputElement>(ARTIST_NAME_SELECTOR);
  if (el === null) {
    throw new FieldNotFoundError(ARTIST_NAME_SELECTOR);
  }
  const name = el.value.trim();
  if (name === "") {
    throw new Error(`${ARTIST_NAME_SELECTOR} の値が空です（アーティスト名が未登録）`);
  }
  return name;
}

function resolveCreditArtistName(root: ParentNode, profileArtist: string): string {
  const configured = profileArtist.trim();
  if (configured !== "") {
    return configured;
  }
  return requireArtistName(root);
}

// Apple Music クレジット展開トリガー（「クレジットを追加」）を解決する。
// .requirements-item-title は複数あり得るため textContent で絞り込む（fail-loud）。
function requireCreditTrigger(root: ParentNode): HTMLElement {
  const trigger = Array.from(root.querySelectorAll<HTMLElement>(APPLE_CREDIT_SELECTORS.addTrigger)).find((el) =>
    el.textContent?.includes(APPLE_CREDIT_SELECTORS.addTriggerText),
  );
  if (trigger === undefined) {
    throw new FieldNotFoundError(
      `${APPLE_CREDIT_SELECTORS.addTrigger}（text: ${APPLE_CREDIT_SELECTORS.addTriggerText}）`,
    );
  }
  return trigger;
}

// Apple Music クレジット（演奏者 / プロデューサー）を全 track に注入する（#888 / #919 / #923）。
//
// トップレベルの「クレジットを追加」を 1 回 click して全 track の入力欄を visible 化し、
// 各 track の performer / producer に以下を注入する:
//   - name 欄: `profile.artist`（未設定時は後方互換で `#artistName`）
//   - role 欄: `credits.performer_role` / `credits.producer_role`（profile 由来、既定 Synthesizer + Producer）
// role 欄は `dk-searchable-select__native` クラスで display:none に隠れたネイティブ select だが、
// `setSelectValue` でネイティブ側に setSelectedIndex + change dispatch すれば DistroKid 独自 UI
// （`.dk-searchable-select__input`）の表示テキストも同期される（実 DOM 検証済み・#919）。
// Apple Music ストア check 後に credit trigger が可視化されるまで待つ（#923）。
// checkAllStores() でストアを check してから本関数が呼ばれる順序依存（content.ts で保証）。
export async function injectAppleMusicCredits(
  root: ParentNode,
  trackCount: number,
  artist: string,
  credits: DistrokidProfileCredits,
): Promise<void> {
  const artistName = resolveCreditArtistName(root, artist);
  const trigger = requireCreditTrigger(root);
  // Apple Music ストア check 後に credit trigger が可視化されるまで待つ（#923）。
  await waitForElementVisible(trigger, CREDIT_TRIGGER_WAIT_TIMEOUT_MS);
  trigger.click();
  for (let track1 = 1; track1 <= trackCount; track1 += 1) {
    setNativeValue(requireInput(root, APPLE_CREDIT_SELECTORS.performerNameByTrack(track1)), artistName);
    setSelectValue(
      requireElement<HTMLSelectElement>(root, APPLE_CREDIT_SELECTORS.performerRoleByTrack(track1)),
      credits.performer_role,
    );
    setNativeValue(requireInput(root, APPLE_CREDIT_SELECTORS.producerNameByTrack(track1)), artistName);
    setSelectValue(
      requireElement<HTMLSelectElement>(root, APPLE_CREDIT_SELECTORS.producerRoleByTrack(track1)),
      credits.producer_role,
    );
  }
}

// modal 内で AI 開示の各設定を反映する（uuid は modal を開いた 1st track のもの）。
// 段階的 trigger（#888）:
//   - modal mount 直後は SweetAlert2 の show animation 中で内部 form が未描画なことがあるため、
//     最初の操作対象（lyrics checkbox）の出現を MutationObserver で待ってから注入を始める
//   - recording_scope='full' → full radio を check すると persona radio が dynamic inject される
//     ため、出現を MutationObserver で待ってから persona を設定する
//   - recording_scope='partial' → partial radio を check すると種別 radio が visible 化するため、
//     partial_audio_type が非 null のときのみ設定する（undefined を loose equality で skip #877）
//   - apply-all は album mode のみ存在するため、不在なら skip（single mode 許容）
async function applyModalSelections(modal: ParentNode, uuid: string, ai: AiDisclosure): Promise<void> {
  await waitForElement(modal, AI_MODAL_SELECTORS.lyricsByUuid(uuid), AI_MODAL_WAIT_TIMEOUT_MS);
  setChecked(requireInput(modal, AI_MODAL_SELECTORS.lyricsByUuid(uuid)), ai.lyrics, true);
  setChecked(requireInput(modal, AI_MODAL_SELECTORS.musicByUuid(uuid)), ai.music, true);
  setChecked(
    requireInput(modal, AI_MODAL_SELECTORS.recordingScopeByTrack(MODAL_TRACK, ai.recording_scope)),
    true,
    true,
  );

  if (ai.recording_scope === "full") {
    return applyFullScopeSelections(modal, uuid, ai);
  }
  if (ai.partial_audio_type != null) {
    setChecked(requireInput(modal, AI_MODAL_SELECTORS.partialAudioTypeByUuid(uuid, ai.partial_audio_type)), true, true);
  }
  applyAllSelection(modal, ai);
  return Promise.resolve();
}

// full check 後に dynamic inject される persona radio の出現を待ってから設定する。
async function applyFullScopeSelections(modal: ParentNode, uuid: string, ai: AiDisclosure): Promise<void> {
  const personaSelector = AI_MODAL_SELECTORS.artistPersonaByUuid(uuid, ai.artist_persona ? "1" : "0");
  await waitForElement(modal, personaSelector, AI_MODAL_WAIT_TIMEOUT_MS);
  setChecked(requireInput(modal, personaSelector), true, true);
  applyAllSelection(modal, ai);
}

// apply-all checkbox を設定する。album mode のみ存在するため不在なら skip（single mode 許容 #888）。
function applyAllSelection(modal: ParentNode, ai: AiDisclosure): void {
  const applyAll = modal.querySelector<HTMLInputElement>(AI_MODAL_SELECTORS.applyAll);
  if (applyAll !== null) {
    setChecked(applyAll, ai.apply_to_all, true);
  }
}

// AI 開示注入（#877 modal フロー）:
//   1. 全 track の uuid を DOM order で解決する（基点は title_<uuid>）
//   2. enabled=false: 各 track の「いいえ」radio を明示確定（modal は開かない）
//   3. enabled=true: 1st track の「はい」radio を click → modal mount を待つ
//      → modal 内で各設定 + apply-all → 保存 button → modal unmount を待つ
// apply-all により 25 track 全部へ DistroKid 側が伝播するため、track ごとの inline 注入はしない。
export async function injectAiDisclosure(root: ParentNode, ai: AiDisclosure): Promise<void> {
  const uuids = resolveTrackUuids(root);
  if (uuids.length === 0) {
    throw new FieldNotFoundError(TITLE_NAME_SELECTOR);
  }

  if (!ai.enabled) {
    // 人手 default に頼らず、各 track の「いいえ」を明示確定する（modal は開かない）。
    for (const uuid of uuids) {
      setChecked(requireInput(root, AI_DISCLOSURE_SELECTORS.gateByUuid(uuid).no), true);
    }
    return;
  }

  const firstUuid = uuids[0];
  setChecked(requireInput(root, AI_DISCLOSURE_SELECTORS.gateByUuid(firstUuid).yes), true);
  const modal = await waitForElement(root, AI_MODAL_SELECTORS.modal, AI_MODAL_WAIT_TIMEOUT_MS);
  await applyModalSelections(modal, firstUuid, ai);
  requireElement<HTMLButtonElement>(modal, AI_MODAL_SELECTORS.saveButton).click();
  await waitForRemoval(modal, AI_MODAL_WAIT_TIMEOUT_MS);
}
