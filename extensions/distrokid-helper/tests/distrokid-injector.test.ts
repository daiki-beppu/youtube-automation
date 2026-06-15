// @vitest-environment jsdom
//
// `lib/distrokid-injector.ts` のセレクタ契約 + 注入オーケストレーションのテスト（#813 / #877 / #888）。
//
// #888 で実 DOM 再検証に基づき以下を固定する:
//   (A) AI 開示 modal の段階的 trigger（録音範囲 radio は class+track+value、full check で
//       persona radio が dynamic inject される → MutationObserver で待機、apply-all は album mode のみ）
//   (B) トラック数 select（#howManySongsOnThisAlbum）への曲数 set + track 行生成待機
//   (C) Apple Music クレジット（演奏者 / プロデューサー）の全 track 一括注入
//
// jsdom はレイアウトを行わず getBoundingClientRect() が常に全 0 を返すため、可視要素には
// VISIBLE_RECT を擬似付与する（production の strict isVisible は bbox を見て hidden を排除する）。
// File 注入（DataTransfer）と MutationObserver による実展開待ちのうち、DOM 非同期挿入のみ
// jsdom で再現できる。実 file input への DataTransfer セットは Playwright（tests/e2e）が担う。

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  setNativeValue,
  injectProfile,
  injectAlbumTitle,
  injectReleaseDate,
  resolveTrackUuids,
  injectTrackTitle,
  injectSongwriter,
  assertNewRelease,
  injectAiDisclosure,
  injectAppleMusicCredits,
  setTrackCount,
  waitForElement,
  waitForElementCount,
  waitForRemoval,
  waitForElementVisible,
  checkAllStores,
  acceptImportantTerms,
  scrollToDoneButton,
  uncheckUpsells,
  PROFILE_SELECTORS,
  ALBUM_SELECTORS,
  RELEASE_DATE_SELECTOR,
  FILE_SELECTORS,
  TRACK_FIELD_SELECTORS,
  TRACK_COUNT_SELECTOR,
  ARTIST_NAME_SELECTOR,
  APPLE_CREDIT_SELECTORS,
  AI_DISCLOSURE_SELECTORS,
  AI_MODAL_SELECTORS,
  STORE_SELECTORS,
  EXCLUDED_STORE_IDS,
  DONE_BUTTON_SELECTOR,
  UPSELL_SELECTORS,
  CREDIT_TRIGGER_WAIT_TIMEOUT_MS,
  FieldNotFoundError,
  ModalTimeoutError,
  TrackCountTimeoutError,
  OptionNotFoundError,
  VisibilityTimeoutError,
  RELOAD_GUIDANCE,
} from "../lib/distrokid-injector";
import type { DistrokidProfile, AiDisclosure, DistrokidProfileCredits, SongwriterName } from "../lib/types";

// Apple Music credits default（profile.credits の標準値・テスト共通）。
const SAMPLE_CREDITS: DistrokidProfileCredits = {
  performer_role: "Audio",
  producer_role: "Producer",
};

// jsdom はレイアウトしないため、可視要素には非 0 bbox を擬似付与して isVisible を通す。
const VISIBLE_RECT = {
  x: 0,
  y: 0,
  top: 0,
  left: 0,
  right: 100,
  bottom: 20,
  width: 100,
  height: 20,
  toJSON: () => ({}),
} as DOMRect;

const ZERO_RECT = {
  x: 0,
  y: 0,
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
  width: 0,
  height: 0,
  toJSON: () => ({}),
} as DOMRect;

function makeVisible<T extends HTMLElement>(el: T): T {
  el.getBoundingClientRect = () => VISIBLE_RECT;
  return el;
}

// id / name 属性を持つ可視 input を body に mount する。
// value はプロパティではなく属性で設定し、`[value="0"]` のような属性セレクタにも一致させる。
function mountInput(attrs: { id?: string; name?: string; type?: string; value?: string }): HTMLInputElement {
  const input = document.createElement("input");
  if (attrs.id !== undefined) input.id = attrs.id;
  if (attrs.name !== undefined) input.name = attrs.name;
  if (attrs.type !== undefined) input.type = attrs.type;
  if (attrs.value !== undefined) input.setAttribute("value", attrs.value);
  document.body.appendChild(input);
  return makeVisible(input);
}

// 指定 value 群を option に持つ可視 SELECT を body に mount する。
function mountSelect(id: string, values: string[]): HTMLSelectElement {
  const select = document.createElement("select");
  select.id = id;
  for (const v of values) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  }
  document.body.appendChild(select);
  return makeVisible(select);
}

// {value, text} を別指定できる mount。実機 DistroKid の <option value="25">R&B／ソウル</option>
// のように value が数値で text が日本語ラベルというパターンを再現するため。
function mountSelectWithOptions(
  id: string,
  options: ReadonlyArray<{ value: string; text: string }>,
): HTMLSelectElement {
  const select = document.createElement("select");
  select.id = id;
  for (const o of options) {
    const opt = document.createElement("option");
    opt.value = o.value;
    opt.textContent = o.text;
    select.appendChild(opt);
  }
  document.body.appendChild(select);
  return makeVisible(select);
}

function makeCheckbox(parent: ParentNode, attrs: { id?: string; name?: string }): HTMLInputElement {
  const cb = document.createElement("input");
  cb.type = "checkbox";
  if (attrs.id !== undefined) cb.id = attrs.id;
  if (attrs.name !== undefined) cb.name = attrs.name;
  (parent as Node).appendChild(cb);
  return cb;
}

function makeRadio(parent: ParentNode, attrs: { name: string; value: string }): HTMLInputElement {
  const r = document.createElement("input");
  r.type = "radio";
  r.name = attrs.name;
  r.setAttribute("value", attrs.value);
  (parent as Node).appendChild(r);
  return r;
}

// 録音範囲 radio（実 DOM 準拠 #888: name は null、class + track + value で紐付ける）。
function makeScopeRadio(parent: ParentNode, track1: number, value: "full" | "partial"): HTMLInputElement {
  const r = document.createElement("input");
  r.type = "radio";
  r.className = "distroAiRecordingScope";
  r.setAttribute("track", String(track1));
  r.setAttribute("value", value);
  (parent as Node).appendChild(r);
  return r;
}

// track 単位の title input + ai_gate radio（yes/no）を fieldset に mount する（modal 開閉の起点）。
function mountTrackGate(uuid: string): {
  fieldset: HTMLFieldSetElement;
  gateNo: HTMLInputElement;
  gateYes: HTMLInputElement;
} {
  const fieldset = document.createElement("fieldset");
  const title = document.createElement("input");
  title.name = `title_${uuid}`;
  fieldset.appendChild(title);
  const gateNo = makeRadio(fieldset, { name: `ai_gate_${uuid}`, value: "0" });
  gateNo.checked = true;
  const gateYes = makeRadio(fieldset, { name: `ai_gate_${uuid}`, value: "1" });
  document.body.appendChild(fieldset);
  return { fieldset, gateNo, gateYes };
}

// 実 DOM 再検証（#877 / #888）に基づく SweetAlert2 modal を組み立てる（uuid は modal を開いた 1st track）。
// persona radio は初期には存在せず、録音範囲 full の change で #ai-artist-questions-1 へ dynamic inject する。
// apply-all は album mode（opts.album）のときのみ存在する。
interface ModalRefs {
  modal: HTMLElement;
  lyrics: HTMLInputElement;
  music: HTMLInputElement;
  scopeFull: HTMLInputElement;
  scopePartial: HTMLInputElement;
  partialVocals: HTMLInputElement;
  partialInstruments: HTMLInputElement;
  personaContainer: HTMLElement;
  // full check で dynamic inject された persona radio を返す（modal 除去後も closure 参照で
  // checked 状態を読めるようにする）。未 inject なら null。
  getPersona: (value: "0" | "1") => HTMLInputElement | null;
  applyAll: HTMLInputElement | null;
  save: HTMLButtonElement;
  saveClicks: () => number;
}

function withClass<T extends HTMLElement>(el: T, className: string): T {
  el.classList.add(className);
  return el;
}

