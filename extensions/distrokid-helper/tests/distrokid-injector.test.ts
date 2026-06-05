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
  PROFILE_SELECTORS,
  ALBUM_SELECTORS,
  RELEASE_DATE_SELECTOR,
  FILE_SELECTORS,
  TRACK_FIELD_SELECTORS,
  AI_DISCLOSURE_SELECTORS,
  FieldNotFoundError,
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

// 実 DOM 検証（#866）に基づく track 単位の AI 開示構造を mount する。
// title input (uuid 解決基点) + ai_gate radio + ai_lyrics/ai_music checkbox +
// ai_partial_audio_type radio（vocals/instruments）を fieldset に並べる。
function mountAiCreditsForTrack(uuid: string): {
  fieldset: HTMLFieldSetElement;
  title: HTMLInputElement;
  gateNo: HTMLInputElement;
  gateYes: HTMLInputElement;
  lyrics: HTMLInputElement;
  composition: HTMLInputElement;
  partialVocals: HTMLInputElement;
  partialInstruments: HTMLInputElement;
} {
  const fieldset = document.createElement("fieldset");
  const title = document.createElement("input");
  title.name = `title_${uuid}`;
  fieldset.appendChild(title);
  const gateNo = makeRadio(fieldset, { name: `ai_gate_${uuid}`, value: "0" });
  gateNo.checked = true;
  const gateYes = makeRadio(fieldset, { name: `ai_gate_${uuid}`, value: "1" });
  const lyrics = makeCheckbox(fieldset, { name: `ai_lyrics_${uuid}` });
  const composition = makeCheckbox(fieldset, { name: `ai_music_${uuid}` });
  const partialVocals = makeRadio(fieldset, {
    name: `ai_partial_audio_type_${uuid}`,
    value: "vocals",
  });
  const partialInstruments = makeRadio(fieldset, {
    name: `ai_partial_audio_type_${uuid}`,
    value: "instruments",
  });
  document.body.appendChild(fieldset);
  return {
    fieldset,
    title,
    gateNo,
    gateYes,
    lyrics,
    composition,
    partialVocals,
    partialInstruments,
  };
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
  composition: true,
  partial_audio_type: null,
};
const SAMPLE_PROFILE: DistrokidProfile = {
  language: "ja",
  main_genre: "Electronic",
  sub_genre: "House",
  songwriter: SAMPLE_SONGWRITER,
  ai_disclosure: SAMPLE_AI,
};

