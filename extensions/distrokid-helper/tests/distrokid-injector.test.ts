// @vitest-environment jsdom
//
// `lib/distrokid-injector.ts` のセレクタ契約 + 注入オーケストレーションのテスト（#813）。
//
// このバグ修正の核心は「PR #803 の想像セレクタ（name 属性ベース）を、実 DOM 検証に基づく
// id ベースセレクタへ刷新する」こと。前半はセレクタ定数が実 DOM 検証サマリ（order.md）と
// 1:1 一致することを固定する。後半は注入オーケストレーション関数（プロファイル / アルバム名 /
// リリース日 / track uuid 解決 / songwriter / 新規リリース assert / AI 開示モーダル）の
// 受け入れ条件に直結する分岐を jsdom で固定する。
//
// jsdom はレイアウトを行わず getBoundingClientRect() が常に全 0 を返すため、可視要素には
// VISIBLE_RECT を擬似付与する（production の strict isVisible は bbox を見て hidden を排除する）。
// File 注入（DataTransfer）と MutationObserver による実展開待ちのうち、DOM 非同期挿入のみ
// jsdom で再現できる。実 file input への DataTransfer セットは Playwright（tests/e2e）が担う。

import { describe, it, expect, beforeEach } from "vitest";
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
  waitForElement,
  waitForRemoval,
  PROFILE_SELECTORS,
  ALBUM_SELECTORS,
  RELEASE_DATE_SELECTOR,
  FILE_SELECTORS,
  TRACK_FIELD_SELECTORS,
  AI_DISCLOSURE_SELECTORS,
  AI_MODAL_SELECTORS,
  FieldNotFoundError,
  ModalTimeoutError,
} from "../lib/distrokid-injector";
import type {
  DistrokidProfile,
  AiDisclosure,
  SongwriterName,
} from "../lib/types";

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
function mountInput(attrs: {
  id?: string;
  name?: string;
  type?: string;
  value?: string;
}): HTMLInputElement {
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

function makeCheckbox(
  parent: ParentNode,
  attrs: { id?: string; name?: string },
): HTMLInputElement {
  const cb = document.createElement("input");
  cb.type = "checkbox";
  if (attrs.id !== undefined) cb.id = attrs.id;
  if (attrs.name !== undefined) cb.name = attrs.name;
  (parent as Node).appendChild(cb);
  return cb;
}

function makeRadio(
  parent: ParentNode,
  attrs: { name: string; value: string },
): HTMLInputElement {
  const r = document.createElement("input");
  r.type = "radio";
  r.name = attrs.name;
  r.setAttribute("value", attrs.value);
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

// 実 DOM 再検証（#877）に基づく SweetAlert2 modal を組み立てる（uuid は modal を開いた 1st track）。
interface ModalRefs {
  modal: HTMLElement;
  lyrics: HTMLInputElement;
  music: HTMLInputElement;
  scopeFull: HTMLInputElement;
  scopePartial: HTMLInputElement;
  partialVocals: HTMLInputElement;
  partialInstruments: HTMLInputElement;
  personaHuman: HTMLInputElement;
  personaAi: HTMLInputElement;
  applyAll: HTMLInputElement;
  save: HTMLButtonElement;
  saveClicks: () => number;
}

function withClass<T extends HTMLElement>(el: T, className: string): T {
  el.classList.add(className);
  return el;
}

function buildModal(uuid: string): ModalRefs {
  const modal = document.createElement("div");
  modal.className = "ai-credits-swal-modal";
  modal.setAttribute("role", "dialog");
  const details = document.createElement("div");
  details.id = "ai-details-1";
  modal.appendChild(details);

  const lyrics = withClass(makeCheckbox(details, { name: `ai_lyrics_${uuid}` }), "distroAiLyrics");
  const music = withClass(makeCheckbox(details, { name: `ai_music_${uuid}` }), "distroAiMusic");

  const scopeName = `ai_recording_scope_${uuid}`;
  const scopeFull = withClass(
    makeRadio(details, { name: scopeName, value: "full" }),
    "distroAiRecordingScope",
  );
  const scopePartial = withClass(
    makeRadio(details, { name: scopeName, value: "partial" }),
    "distroAiRecordingScope",
  );

  const partialVocals = withClass(
    makeRadio(details, { name: `ai_partial_audio_type_${uuid}`, value: "vocals" }),
    "distroAiPartialAudioType",
  );
  const partialInstruments = withClass(
    makeRadio(details, { name: `ai_partial_audio_type_${uuid}`, value: "instruments" }),
    "distroAiPartialAudioType",
  );

  const personaName = `ai_artist_persona_${uuid}_0`;
  const personaHuman = withClass(
    makeRadio(details, { name: personaName, value: "0" }),
    "distroAiArtistPersona",
  );
  const personaAi = withClass(
    makeRadio(details, { name: personaName, value: "1" }),
    "distroAiArtistPersona",
  );

  const applyAll = makeCheckbox(details, { id: "ai-apply-all-1" });

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
    personaHuman,
    personaAi,
    applyAll,
    save,
    saveClicks: () => saveClicks,
  };
}

// track gate を mount し、1st track の「はい」click で modal を遅延 mount する配線を張る。
// setTimeout(0) で mount することで injector 側 MutationObserver の待機経路を実際に通す。
function setupModalForm(uuids: string[]): {
  gates: { uuid: string; gateNo: HTMLInputElement; gateYes: HTMLInputElement }[];
  getModalRefs: () => ModalRefs | null;
} {
  let modalRefs: ModalRefs | null = null;
  const gates = uuids.map((uuid) => {
    const { gateNo, gateYes } = mountTrackGate(uuid);
    gateYes.addEventListener("click", () => {
      setTimeout(() => {
        if (document.querySelector(AI_MODAL_SELECTORS.modal) === null) {
          modalRefs = buildModal(uuid);
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
// 旧フラット 6 文字列（artist_name 等）が無いこと・nested 構造であることを compile 時に担保する。
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
    expect(TRACK_FIELD_SELECTORS.titleByUuid("abc-123")).toBe(
      '[name="title_abc-123"]',
    );
  });

  it("songwriterByIndex は first/middle/last 3 分割欄（1-indexed）を返す", () => {
    expect(TRACK_FIELD_SELECTORS.songwriterByIndex(2)).toEqual({
      first: '[name="songwriter_real_name_first2"]',
      middle: '[name="songwriter_real_name_middle2"]',
      last: '[name="songwriter_real_name_last2"]',
    });
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
    expect(() =>
      injectProfile(document, { ...SAMPLE_PROFILE, sub_genre: null }),
    ).toThrow(FieldNotFoundError);
  });

  it("language 欄が存在しなければ FieldNotFoundError", () => {
    // Given: main_genre だけ存在
    mountSelect("genrePrimary", ["Electronic"]);

    // Then
    expect(() =>
      injectProfile(document, { ...SAMPLE_PROFILE, sub_genre: null }),
    ).toThrow(FieldNotFoundError);
  });
});

describe("injectAlbumTitle（アルバム時のみ・シングルモードは skip）", () => {
  it("可視の #albumTitleInput に注入する（アルバム時）", () => {
    // Given
    const el = mountInput({ id: "albumTitleInput", type: "text" });

    // When
    injectAlbumTitle(document, "My Album");

    // Then
    expect(el.value).toBe("My Album");
  });

  it("要素不在ならスキップ（シングルモード・throw しない）", () => {
    // Then: album_title 欄が無くても fail-loud しない
    expect(() => injectAlbumTitle(document, "X")).not.toThrow();
  });
});

describe("injectReleaseDate（未確定 null は注入しない）", () => {
  it("null なら何もしない（要素不在でも throw しない）", () => {
    expect(() => injectReleaseDate(document, null)).not.toThrow();
  });

  it("値ありで可視 #release-date-dp に注入する", () => {
    // Given
    const el = mountInput({ id: "release-date-dp", type: "date" });

    // When
    injectReleaseDate(document, "2026-07-01");

    // Then
    expect(el.value).toBe("2026-07-01");
  });

  it("値ありで要素不在なら FieldNotFoundError", () => {
    expect(() => injectReleaseDate(document, "2026-07-01")).toThrow(
      FieldNotFoundError,
    );
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
    expect(() => injectSongwriter(document, 1, SAMPLE_SONGWRITER)).toThrow(
      FieldNotFoundError,
    );
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

describe("AI_DISCLOSURE_SELECTORS / AI_MODAL_SELECTORS（実 DOM 準拠 #877）", () => {
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

  it("recordingScope は full / partial の radio selector を返す", () => {
    expect(AI_MODAL_SELECTORS.recordingScope("full")).toBe(
      '.distroAiRecordingScope[value="full"]',
    );
    expect(AI_MODAL_SELECTORS.recordingScope("partial")).toBe(
      '.distroAiRecordingScope[value="partial"]',
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
    expect(AI_MODAL_SELECTORS.artistPersonaByUuid("abc", "0")).toBe(
      '[name="ai_artist_persona_abc_0"][value="0"]',
    );
    expect(AI_MODAL_SELECTORS.artistPersonaByUuid("abc", "1")).toBe(
      '[name="ai_artist_persona_abc_0"][value="1"]',
    );
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
    await expect(waitForElement(document, "#never", 20)).rejects.toBeInstanceOf(
      ModalTimeoutError,
    );
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

describe("injectAiDisclosure（#877 modal フロー・async）", () => {
  it("title input (track) が無ければ FieldNotFoundError（uuid 解決不可）", async () => {
    await expect(injectAiDisclosure(document, SAMPLE_AI)).rejects.toBeInstanceOf(
      FieldNotFoundError,
    );
  });

  it("enabled=true で 1st track の「はい」を 1 回だけ click し modal を開閉する", async () => {
    // Given: 2 track（1st の「はい」で modal が開く）
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

  it("modal 内で lyrics / music / recording_scope(full) / persona(AI) / apply-all を設定する", async () => {
    const { getModalRefs } = setupModalForm(["uuid-a"]);

    await injectAiDisclosure(document, SAMPLE_AI);

    const refs = getModalRefs();
    expect(refs).not.toBeNull();
    expect(refs!.lyrics.checked).toBe(true);
    expect(refs!.music.checked).toBe(true);
    expect(refs!.scopeFull.checked).toBe(true);
    expect(refs!.scopePartial.checked).toBe(false);
    // artist_persona=true → AI ペルソナ(value=1)
    expect(refs!.personaAi.checked).toBe(true);
    expect(refs!.personaHuman.checked).toBe(false);
    expect(refs!.applyAll.checked).toBe(true);
    // recording_scope=full なので partial 種別 radio には触れない
    expect(refs!.partialVocals.checked).toBe(false);
    expect(refs!.partialInstruments.checked).toBe(false);
  });

  it("artist_persona=false なら 人間アーティスト(value=0) を選ぶ", async () => {
    const { getModalRefs } = setupModalForm(["uuid-a"]);

    await injectAiDisclosure(document, { ...SAMPLE_AI, artist_persona: false });

    const refs = getModalRefs()!;
    expect(refs.personaHuman.checked).toBe(true);
    expect(refs.personaAi.checked).toBe(false);
  });

  it("recording_scope='partial' + partial_audio_type='vocals' で partial radio を選ぶ", async () => {
    const { getModalRefs } = setupModalForm(["uuid-a"]);

    await injectAiDisclosure(document, {
      ...SAMPLE_AI,
      recording_scope: "partial",
      partial_audio_type: "vocals",
    });

    const refs = getModalRefs()!;
    expect(refs.scopePartial.checked).toBe(true);
    expect(refs.partialVocals.checked).toBe(true);
    expect(refs.partialInstruments.checked).toBe(false);
  });

  it("apply_to_all=false なら apply-all checkbox を入れない", async () => {
    const { getModalRefs } = setupModalForm(["uuid-a"]);

    await injectAiDisclosure(document, { ...SAMPLE_AI, apply_to_all: false });

    expect(getModalRefs()!.applyAll.checked).toBe(false);
  });

  it("partial_audio_type=undefined でも FieldNotFoundError を出さない（loose equality 回帰 #877）", async () => {
    // Given: recording_scope=partial だが partial_audio_type が undefined（旧バグの再現条件）
    const { getModalRefs } = setupModalForm(["uuid-a"]);
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
    // Given: gate「はい」で modal は開くが save ボタンが無い不正 modal
    mountTrackGate("uuid-a");
    const yes = document.querySelector<HTMLInputElement>(
      '[name="ai_gate_uuid-a"][value="1"]',
    )!;
    yes.addEventListener("click", () => {
      setTimeout(() => {
        const modal = document.createElement("div");
        modal.className = "ai-credits-swal-modal";
        const details = document.createElement("div");
        // 必須フィールドは置くが save ボタンを欠く
        withClass(makeCheckbox(details, { name: "ai_lyrics_uuid-a" }), "distroAiLyrics");
        withClass(makeCheckbox(details, { name: "ai_music_uuid-a" }), "distroAiMusic");
        withClass(
          makeRadio(details, { name: "scope", value: "full" }),
          "distroAiRecordingScope",
        );
        withClass(
          makeRadio(details, { name: "ai_artist_persona_uuid-a_0", value: "1" }),
          "distroAiArtistPersona",
        );
        makeCheckbox(details, { id: "ai-apply-all-1" });
        modal.appendChild(details);
        document.body.appendChild(modal);
      }, 0);
    });

    await expect(injectAiDisclosure(document, SAMPLE_AI)).rejects.toBeInstanceOf(
      FieldNotFoundError,
    );
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