function buildModal(uuid: string, opts: { album: boolean }): ModalRefs {
  const modal = document.createElement("div");
  modal.className = "ai-credits-swal-modal";
  modal.setAttribute("role", "dialog");
  const details = document.createElement("div");
  details.id = "ai-details-1";
  modal.appendChild(details);

  const lyrics = withClass(makeCheckbox(details, { name: `ai_lyrics_${uuid}` }), "distroAiLyrics");
  const music = withClass(makeCheckbox(details, { name: `ai_music_${uuid}` }), "distroAiMusic");

  // 録音範囲 radio（name は null、track=1）。
  const scopeFull = makeScopeRadio(details, 1, "full");
  const scopePartial = makeScopeRadio(details, 1, "partial");

  const partialVocals = withClass(
    makeRadio(details, { name: `ai_partial_audio_type_${uuid}`, value: "vocals" }),
    "distroAiPartialAudioType",
  );
  const partialInstruments = withClass(
    makeRadio(details, { name: `ai_partial_audio_type_${uuid}`, value: "instruments" }),
    "distroAiPartialAudioType",
  );

  // persona radio はここでは作らない。full check で dynamic inject する。
  const personaContainer = document.createElement("div");
  personaContainer.id = "ai-artist-questions-1";
  details.appendChild(personaContainer);

  const personaName = `ai_artist_persona_${uuid}_0`;
  const personaByValue: Record<string, HTMLInputElement> = {};
  // full check（change）で persona radio を遅延 inject し、injector 側の MutationObserver 待機経路を通す。
  scopeFull.addEventListener("change", () => {
    if (!scopeFull.checked) return;
    if (personaContainer.querySelector('[name^="ai_artist_persona_"]') !== null) return;
    setTimeout(() => {
      if (personaContainer.querySelector('[name^="ai_artist_persona_"]') !== null) return;
      personaByValue["0"] = withClass(
        makeRadio(personaContainer, { name: personaName, value: "0" }),
        "distroAiArtistPersona",
      );
      personaByValue["1"] = withClass(
        makeRadio(personaContainer, { name: personaName, value: "1" }),
        "distroAiArtistPersona",
      );
    }, 0);
  });

  const applyAll = opts.album ? makeCheckbox(details, { id: "ai-apply-all-1" }) : null;

  const save = document.createElement("button");
  save.className = "swal2-confirm ai-modal-btn-save";
  modal.appendChild(save);
  let saveClicks = 0;
  // 「保存する」で modal を unmount する（実 swal2 の閉じる挙動を模す）。
  save.addEventListener("click", () => {
    saveClicks += 1;
    setTimeout(() => modal.remove(), 0);
  });

  return {
    modal,
    lyrics,
    music,
    scopeFull,
    scopePartial,
    partialVocals,
    partialInstruments,
    personaContainer,
    getPersona: (value: "0" | "1") => personaByValue[value] ?? null,
    applyAll,
    save,
    saveClicks: () => saveClicks,
  };
}

// track gate を mount し、1st track の「はい」click で modal を遅延 mount する配線を張る。
// setTimeout(0) で mount することで injector 側 MutationObserver の待機経路を実際に通す。
function setupModalForm(
  uuids: string[],
  opts: { album: boolean } = { album: uuids.length > 1 },
): {
  gates: { uuid: string; gateNo: HTMLInputElement; gateYes: HTMLInputElement }[];
  getModalRefs: () => ModalRefs | null;
} {
  let modalRefs: ModalRefs | null = null;
  const gates = uuids.map((uuid) => {
    const { gateNo, gateYes } = mountTrackGate(uuid);
    gateYes.addEventListener("click", () => {
      setTimeout(() => {
        if (document.querySelector(AI_MODAL_SELECTORS.modal) === null) {
          modalRefs = buildModal(uuid, opts);
          document.body.appendChild(modalRefs.modal);
        }
      }, 0);
    });
    return { uuid, gateNo, gateYes };
  });
  return { gates, getModalRefs: () => modalRefs };
}

beforeEach(() => {
  document.body.innerHTML = "";
});

// 新 schema の型契約を構造的に固定する（Python の DistrokidProfile と 1:1）。
const SAMPLE_SONGWRITER: SongwriterName = { first: "Jane", middle: null, last: "Doe" };
const SAMPLE_AI: AiDisclosure = {
  enabled: true,
  lyrics: true,
  music: true,
  recording_scope: "full",
  partial_audio_type: null,
  artist_persona: true,
  apply_to_all: true,
};
const SAMPLE_PROFILE: DistrokidProfile = {
  language: "ja",
  main_genre: "Electronic",
  sub_genre: "House",
  songwriter: SAMPLE_SONGWRITER,
  ai_disclosure: SAMPLE_AI,
  credits: SAMPLE_CREDITS,
};

describe("新 schema 型契約（lib/types）", () => {
  it("DistrokidProfile は nested songwriter + modal 対応 ai_disclosure を持つ", () => {
    // Then: 旧フラットフィールドは型から撤廃され、nested 構造になっている
    expect(SAMPLE_PROFILE.songwriter?.first).toBe("Jane");
    expect(SAMPLE_PROFILE.songwriter?.middle).toBeNull();
    expect(SAMPLE_PROFILE.ai_disclosure.partial_audio_type).toBeNull();
    expect("artist_name" in SAMPLE_PROFILE).toBe(false);
    // #877 で modal フローの新フィールドが追加され、composition は music にリネーム
    expect(SAMPLE_PROFILE.ai_disclosure.music).toBe(true);
    expect(SAMPLE_PROFILE.ai_disclosure.recording_scope).toBe("full");
    expect(SAMPLE_PROFILE.ai_disclosure.artist_persona).toBe(true);
    expect(SAMPLE_PROFILE.ai_disclosure.apply_to_all).toBe(true);
    expect("composition" in SAMPLE_PROFILE.ai_disclosure).toBe(false);
  });
});

describe("PROFILE_SELECTORS（id ベース・実 DOM 検証）", () => {
  it("language / main_genre / sub_genre が実 DOM の id を指す", () => {
    expect(PROFILE_SELECTORS.language).toBe("#language");
    expect(PROFILE_SELECTORS.main_genre).toBe("#genrePrimary");
    expect(PROFILE_SELECTORS.sub_genre).toBe("#genreSecondary");
  });
});

describe("ALBUM_SELECTORS / RELEASE_DATE_SELECTOR", () => {
  it("album_title はアルバム時のみ存在する #albumTitleInput", () => {
    expect(ALBUM_SELECTORS.album_title).toBe("#albumTitleInput");
  });

  it("リリース日は name=releaseDate の #release-date-dp", () => {
    expect(RELEASE_DATE_SELECTOR).toBe("#release-date-dp");
  });
});

describe("FILE_SELECTORS（ジャケット + track 別アップロード）", () => {
  it("cover は #artwork", () => {
    expect(FILE_SELECTORS.cover).toBe("#artwork");
  });

  it("trackByIndex は 1-indexed の #js-track-upload-N を返す", () => {
    expect(FILE_SELECTORS.trackByIndex(1)).toBe("#js-track-upload-1");
    expect(FILE_SELECTORS.trackByIndex(3)).toBe("#js-track-upload-3");
  });
});

describe("TRACK_FIELD_SELECTORS（track 別タイトル + songwriter 3 分割）", () => {
  it("titleByUuid は [name=title_<uuid>] を返す（DOM order で uuid 解決）", () => {
    expect(TRACK_FIELD_SELECTORS.titleByUuid("abc-123")).toBe('[name="title_abc-123"]');
  });

  it("songwriterByIndex は first/middle/last 3 分割欄（1-indexed）を返す", () => {
    expect(TRACK_FIELD_SELECTORS.songwriterByIndex(2)).toEqual({
      first: '[name="songwriter_real_name_first2"]',
      middle: '[name="songwriter_real_name_middle2"]',
      last: '[name="songwriter_real_name_last2"]',
    });
  });
});