describe("新 schema 型契約（lib/types）", () => {
  it("DistrokidProfile は nested songwriter + ai_disclosure を持つ", () => {
    // Then: 旧フラットフィールドは型から撤廃され、nested 構造になっている
    expect(SAMPLE_PROFILE.songwriter?.first).toBe("Jane");
    expect(SAMPLE_PROFILE.songwriter?.middle).toBeNull();
    expect(SAMPLE_PROFILE.ai_disclosure.partial_audio_type).toBeNull();
    expect("artist_name" in SAMPLE_PROFILE).toBe(false);
    // #866 で実 DOM に存在しないフィールドは型から撤廃
    expect("full_audio" in SAMPLE_PROFILE.ai_disclosure).toBe(false);
    expect("apply_to_all" in SAMPLE_PROFILE.ai_disclosure).toBe(false);
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

describe("AI_DISCLOSURE_SELECTORS（uuid-driven 関数群・実 DOM 準拠 #866）", () => {
  it("gateByUuid は ai_gate_<uuid> の yes / no radio selector を返す", () => {
    expect(AI_DISCLOSURE_SELECTORS.gateByUuid("abc")).toEqual({
      no: '[name="ai_gate_abc"][value="0"]',
      yes: '[name="ai_gate_abc"][value="1"]',
    });
  });

  it("lyricsByUuid / compositionByUuid は ai_lyrics_<uuid> / ai_music_<uuid> selector", () => {
    expect(AI_DISCLOSURE_SELECTORS.lyricsByUuid("abc")).toBe('[name="ai_lyrics_abc"]');
    expect(AI_DISCLOSURE_SELECTORS.compositionByUuid("abc")).toBe('[name="ai_music_abc"]');
  });

  it("partialAudioTypeByUuid は vocals / instruments radio selector", () => {
    expect(AI_DISCLOSURE_SELECTORS.partialAudioTypeByUuid("abc", "vocals")).toBe(
      '[name="ai_partial_audio_type_abc"][value="vocals"]',
    );
    expect(AI_DISCLOSURE_SELECTORS.partialAudioTypeByUuid("abc", "instruments")).toBe(
      '[name="ai_partial_audio_type_abc"][value="instruments"]',
    );
  });
});

describe("injectAiDisclosure（全 track へ ai 設定を一括適用・sync）", () => {
  it("title input (track) が無ければ FieldNotFoundError（uuid 解決不可）", () => {
    expect(() => injectAiDisclosure(document, SAMPLE_AI)).toThrow(FieldNotFoundError);
  });

  it("enabled=true で全 track の「はい」radio が click され lyrics/composition が確定する", () => {
    // Given: 2 track のモック (どちらも初期は「いいえ」 checked)
    const t1 = mountAiCreditsForTrack("uuid-a");
    const t2 = mountAiCreditsForTrack("uuid-b");

    // When
    injectAiDisclosure(document, {
      enabled: true,
      lyrics: true,
      composition: true,
      partial_audio_type: null,
    });

    // Then: 全 track で yes radio が確定、lyrics/composition も checked
    expect(t1.gateYes.checked).toBe(true);
    expect(t2.gateYes.checked).toBe(true);
    expect(t1.lyrics.checked).toBe(true);
    expect(t1.composition.checked).toBe(true);
    expect(t2.lyrics.checked).toBe(true);
    expect(t2.composition.checked).toBe(true);
    // partial_audio_type=null なので partial 系 radio には触れない
    expect(t1.partialVocals.checked).toBe(false);
    expect(t1.partialInstruments.checked).toBe(false);
  });

  it("partial_audio_type='vocals' で対応 radio が click される（全 track）", () => {
    const t1 = mountAiCreditsForTrack("uuid-a");
    const t2 = mountAiCreditsForTrack("uuid-b");

    injectAiDisclosure(document, {
      enabled: true,
      lyrics: true,
      composition: true,
      partial_audio_type: "vocals",
    });

    expect(t1.partialVocals.checked).toBe(true);
    expect(t1.partialInstruments.checked).toBe(false);
    expect(t2.partialVocals.checked).toBe(true);
  });

  it("partial_audio_type='instruments' でも同様に対応 radio が click される", () => {
    const t1 = mountAiCreditsForTrack("uuid-a");

    injectAiDisclosure(document, { ...SAMPLE_AI, partial_audio_type: "instruments" });

    expect(t1.partialInstruments.checked).toBe(true);
    expect(t1.partialVocals.checked).toBe(false);
  });

  it("enabled=false でも全 track の「いいえ」radio を明示確定する（人手 default に頼らない）", () => {
    // Given: 初期は yes が checked（過去操作の影響を仮想）
    const t1 = mountAiCreditsForTrack("uuid-a");
    t1.gateNo.checked = false;
    t1.gateYes.checked = true;
    let noClicks = 0;
    t1.gateNo.addEventListener("click", () => {
      noClicks += 1;
    });

    // When
    injectAiDisclosure(document, { ...SAMPLE_AI, enabled: false });

    // Then: 「いいえ」が click で確定、lyrics/composition は触れない
    expect(noClicks).toBe(1);
    expect(t1.gateNo.checked).toBe(true);
    expect(t1.lyrics.checked).toBe(false);
    expect(t1.composition.checked).toBe(false);
  });

  it("ai_gate radio が無ければ FieldNotFoundError", () => {
    // Given: title だけあって ai_gate radio が無い
    const title = document.createElement("input");
    title.name = "title_uuid-a";
    document.body.appendChild(title);

    expect(() => injectAiDisclosure(document, SAMPLE_AI)).toThrow(FieldNotFoundError);
  });

  it("ai_lyrics checkbox が無ければ FieldNotFoundError", () => {
    // Given: title + ai_gate はあるが ai_lyrics 不在
    const title = document.createElement("input");
    title.name = "title_uuid-a";
    document.body.appendChild(title);
    const gateYes = makeRadio(document.body, { name: "ai_gate_uuid-a", value: "1" });
    const gateNo = makeRadio(document.body, { name: "ai_gate_uuid-a", value: "0" });
    gateNo.checked = true;

    expect(() => injectAiDisclosure(document, SAMPLE_AI)).toThrow(FieldNotFoundError);
    expect(gateYes.checked).toBe(true); // 順序: gate を先に確定してから lyrics で fail-loud
  });

  it("partial_audio_type が non-null で対応 radio 不在なら FieldNotFoundError", () => {
    // Given: lyrics/composition checkbox はあるが partial_audio_type radio が無い
    const title = document.createElement("input");
    title.name = "title_uuid-a";
    document.body.appendChild(title);
    makeRadio(document.body, { name: "ai_gate_uuid-a", value: "1" });
    const gateNo = makeRadio(document.body, { name: "ai_gate_uuid-a", value: "0" });
    gateNo.checked = true;
    makeCheckbox(document.body, { name: "ai_lyrics_uuid-a" });
    makeCheckbox(document.body, { name: "ai_music_uuid-a" });

    expect(() =>
      injectAiDisclosure(document, { ...SAMPLE_AI, partial_audio_type: "vocals" }),
    ).toThrow(FieldNotFoundError);
  });

  it("setChecked: 既に目標状態なら click せず、不一致のみ click する", () => {
    // Given: lyrics は既に checked（config も true）、composition は false（config は true）
    const t1 = mountAiCreditsForTrack("uuid-a");
    t1.lyrics.checked = true;
    let lyricsClicks = 0;
    let compositionClicks = 0;
    t1.lyrics.addEventListener("click", () => {
      lyricsClicks += 1;
    });
    t1.composition.addEventListener("click", () => {
      compositionClicks += 1;
    });

    // When
    injectAiDisclosure(document, {
      enabled: true,
      lyrics: true,
      composition: true,
      partial_audio_type: null,
    });

    // Then: 一致は無操作、不一致のみ click で切替
    expect(lyricsClicks).toBe(0);
    expect(t1.lyrics.checked).toBe(true);
    expect(compositionClicks).toBe(1);
    expect(t1.composition.checked).toBe(true);
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