describe("TRACK_COUNT_SELECTOR / APPLE_CREDIT_SELECTORS（#888 実 DOM 準拠）", () => {
  it("トラック数 select は #howManySongsOnThisAlbum", () => {
    expect(TRACK_COUNT_SELECTOR).toBe("#howManySongsOnThisAlbum");
  });

  it("artist 名は #artistName（アカウント登録の hidden）", () => {
    expect(ARTIST_NAME_SELECTOR).toBe("#artistName");
  });

  it("credit トリガーは .requirements-item-title（text=「クレジットを追加」）", () => {
    expect(APPLE_CREDIT_SELECTORS.addTrigger).toBe(".requirements-item-title");
    expect(APPLE_CREDIT_SELECTORS.addTriggerText).toBe("クレジットを追加");
  });

  it("performer/producer の name / role は #track-{N}-{role}-1-{kind}（1-indexed）を返す", () => {
    // #919 で role 欄も注入対象に追加したため、name と role を別 selector に分けた。
    expect(APPLE_CREDIT_SELECTORS.performerNameByTrack(3)).toBe("#track-3-performer-1-name");
    expect(APPLE_CREDIT_SELECTORS.performerRoleByTrack(3)).toBe("#track-3-performer-1-role");
    expect(APPLE_CREDIT_SELECTORS.producerNameByTrack(3)).toBe("#track-3-producer-1-name");
    expect(APPLE_CREDIT_SELECTORS.producerRoleByTrack(3)).toBe("#track-3-producer-1-role");
  });
});

describe("setNativeValue", () => {
  it("値をセットし input と change を bubbles:true で発火する", () => {
    // Given: body に紐づく input と、親(body)で捕捉するイベントリスナ
    const input = document.createElement("input");
    document.body.appendChild(input);
    const bubbled: Record<string, boolean> = {};
    document.body.addEventListener("input", () => {
      bubbled.input = true;
    });
    document.body.addEventListener("change", () => {
      bubbled.change = true;
    });

    // When
    setNativeValue(input, "hello");

    // Then: 値がセットされ、両イベントが親まで bubbling する
    expect(input.value).toBe("hello");
    expect(bubbled.input).toBe(true);
    expect(bubbled.change).toBe(true);
  });

  it("textarea にも prototype setter 経由で値をセットできる", () => {
    // Given
    const textarea = document.createElement("textarea");
    document.body.appendChild(textarea);

    // When
    setNativeValue(textarea, "multi\nline");

    // Then
    expect(textarea.value).toBe("multi\nline");
  });
});

describe("injectProfile（language/main_genre 必須・sub_genre 任意・isVisible 排除）", () => {
  it("language/main_genre/sub_genre を可視 SELECT に注入する", () => {
    // Given
    const language = mountSelect("language", ["ja", "en"]);
    const genre = mountSelect("genrePrimary", ["Electronic", "Pop"]);
    const sub = mountSelect("genreSecondary", ["House", "Techno"]);

    // When
    injectProfile(document, SAMPLE_PROFILE);

    // Then
    expect(language.value).toBe("ja");
    expect(genre.value).toBe("Electronic");
    expect(sub.value).toBe("House");
  });

  it("sub_genre が null なら genreSecondary を触らない（skip）", () => {
    // Given
    mountSelect("language", ["ja"]);
    mountSelect("genrePrimary", ["Electronic"]);
    const sub = mountSelect("genreSecondary", ["House", "Techno"]);
    let subChanges = 0;
    sub.addEventListener("change", () => {
      subChanges += 1;
    });

    // When
    injectProfile(document, { ...SAMPLE_PROFILE, sub_genre: null });

    // Then: skip されるため change は一切発火しない
    expect(subChanges).toBe(0);
  });

  it("language が hidden（bbox 0）なら FieldNotFoundError で fail-loud", () => {
    // Given: language は存在するが type=hidden 相当（bbox 0）
    const language = mountSelect("language", ["ja"]);
    language.getBoundingClientRect = () => ZERO_RECT;
    mountSelect("genrePrimary", ["Electronic"]);

    // Then
    expect(() => injectProfile(document, { ...SAMPLE_PROFILE, sub_genre: null })).toThrow(FieldNotFoundError);
  });

  it("language 欄が存在しなければ FieldNotFoundError", () => {
    // Given: main_genre だけ存在
    mountSelect("genrePrimary", ["Electronic"]);

    // Then
    expect(() => injectProfile(document, { ...SAMPLE_PROFILE, sub_genre: null })).toThrow(FieldNotFoundError);
  });
});

// #888 第2回 retest: payload が option.value と不一致だと selectedIndex が -1 になり、
// DistroKid 本体の submit handler 内で jQuery .val() == null → null.trim() crash する。
// setNativeValue は <select> 検出時に option.value → text → 部分一致（normalize）の順で
// 一致を取り、最終的に selectedIndex を更新する必要がある。
describe("setNativeValue（<select>）— option の value / text 一致 + normalize fallback", () => {
  it("option.value 完全一致を優先する（既存パターン）", () => {
    const sel = mountSelectWithOptions("genrePrimary", [
      { value: "", text: "ジャンルを選択" },
      { value: "9", text: "Electronic" },
      { value: "25", text: "R&B／ソウル" },
    ]);

    setNativeValue(sel, "25");

    expect(sel.value).toBe("25");
    expect(sel.selectedIndex).toBe(2);
  });

  it("option.text 完全一致で実機ラベル（日本語）が選ばれる", () => {
    const sel = mountSelectWithOptions("genrePrimary", [
      { value: "", text: "ジャンルを選択" },
      { value: "9", text: "Electronic" },
      { value: "25", text: "R&B／ソウル" },
    ]);

    setNativeValue(sel, "R&B／ソウル");

    expect(sel.value).toBe("25");
    expect(sel.selectedIndex).toBe(2);
  });

  it("normalize で ／ → / 変換 + lowercase を吸収する（text 完全一致）", () => {
    const sel = mountSelectWithOptions("genrePrimary", [{ value: "25", text: "R&B／ソウル" }]);

    // payload は半角 / + 全大文字
    setNativeValue(sel, "R&B/ソウル");

    expect(sel.value).toBe("25");
  });

  it("text 部分一致 fallback（payload が option.text の前方）", () => {
    const sel = mountSelectWithOptions("genrePrimary", [
      { value: "", text: "ジャンルを選択" },
      { value: "9", text: "Electronic Dance" },
    ]);

    // payload "Electronic" は option.text "Electronic Dance" の部分集合
    setNativeValue(sel, "Electronic");

    expect(sel.value).toBe("9");
  });

  it('placeholder (value="") は部分一致経路から除外される', () => {
    const sel = mountSelectWithOptions("genrePrimary", [
      { value: "", text: "ジャンルを選択（全 44 件）" },
      { value: "25", text: "R&B／ソウル" },
    ]);

    // payload "ジャンル" は placeholder の text に含まれるが、value="" のため skip され
    // R&B option ともマッチしないので OptionNotFoundError
    expect(() => setNativeValue(sel, "ジャンル")).toThrow(OptionNotFoundError);
  });

  it("一致無しなら OptionNotFoundError で fail-loud（null.trim crash 予防）", () => {
    const sel = mountSelectWithOptions("genrePrimary", [
      { value: "9", text: "Electronic" },
      { value: "25", text: "R&B／ソウル" },
    ]);

    expect(() => setNativeValue(sel, "存在しないジャンル名")).toThrow(OptionNotFoundError);
    // 一致が無いので selectedIndex も初期のまま
    expect(sel.selectedIndex).toBe(0);
  });

  it("成功時に input / change イベントを bubbles:true で発火する（React 互換）", () => {
    const sel = mountSelectWithOptions("genrePrimary", [{ value: "25", text: "R&B／ソウル" }]);
    let inputs = 0;
    let changes = 0;
    sel.addEventListener("input", (e) => {
      if (e.bubbles) inputs += 1;
    });
    sel.addEventListener("change", (e) => {
      if (e.bubbles) changes += 1;
    });

    setNativeValue(sel, "25");

    expect(inputs).toBe(1);
    expect(changes).toBe(1);
  });

  it("OptionNotFoundError は selector と payload 値を含むメッセージを持つ", () => {
    const err = new OptionNotFoundError("#genrePrimary", "Electronic");
    expect(err.message).toContain("#genrePrimary");
    expect(err.message).toContain("Electronic");
    expect(err.name).toBe("OptionNotFoundError");
  });
});

describe("injectAlbumTitle（#919 id 直接取得・fail-loud）", () => {
  it("#albumTitleInput に注入する", () => {
    // Given
    const el = mountInput({ id: "albumTitleInput", type: "text" });

    // When
    injectAlbumTitle(document, "My Album");

    // Then
    expect(el.value).toBe("My Album");
  });

  it("bbox=0 でも id があれば注入する（race condition 回避・#919）", () => {
    // Given: setTrackCount(25) 直後の DistroKid 内部 re-layout で bbox=0 になる瞬間を再現。
    // 旧 injectAlbumTitle は findVisibleField の isVisible filter で silent skip していた。
    const el = mountInput({ id: "albumTitleInput", type: "text" });
    el.getBoundingClientRect = () => ZERO_RECT;

    // When
    injectAlbumTitle(document, "My Album");

    // Then: id ベース取得なので bbox=0 でも注入される
    expect(el.value).toBe("My Album");
  });

  it("要素不在なら FieldNotFoundError（fail-loud）", () => {
    // Then: シングルモードや UI 変更で要素が消えた場合は fail-loud で気付く。
    expect(() => injectAlbumTitle(document, "X")).toThrow(FieldNotFoundError);
  });
});

describe("injectReleaseDate（#919 id 直接取得・null は skip / #932 プラン非対応は warn+skip）", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("null なら何もしない（要素不在でも throw しない）", () => {
    expect(() => injectReleaseDate(document, null)).not.toThrow();
  });

  it("値ありで #release-date-dp に注入する", () => {
    // Given
    const el = mountInput({ id: "release-date-dp", type: "date" });

    // When
    injectReleaseDate(document, "2026-07-01");

    // Then
    expect(el.value).toBe("2026-07-01");
  });

  it("bbox=0 でも id があれば注入する（race condition 回避・#919）", () => {
    // Given
    const el = mountInput({ id: "release-date-dp", type: "date" });
    el.getBoundingClientRect = () => ZERO_RECT;

    // When
    injectReleaseDate(document, "2026-07-01");

    // Then
    expect(el.value).toBe("2026-07-01");
  });

  it("値ありで要素不在でも throw せず skip し console.warn が呼ばれる（#932 プラン非対応）", () => {
    // Given: #release-date-dp が DOM に存在しない（プラン非対応の契約の模倣）
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // When / Then: throw しない
    expect(() => injectReleaseDate(document, "2026-07-01")).not.toThrow();

    // Then: console.warn が呼ばれ、セレクタが含まれる
    expect(warnSpy).toHaveBeenCalledOnce();
    expect(warnSpy.mock.calls[0][0]).toContain("#release-date-dp");
  });
});

describe("resolveTrackUuids（title_ 接頭辞を DOM order で uuid 解決）", () => {
  it("title_ input を DOM order で列挙し uuid を返す", () => {
    // Given: title 以外の input が混在しても title_ のみ拾う
    mountInput({ name: "title_uuid-a" });
    mountInput({ name: "title_uuid-b" });
    mountInput({ name: "other_field" });

    // Then
    expect(resolveTrackUuids(document)).toEqual(["uuid-a", "uuid-b"]);
  });

  it("title_ input が無ければ空配列", () => {
    expect(resolveTrackUuids(document)).toEqual([]);
  });
});

describe("injectTrackTitle", () => {
  it("uuid の title input に注入する", () => {
    // Given
    const el = mountInput({ name: "title_uuid-a" });

    // When
    injectTrackTitle(document, "uuid-a", "Song A");

    // Then
    expect(el.value).toBe("Song A");
  });
});

describe("injectSongwriter（3 分割・middle は任意）", () => {
  it("first/last を注入し、middle が null ならスキップ", () => {
    // Given
    const first = mountInput({ name: "songwriter_real_name_first1" });
    const last = mountInput({ name: "songwriter_real_name_last1" });
    const middle = mountInput({ name: "songwriter_real_name_middle1" });
    let middleChanges = 0;
    middle.addEventListener("change", () => {
      middleChanges += 1;
    });

    // When
    injectSongwriter(document, 1, { first: "Jane", last: "Doe", middle: null });

    // Then
    expect(first.value).toBe("Jane");
    expect(last.value).toBe("Doe");
    expect(middleChanges).toBe(0);
  });

  it("middle ありなら 3 欄すべて注入", () => {
    // Given
    mountInput({ name: "songwriter_real_name_first2" });
    mountInput({ name: "songwriter_real_name_last2" });
    const middle = mountInput({ name: "songwriter_real_name_middle2" });

    // When
    injectSongwriter(document, 2, { first: "A", last: "B", middle: "C" });

    // Then
    expect(middle.value).toBe("C");
  });

  it("first 欄が無ければ FieldNotFoundError", () => {
    expect(() => injectSongwriter(document, 1, SAMPLE_SONGWRITER)).toThrow(FieldNotFoundError);
  });
});

describe("assertNewRelease（新規リリース前提の assert）", () => {
  it("radio が不在なら FieldNotFoundError", () => {
    expect(() => assertNewRelease(document)).toThrow(FieldNotFoundError);
  });

  it("いいえ(value=0) が全て checked なら正常", () => {
    // Given
    const radio = mountInput({
      name: "previouslyReleased_uuid-a",
      type: "radio",
      value: "0",
    });
    radio.checked = true;

    // Then
    expect(() => assertNewRelease(document)).not.toThrow();
  });

  it("checked でなければ Error（過去公開はスコープ外 → FieldNotFoundError ではない）", () => {
    // Given: radio はあるが checked ではない（= 過去公開を選んでいる想定）
    mountInput({
      name: "previouslyReleased_uuid-a",
      type: "radio",
      value: "0",
    });

    // Then: 未検出ではないため FieldNotFoundError とは区別される
    let caught: unknown;
    try {
      assertNewRelease(document);
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(Error);
    expect(caught).not.toBeInstanceOf(FieldNotFoundError);
  });
});

describe("AI_DISCLOSURE_SELECTORS / AI_MODAL_SELECTORS（実 DOM 準拠 #877 / #888）", () => {
  it("gateByUuid は ai_gate_<uuid> の yes / no radio selector を返す", () => {
    expect(AI_DISCLOSURE_SELECTORS.gateByUuid("abc")).toEqual({
      no: '[name="ai_gate_abc"][value="0"]',
      yes: '[name="ai_gate_abc"][value="1"]',
    });
  });

  it("modal / save / apply-all は実 DOM の固定セレクタを指す", () => {
    expect(AI_MODAL_SELECTORS.modal).toBe(".ai-credits-swal-modal");
    expect(AI_MODAL_SELECTORS.saveButton).toBe("button.swal2-confirm.ai-modal-btn-save");
    expect(AI_MODAL_SELECTORS.applyAll).toBe("#ai-apply-all-1");
  });

  it("lyrics / music は modal を開いた track の uuid で selector を返す", () => {
    expect(AI_MODAL_SELECTORS.lyricsByUuid("abc")).toBe('[name="ai_lyrics_abc"]');
    expect(AI_MODAL_SELECTORS.musicByUuid("abc")).toBe('[name="ai_music_abc"]');
  });

  it("recordingScopeByTrack は class+track+value の radio selector を返す（name は null）", () => {
    expect(AI_MODAL_SELECTORS.recordingScopeByTrack(1, "full")).toBe(
      '[class*="distroAiRecordingScope"][track="1"][value="full"]',
    );
    expect(AI_MODAL_SELECTORS.recordingScopeByTrack(1, "partial")).toBe(
      '[class*="distroAiRecordingScope"][track="1"][value="partial"]',
    );
  });

  it("partialAudioTypeByUuid は vocals / instruments radio selector を返す", () => {
    expect(AI_MODAL_SELECTORS.partialAudioTypeByUuid("abc", "vocals")).toBe(
      '[name="ai_partial_audio_type_abc"][value="vocals"]',
    );
    expect(AI_MODAL_SELECTORS.partialAudioTypeByUuid("abc", "instruments")).toBe(
      '[name="ai_partial_audio_type_abc"][value="instruments"]',
    );
  });

  it("artistPersonaByUuid は 人間(0) / AI ペルソナ(1) radio selector を返す", () => {
    expect(AI_MODAL_SELECTORS.artistPersonaByUuid("abc", "0")).toBe('[name="ai_artist_persona_abc_0"][value="0"]');
    expect(AI_MODAL_SELECTORS.artistPersonaByUuid("abc", "1")).toBe('[name="ai_artist_persona_abc_0"][value="1"]');
  });
});

describe("waitForElement / waitForRemoval（MutationObserver ベース）", () => {
  it("既に存在する要素は即解決する", async () => {
    const el = mountInput({ id: "already-here" });
    await expect(waitForElement(document, "#already-here", 1000)).resolves.toBe(el);
  });

  it("後から mount される要素を MutationObserver で解決する", async () => {
    const promise = waitForElement(document, "#late", 1000);
    setTimeout(() => mountInput({ id: "late" }), 0);
    const resolved = await promise;
    expect(resolved.id).toBe("late");
  });

  it("制限時間内に出現しなければ ModalTimeoutError で fail-loud", async () => {
    await expect(waitForElement(document, "#never", 20)).rejects.toBeInstanceOf(ModalTimeoutError);
  });

  it("既に DOM 外の要素は即解決する（waitForRemoval）", async () => {
    const el = document.createElement("div");
    await expect(waitForRemoval(el, 1000)).resolves.toBeUndefined();
  });

  it("後から除去される要素を解決する（waitForRemoval）", async () => {
    const el = mountInput({ id: "to-remove" });
    const promise = waitForRemoval(el, 1000);
    setTimeout(() => el.remove(), 0);
    await expect(promise).resolves.toBeUndefined();
  });
});

describe("waitForElementCount（#888 track 行生成待ち）", () => {
  it("既に count 個あれば即解決する", async () => {
    mountInput({ name: "title_a" });
    mountInput({ name: "title_b" });
    await expect(waitForElementCount(document, '[name^="title_"]', 2, 1000)).resolves.toBeUndefined();
  });

  it("後から count 個に達するのを MutationObserver で解決する", async () => {
    const promise = waitForElementCount(document, '[name^="title_"]', 2, 1000);
    setTimeout(() => {
      mountInput({ name: "title_a" });
      mountInput({ name: "title_b" });
    }, 0);
    await expect(promise).resolves.toBeUndefined();
  });

  it("制限時間内に達しなければ TrackCountTimeoutError で fail-loud", async () => {
    mountInput({ name: "title_a" });
    await expect(waitForElementCount(document, '[name^="title_"]', 3, 20)).rejects.toBeInstanceOf(
      TrackCountTimeoutError,
    );
  });
});

describe("setTrackCount（#888 トラック数 select + 行生成待機）", () => {
  it("select に曲数を set + change 発火し、行が揃えば解決する", async () => {
    // Given: select と、既に揃った 2 つの title 行
    const select = mountSelect("howManySongsOnThisAlbum", ["1", "2", "3"]);
    mountInput({ name: "title_a" });
    mountInput({ name: "title_b" });
    let changes = 0;
    select.addEventListener("change", () => {
      changes += 1;
    });

    // When
    await setTrackCount(document, 2);

    // Then: 値がセットされ change が発火する
    expect(select.value).toBe("2");
    expect(changes).toBeGreaterThan(0);
  });

  it("change で後から生成される track 行を待つ", async () => {
    // Given: change で 2 行を遅延生成する select
    const select = mountSelect("howManySongsOnThisAlbum", ["1", "2"]);
    select.addEventListener("change", () => {
      setTimeout(() => {
        mountInput({ name: "title_a" });
        mountInput({ name: "title_b" });
      }, 0);
    });

    // When / Then: 行生成を待って解決し、uuid が DOM order で解決できる
    await expect(setTrackCount(document, 2)).resolves.toBeUndefined();
    expect(resolveTrackUuids(document)).toEqual(["a", "b"]);
  });

  it("select が無ければ FieldNotFoundError で fail-loud", async () => {
    await expect(setTrackCount(document, 2)).rejects.toBeInstanceOf(FieldNotFoundError);
  });
});

describe("injectAppleMusicCredits（#888 / #919 Apple Music クレジット・role 含む）", () => {
  // #artistName + trigger + 各 track の performer/producer の name + role を mount する。
  // role は実機 DOM に合わせて `dk-searchable-select__native` 相当のネイティブ select として組む
  // （options は profile.credits に揃えるためのデフォルト Audio / Producer + 担当未選択を含む）。
  function mountCreditDom(
    trackCount: number,
    opts: { artist: string; mountRole?: boolean },
  ): { getTriggerClicks: () => number } {
    const mountRole = opts.mountRole ?? true;
    const artist = document.createElement("input");
    artist.id = "artistName";
    artist.type = "hidden";
    artist.setAttribute("value", opts.artist);
    document.body.appendChild(artist);

    const trigger = document.createElement("div");
    trigger.className = "requirements-item-title";
    trigger.textContent = "クレジットを追加";
    makeVisible(trigger as HTMLElement);
    document.body.appendChild(trigger);
    let triggerClicks = 0;
    trigger.addEventListener("click", () => {
      triggerClicks += 1;
    });

    // credit 入力欄は DOM 上に事前存在する（trigger click で visible 化するだけ）。
    for (let n = 1; n <= trackCount; n += 1) {
      mountInput({ id: `track-${n}-performer-1-name`, name: "performer-name" });
      mountInput({ id: `track-${n}-producer-1-name`, name: "producer-name" });
      if (mountRole) {
        // performer role: 86 options のサブセット（unselected + Audio + Synthesizer）。
        mountSelectWithOptions(`track-${n}-performer-1-role`, [
          { value: "unselected", text: "担当を選択" },
          { value: "Audio", text: "オーディオ" },
          { value: "Synthesizer", text: "シンセサイザー" },
        ]);
        // producer role: 40 options のサブセット（unselected + Producer + Executive producer）。
        mountSelectWithOptions(`track-${n}-producer-1-role`, [
          { value: "unselected", text: "担当を選択" },
          { value: "Producer", text: "プロデューサー" },
          { value: "Executive producer", text: "エグゼクティブプロデューサー" },
        ]);
      }
    }
    return { getTriggerClicks: () => triggerClicks };
  }

  it("trigger を 1 回 click し、全 track の name / role を注入する", async () => {
    // Given
    const { getTriggerClicks } = mountCreditDom(3, { artist: "Soulful Grooves" });

    // When
    await injectAppleMusicCredits(document, 3, SAMPLE_CREDITS);

    // Then: トリガーは 1 回だけ click され、全 track の name + role が注入される
    expect(getTriggerClicks()).toBe(1);
    for (let n = 1; n <= 3; n += 1) {
      expect(document.querySelector<HTMLInputElement>(`#track-${n}-performer-1-name`)!.value).toBe("Soulful Grooves");
      expect(document.querySelector<HTMLSelectElement>(`#track-${n}-performer-1-role`)!.value).toBe("Audio");
      expect(document.querySelector<HTMLInputElement>(`#track-${n}-producer-1-name`)!.value).toBe("Soulful Grooves");
      expect(document.querySelector<HTMLSelectElement>(`#track-${n}-producer-1-role`)!.value).toBe("Producer");
    }
  });

  it("role select の change event が dispatch される（独自 UI 同期のため）", async () => {
    // Given: change event を観測する
    mountCreditDom(1, { artist: "X" });
    const perfRole = document.querySelector<HTMLSelectElement>("#track-1-performer-1-role")!;
    const prodRole = document.querySelector<HTMLSelectElement>("#track-1-producer-1-role")!;
    let perfChanges = 0;
    let prodChanges = 0;
    perfRole.addEventListener("change", () => {
      perfChanges += 1;
    });
    prodRole.addEventListener("change", () => {
      prodChanges += 1;
    });

    // When
    await injectAppleMusicCredits(document, 1, SAMPLE_CREDITS);

    // Then: setSelectValue は input + change を bubbles:true で 1 回ずつ dispatch する。
    // 実機 DistroKid の `dk-searchable-select` 独自 UI は change を listen して表示テキストを同期する。
    expect(perfChanges).toBe(1);
    expect(prodChanges).toBe(1);
  });

  it("複数の .requirements-item-title から「クレジットを追加」を textContent で選ぶ", async () => {
    // Given: 無関係な requirements-item-title が先に存在する
    const decoy = document.createElement("div");
    decoy.className = "requirements-item-title";
    decoy.textContent = "別の要件";
    let decoyClicks = 0;
    decoy.addEventListener("click", () => {
      decoyClicks += 1;
    });
    document.body.appendChild(decoy);
    const { getTriggerClicks } = mountCreditDom(1, { artist: "X" });

    // When
    await injectAppleMusicCredits(document, 1, SAMPLE_CREDITS);

    // Then: 「クレジットを追加」のみ click され、decoy は触らない
    expect(getTriggerClicks()).toBe(1);
    expect(decoyClicks).toBe(0);
  });

  it("#artistName が無ければ FieldNotFoundError", async () => {
    // Given: trigger と入力欄はあるが #artistName が無い
    const trigger = document.createElement("div");
    trigger.className = "requirements-item-title";
    trigger.textContent = "クレジットを追加";
    document.body.appendChild(trigger);
    mountInput({ id: "track-1-performer-1-name", name: "performer-name" });
    mountInput({ id: "track-1-producer-1-name", name: "producer-name" });

    // Then: async function → rejected promise
    await expect(injectAppleMusicCredits(document, 1, SAMPLE_CREDITS)).rejects.toBeInstanceOf(FieldNotFoundError);
  });

  it("#artistName が空なら fail-loud（FieldNotFoundError ではない）", async () => {
    // Given: #artistName はあるが値が空
    mountCreditDom(1, { artist: "" });

    // Then: 未検出ではないため FieldNotFoundError とは区別される
    let caught: unknown;
    try {
      await injectAppleMusicCredits(document, 1, SAMPLE_CREDITS);
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(Error);
    expect(caught).not.toBeInstanceOf(FieldNotFoundError);
  });

  it("trigger が無ければ FieldNotFoundError", async () => {
    // Given: #artistName と入力欄はあるが trigger が無い
    const artist = document.createElement("input");
    artist.id = "artistName";
    artist.type = "hidden";
    artist.setAttribute("value", "X");
    document.body.appendChild(artist);
    mountInput({ id: "track-1-performer-1-name", name: "performer-name" });
    mountInput({ id: "track-1-producer-1-name", name: "producer-name" });

    // Then: async function → rejected promise
    await expect(injectAppleMusicCredits(document, 1, SAMPLE_CREDITS)).rejects.toBeInstanceOf(FieldNotFoundError);
  });

  it("performer name 欄が無ければ FieldNotFoundError", async () => {
    // Given: trigger と #artistName はあるが producer のみで performer name 欄が無い
    const artist = document.createElement("input");
    artist.id = "artistName";
    artist.type = "hidden";
    artist.setAttribute("value", "X");
    document.body.appendChild(artist);
    const trigger = document.createElement("div");
    trigger.className = "requirements-item-title";
    trigger.textContent = "クレジットを追加";
    makeVisible(trigger as HTMLElement);
    document.body.appendChild(trigger);
    mountInput({ id: "track-1-producer-1-name", name: "producer-name" });
    mountSelectWithOptions("track-1-producer-1-role", [{ value: "Producer", text: "プロデューサー" }]);

    // Then
    await expect(injectAppleMusicCredits(document, 1, SAMPLE_CREDITS)).rejects.toBeInstanceOf(FieldNotFoundError);
  });

  it("performer role select が無ければ FieldNotFoundError", async () => {
    // Given: role select だけが欠落している（name 欄は揃っている）
    mountCreditDom(1, { artist: "X", mountRole: false });

    // Then
    await expect(injectAppleMusicCredits(document, 1, SAMPLE_CREDITS)).rejects.toBeInstanceOf(FieldNotFoundError);
  });

  it("role が option に無ければ OptionNotFoundError", async () => {
    // Given: performer_role に "NonExistent" を指定し、option に無い値を要求する
    mountCreditDom(1, { artist: "X" });

    // Then: setSelectValue が fail-loud
    await expect(
      injectAppleMusicCredits(document, 1, { performer_role: "NonExistent", producer_role: "Producer" }),
    ).rejects.toBeInstanceOf(OptionNotFoundError);
  });

  it("CREDIT_TRIGGER_WAIT_TIMEOUT_MS は 10_000 ms（既存定数群と同値）", () => {
    // #923: checkAllStores() 後の DistroKid 側 re-render で credit trigger が可視化されるまでの待ち上限
    expect(CREDIT_TRIGGER_WAIT_TIMEOUT_MS).toBe(10_000);
  });
});

describe("uncheckUpsells（#919 オプション強制 $0 保証）", () => {
  it("checked な name=store / name=extras を全部 uncheck する", () => {
    // Given: ディスカバリーパック (store) と複数の extras (legacy / mastering / store-maximizer 等)
    const store = makeCheckbox(document.body, { name: "store" });
    store.checked = true;
    const legacy = makeCheckbox(document.body, { name: "extras" });
    legacy.checked = true;
    const distroVid = makeCheckbox(document.body, { name: "extras" });
    distroVid.checked = true;

    // When
    uncheckUpsells(document);

    // Then: すべて uncheck になる
    expect(store.checked).toBe(false);
    expect(legacy.checked).toBe(false);
    expect(distroVid.checked).toBe(false);
  });

  it("既に全 unchecked なら no-op（click しない）", () => {
    // Given
    const store = makeCheckbox(document.body, { name: "store" });
    const extras = makeCheckbox(document.body, { name: "extras" });
    let clicks = 0;
    store.addEventListener("click", () => {
      clicks += 1;
    });
    extras.addEventListener("click", () => {
      clicks += 1;
    });

    // When
    uncheckUpsells(document);

    // Then
    expect(clicks).toBe(0);
    expect(store.checked).toBe(false);
    expect(extras.checked).toBe(false);
  });

  it("upsell 配下が空でも throw しない（forEach の空配列）", () => {
    expect(() => uncheckUpsells(document)).not.toThrow();
  });

  it("name=store / name=extras 以外の checkbox は触らない", () => {
    // Given: 利用規約 checkbox（#areyousuretandc）は touch しない
    const terms = makeCheckbox(document.body, { id: "areyousuretandc" });
    terms.checked = true;

    // When
    uncheckUpsells(document);

    // Then
    expect(terms.checked).toBe(true);
  });

  it("セレクタ定数は実機 DOM の name 属性を保証する（#923 chk* 除外版）", () => {
    expect(UPSELL_SELECTORS.store).toBe('input[type="checkbox"][name="store"]:not([id^="chk"])');
    expect(UPSELL_SELECTORS.extras).toBe('input[type="checkbox"][name="extras"]');
  });
});

describe("checkAllStores（#923 / #928 配信先ストア check・除外 2 ストア uncheck 保証）", () => {
  it("除外 2 ストア（chksnap / chkroblox）以外の chk* を check する", () => {
    // Given
    const cb1 = makeCheckbox(document.body, { id: "chkspotify", name: "store" });
    const cb2 = makeCheckbox(document.body, { id: "chkapplemusic", name: "store" });
    const cbSnap = makeCheckbox(document.body, { id: "chksnap", name: "store" });
    const cbRoblox = makeCheckbox(document.body, { id: "chkroblox", name: "store" });

    // When
    checkAllStores(document);

    // Then: 除外 2 ストア以外は check、除外 2 ストアは unchecked のまま
    expect(cb1.checked).toBe(true);
    expect(cb2.checked).toBe(true);
    expect(cbSnap.checked).toBe(false);
    expect(cbRoblox.checked).toBe(false);
  });

  it("chksnap / chkroblox が事前に checked の場合は uncheck される（DistroKid デフォルト全 check からの配信外保証）", () => {
    // Given: DistroKid のデフォルト全 check 状態を再現
    const cbSnap = makeCheckbox(document.body, { id: "chksnap", name: "store" });
    cbSnap.checked = true;
    const cbRoblox = makeCheckbox(document.body, { id: "chkroblox", name: "store" });
    cbRoblox.checked = true;
    const cbSpotify = makeCheckbox(document.body, { id: "chkspotify", name: "store" });
    cbSpotify.checked = true;

    // When
    checkAllStores(document);

    // Then: 除外 2 ストアは uncheck される
    expect(cbSnap.checked).toBe(false);
    expect(cbRoblox.checked).toBe(false);
    // 他ストアは check 維持（no-op）
    expect(cbSpotify.checked).toBe(true);
  });

  it("chk* id なし（shazam / audiomack）は check しない", () => {
    // Given: id^="chk" を持つ配信先と id なし upsell が混在
    const real = makeCheckbox(document.body, { id: "chkspotify", name: "store" });
    const shazam = makeCheckbox(document.body, { name: "store" });
    shazam.setAttribute("value", "shazam");
    shazam.checked = false;

    // When
    checkAllStores(document);

    // Then: 配信先は check、shazam は untouched
    expect(real.checked).toBe(true);
    expect(shazam.checked).toBe(false);
  });

  it("対象 0 件で FieldNotFoundError（fail-loud）", () => {
    // Given: name=store の checkbox が一切無い
    // Then: UI 変更検知のため fail-loud
    expect(() => checkAllStores(document)).toThrow(FieldNotFoundError);
  });

  it("STORE_SELECTORS.distribution は id^=chk の配信先だけ対象にする", () => {
    expect(STORE_SELECTORS.distribution).toBe('input[type="checkbox"][name="store"][id^="chk"]');
  });

  it('EXCLUDED_STORE_IDS は ["chksnap", "chkroblox"] の契約を固定する', () => {
    expect(EXCLUDED_STORE_IDS).toEqual(["chksnap", "chkroblox"]);
  });
});

describe("uncheckUpsells（#923 chk* 配信先を巻き込まない回帰）", () => {
  it("chk* id を持つ store は uncheck しない（#923 回帰防止）", () => {
    // Given: 配信先 checkbox（id^="chk"）が checked
    const spotify = makeCheckbox(document.body, { id: "chkspotify", name: "store" });
    spotify.checked = true;
    let spotifyClicks = 0;
    spotify.addEventListener("click", () => {
      spotifyClicks += 1;
    });

    // When
    uncheckUpsells(document);

    // Then: 配信先は touch しない（UPSELL_SELECTORS.store は :not([id^="chk"]) を含む）
    expect(spotifyClicks).toBe(0);
    expect(spotify.checked).toBe(true);
  });

  it("shazam（id なし name=store）は uncheck する", () => {
    // Given: Discovery Pack（shazam）は id なし
    const shazam = makeCheckbox(document.body, { name: "store" });
    shazam.setAttribute("value", "shazam");
    shazam.checked = true;

    // When
    uncheckUpsells(document);

    // Then: shazam は uncheck される
    expect(shazam.checked).toBe(false);
  });

  it("extras は uncheck する", () => {
    // Given
    const legacy = makeCheckbox(document.body, { name: "extras" });
    legacy.checked = true;

    // When
    uncheckUpsells(document);

    // Then
    expect(legacy.checked).toBe(false);
  });
});

describe("acceptImportantTerms（#923 重要事項 4 個 + 条件付き）", () => {
  // required 4 個を mount（bbox=0 でも check されることを確認するため getBoundingClientRect をモックしない）
  function mountRequiredTerms(): HTMLInputElement[] {
    return ["#areyousurepromoservices", "#areyousurerecorded", "#areyousureotherartist", "#areyousuretandc"].map(
      (id) => {
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = id.slice(1);
        cb.className = "areyousure";
        document.body.appendChild(cb);
        return cb;
      },
    );
  }

  it("required 4 個を bbox=0 でも check する（rect 0×0 レース回避）", () => {
    // Given: 4 個は bbox=0（isVisible で false だが id 直接取得で check される）
    const cbs = mountRequiredTerms();
    // bbox=0 のまま（makeVisible しない）

    // When
    acceptImportantTerms(document);

    // Then: 全部 check される
    for (const cb of cbs) {
      expect(cb.checked).toBe(true);
    }
  });

  it("conditional の可視のもののみ check する（不可視は skip）", () => {
    // Given: required 4 個 + 可視 conditional 1 個 + 不可視 conditional 1 個
    mountRequiredTerms();
    const visibleCond = document.createElement("input");
    visibleCond.type = "checkbox";
    visibleCond.id = "areyousureyoutube";
    visibleCond.className = "areyousure";
    makeVisible(visibleCond);
    document.body.appendChild(visibleCond);
    const hiddenCond = document.createElement("input");
    hiddenCond.type = "checkbox";
    hiddenCond.id = "areyousuresnap";
    hiddenCond.className = "areyousure";
    // bbox=0 → isVisible false → skip
    document.body.appendChild(hiddenCond);

    // When
    acceptImportantTerms(document);

    // Then: visible は check、hidden は skip
    expect(visibleCond.checked).toBe(true);
    expect(hiddenCond.checked).toBe(false);
  });

  it("required id のいずれかが不在なら FieldNotFoundError", () => {
    // Given: areyousuretandc だけない
    for (const id of ["areyousurepromoservices", "areyousurerecorded", "areyousureotherartist"]) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id = id;
      document.body.appendChild(cb);
    }

    // Then
    expect(() => acceptImportantTerms(document)).toThrow(FieldNotFoundError);
  });

  it("#areyousuretandc が既に checked なら no-op（click せず checked を維持）", () => {
    // Given: required 4 個を mount し、#areyousuretandc だけ事前 check
    const cbs = mountRequiredTerms();
    const tandc = cbs.find((cb) => cb.id === "areyousuretandc")!;
    tandc.checked = true;
    let clicks = 0;
    tandc.addEventListener("click", () => {
      clicks += 1;
    });

    // When
    acceptImportantTerms(document);

    // Then: setChecked は目標と一致なら click しない
    expect(clicks).toBe(0);
    expect(tandc.checked).toBe(true);
  });
});

describe("VisibilityTimeoutError / waitForElementVisible（#923）", () => {
  it("既に可視なら即解決する", async () => {
    // Given: bbox 非 0 の要素
    const el = document.createElement("div");
    el.id = "test-visible";
    makeVisible(el as HTMLElement);
    document.body.appendChild(el);

    // Then: 即解決
    await expect(waitForElementVisible(el, 1000)).resolves.toBeUndefined();
  });

  it("後から可視化される要素を解決する", async () => {
    // Given: 最初は bbox=0
    const el = document.createElement("div");
    el.id = "test-late-visible";
    document.body.appendChild(el);
    const promise = waitForElementVisible(el, 1000);
    // 後から可視化（getBoundingClientRect を mock して MutationObserver をトリガー）
    setTimeout(() => {
      makeVisible(el as HTMLElement);
      // attribute 変更で MutationObserver をトリガー
      el.setAttribute("style", "display:block");
    }, 0);

    // Then
    await expect(promise).resolves.toBeUndefined();
  });

  it("制限時間内に可視化されなければ VisibilityTimeoutError", async () => {
    // Given: bbox=0 のまま
    const el = document.createElement("div");
    el.id = "test-never-visible";
    document.body.appendChild(el);

    // Then
    await expect(waitForElementVisible(el, 20)).rejects.toBeInstanceOf(VisibilityTimeoutError);
  });

  it("RELOAD_GUIDANCE が ModalTimeoutError / TrackCountTimeoutError / VisibilityTimeoutError の message に含まれる", () => {
    expect(new ModalTimeoutError("#foo").message).toContain(RELOAD_GUIDANCE);
    expect(new TrackCountTimeoutError("#foo", 2).message).toContain(RELOAD_GUIDANCE);
    expect(new VisibilityTimeoutError("#foo").message).toContain(RELOAD_GUIDANCE);
  });
});

describe("scrollToDoneButton（#919 フィル完了後の UX 補助）", () => {
  it("要素ありで scrollIntoView を呼ぶ", () => {
    // Given
    const btn = document.createElement("button");
    btn.id = "doneButton";
    document.body.appendChild(btn);
    let scrollCalls = 0;
    btn.scrollIntoView = ((arg: ScrollIntoViewOptions | boolean) => {
      scrollCalls += 1;
      // smooth + center が指定されていることを assert
      expect(arg).toEqual({ behavior: "smooth", block: "center" });
    }) as typeof btn.scrollIntoView;

    // When
    scrollToDoneButton(document);

    // Then
    expect(scrollCalls).toBe(1);
  });

  it("要素不在でも throw しない（補助 UX のため致命ではない）", () => {
    expect(() => scrollToDoneButton(document)).not.toThrow();
  });

  it("セレクタ定数は #doneButton を保証する", () => {
    expect(DONE_BUTTON_SELECTOR).toBe("#doneButton");
  });
});

describe("injectAiDisclosure（#877 / #888 modal フロー・段階的 trigger・async）", () => {
  it("title input (track) が無ければ FieldNotFoundError（uuid 解決不可）", async () => {
    await expect(injectAiDisclosure(document, SAMPLE_AI)).rejects.toBeInstanceOf(FieldNotFoundError);
  });

  it("enabled=true で 1st track の「はい」を 1 回だけ click し modal を開閉する", async () => {
    // Given: 2 track（1st の「はい」で album modal が開く）
    const { gates, getModalRefs } = setupModalForm(["uuid-a", "uuid-b"]);
    let track2YesClicks = 0;
    gates[1].gateYes.addEventListener("click", () => {
      track2YesClicks += 1;
    });

    // When
    await injectAiDisclosure(document, SAMPLE_AI);

    // Then: 1st track の yes が確定、2nd track の gate は触らない（modal の apply-all が伝播担当）
    expect(gates[0].gateYes.checked).toBe(true);
    expect(track2YesClicks).toBe(0);
    // Then: modal は保存後 unmount している（1 回だけ開いて閉じる）
    expect(document.querySelector(AI_MODAL_SELECTORS.modal)).toBeNull();
    expect(getModalRefs()?.saveClicks()).toBe(1);
  });

  it("modal 内で lyrics / music / recording_scope(full) を設定し、full check 後に inject される persona(AI) と apply-all を設定する", async () => {
    const { getModalRefs } = setupModalForm(["uuid-a"], { album: true });

    await injectAiDisclosure(document, SAMPLE_AI);

    const refs = getModalRefs();
    expect(refs).not.toBeNull();
    expect(refs!.lyrics.checked).toBe(true);
    expect(refs!.music.checked).toBe(true);
    expect(refs!.scopeFull.checked).toBe(true);
    expect(refs!.scopePartial.checked).toBe(false);
    // full check で dynamic inject された persona radio（AI=value:1）が選ばれている
    expect(refs!.getPersona("1")?.checked).toBe(true);
    expect(refs!.getPersona("0")?.checked).toBe(false);
    expect(refs!.applyAll!.checked).toBe(true);
    // recording_scope=full なので partial 種別 radio には触れない
    expect(refs!.partialVocals.checked).toBe(false);
    expect(refs!.partialInstruments.checked).toBe(false);
  });

  it("artist_persona=false なら 人間アーティスト(value=0) を選ぶ", async () => {
    const { getModalRefs } = setupModalForm(["uuid-a"], { album: true });

    await injectAiDisclosure(document, { ...SAMPLE_AI, artist_persona: false });

    const refs = getModalRefs()!;
    expect(refs.getPersona("0")?.checked).toBe(true);
    expect(refs.getPersona("1")?.checked).toBe(false);
  });

  it("recording_scope='partial' + partial_audio_type='vocals' で partial radio を選ぶ（persona は inject されない）", async () => {
    const { getModalRefs } = setupModalForm(["uuid-a"], { album: true });

    await injectAiDisclosure(document, {
      ...SAMPLE_AI,
      recording_scope: "partial",
      partial_audio_type: "vocals",
    });

    const refs = getModalRefs()!;
    expect(refs.scopePartial.checked).toBe(true);
    expect(refs.partialVocals.checked).toBe(true);
    expect(refs.partialInstruments.checked).toBe(false);
    // partial では persona radio は inject されない（full 専用の段階的 trigger）
    expect(refs.getPersona("0")).toBeNull();
    expect(refs.getPersona("1")).toBeNull();
  });

  it("apply_to_all=false なら apply-all checkbox を入れない", async () => {
    const { getModalRefs } = setupModalForm(["uuid-a"], { album: true });

    await injectAiDisclosure(document, { ...SAMPLE_AI, apply_to_all: false });

    expect(getModalRefs()!.applyAll!.checked).toBe(false);
  });

  it("single mode（apply-all 不在）でも fail-loud せず full フローを完走する", async () => {
    // Given: apply-all を持たない single mode modal
    const { getModalRefs } = setupModalForm(["uuid-a"], { album: false });

    // When / Then: apply-all 不在を許容して完走する
    await expect(injectAiDisclosure(document, SAMPLE_AI)).resolves.toBeUndefined();
    const refs = getModalRefs()!;
    expect(refs.applyAll).toBeNull();
    expect(refs.scopeFull.checked).toBe(true);
    expect(refs.getPersona("1")?.checked).toBe(true);
  });

  it("partial_audio_type=undefined でも FieldNotFoundError を出さない（loose equality 回帰 #877）", async () => {
    // Given: recording_scope=partial だが partial_audio_type が undefined（旧バグの再現条件）
    const { getModalRefs } = setupModalForm(["uuid-a"], { album: true });
    const ai = {
      ...SAMPLE_AI,
      recording_scope: "partial",
      partial_audio_type: undefined,
    } as unknown as AiDisclosure;

    // Then: `[value="undefined"]` selector を組まず、partial radio を skip して完走する
    await expect(injectAiDisclosure(document, ai)).resolves.toBeUndefined();
    const refs = getModalRefs()!;
    expect(refs.partialVocals.checked).toBe(false);
    expect(refs.partialInstruments.checked).toBe(false);
  });

  it("enabled=false なら modal を開かず全 track の「いいえ」を明示確定する", async () => {
    // Given: 初期に yes が checked（過去操作の影響を仮想）
    const { gates } = setupModalForm(["uuid-a", "uuid-b"]);
    gates[0].gateNo.checked = false;
    gates[0].gateYes.checked = true;

    // When
    await injectAiDisclosure(document, { ...SAMPLE_AI, enabled: false });

    // Then: modal は開かず、全 track の「いいえ」が確定
    expect(document.querySelector(AI_MODAL_SELECTORS.modal)).toBeNull();
    expect(gates[0].gateNo.checked).toBe(true);
    expect(gates[1].gateNo.checked).toBe(true);
  });

  it("modal 内に保存ボタンが無ければ FieldNotFoundError で fail-loud", async () => {
    // Given: gate「はい」で modal は開くが save ボタンが無い不正 modal。
    // persona inject 待ちを避けるため partial scope で開く。
    mountTrackGate("uuid-a");
    const yes = document.querySelector<HTMLInputElement>('[name="ai_gate_uuid-a"][value="1"]')!;
    yes.addEventListener("click", () => {
      setTimeout(() => {
        const modal = document.createElement("div");
        modal.className = "ai-credits-swal-modal";
        const details = document.createElement("div");
        withClass(makeCheckbox(details, { name: "ai_lyrics_uuid-a" }), "distroAiLyrics");
        withClass(makeCheckbox(details, { name: "ai_music_uuid-a" }), "distroAiMusic");
        // partial scope radio（track=1）。partial_audio_type=null で種別設定は skip される。
        makeScopeRadio(details, 1, "partial");
        modal.appendChild(details);
        // save ボタンを欠く
        document.body.appendChild(modal);
      }, 0);
    });

    await expect(
      injectAiDisclosure(document, {
        ...SAMPLE_AI,
        recording_scope: "partial",
        partial_audio_type: null,
        apply_to_all: false,
      }),
    ).rejects.toBeInstanceOf(FieldNotFoundError);
  });
});

describe("FieldNotFoundError（fail-loud）", () => {
  it("未検出セレクタを名前付きエラーで表現する", () => {
    const err = new FieldNotFoundError("#language");
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("FieldNotFoundError");
    expect(err.message).toContain("#language");
  });
});
