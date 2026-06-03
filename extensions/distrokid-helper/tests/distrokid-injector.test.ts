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

import { describe, it, expect, beforeEach, vi } from "vitest";
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
  AI_MODAL_TIMEOUT_MS,
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

// 実 DOM 検証サマリの AI 開示モーダル（#ai-modal）をミラーする。
// checkbox の DOM order は [歌詞, 作曲, 音声すべて, 音声の一部, apply-all] の 5 個
// （「音声すべて/音声の一部」は name 属性なし → injector は order[2]/[3] で識別する）。
function buildAiModal(parent: ParentNode): {
  modal: HTMLDivElement;
  lyrics: HTMLInputElement;
  music: HTMLInputElement;
  fullAudio: HTMLInputElement;
  partialAudio: HTMLInputElement;
  applyAll: HTMLInputElement;
  save: HTMLButtonElement;
} {
  const modal = document.createElement("div");
  modal.id = "ai-modal";
  const lyrics = makeCheckbox(modal, { name: "ai_lyrics_1" });
  const music = makeCheckbox(modal, { name: "ai_music_1" });
  const fullAudio = makeCheckbox(modal, {});
  const partialAudio = makeCheckbox(modal, {});
  const applyAll = makeCheckbox(modal, { id: "ai-apply-all-1" });
  const save = document.createElement("button");
  save.id = "ai-save";
  save.textContent = "保存する";
  modal.appendChild(save);
  (parent as Node).appendChild(modal);
  return { modal, lyrics, music, fullAudio, partialAudio, applyAll, save };
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
  full_audio: true,
  partial_audio: false,
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
  it("DistrokidProfile は nested songwriter + ai_disclosure を持つ", () => {
    // Then: 旧フラットフィールドは型から撤廃され、nested 構造になっている
    expect(SAMPLE_PROFILE.songwriter?.first).toBe("Jane");
    expect(SAMPLE_PROFILE.songwriter?.middle).toBeNull();
    expect(SAMPLE_PROFILE.ai_disclosure.partial_audio).toBe(false);
    expect("artist_name" in SAMPLE_PROFILE).toBe(false);
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

describe("injectAiDisclosure（はい→モーダル待機→checkbox→保存）", () => {
  it("enabled=false は何もしない（要素不在でも throw しない）", async () => {
    await expect(
      injectAiDisclosure(document, { ...SAMPLE_AI, enabled: false }),
    ).resolves.toBeUndefined();
  });

  it("はい radio が無ければ FieldNotFoundError", async () => {
    const err = await injectAiDisclosure(document, { ...SAMPLE_AI }).catch(
      (e) => e,
    );
    expect(err).toBeInstanceOf(FieldNotFoundError);
  });

  it("はい click → config 通りに checkbox 設定 → 保存 click（モーダル既存）", async () => {
    // Given: はい radio とモーダルが既に存在し、全 checkbox は unchecked
    const yes = mountInput({ id: "ai-yes", type: "radio" });
    let yesClicks = 0;
    yes.addEventListener("click", () => {
      yesClicks += 1;
    });
    const refs = buildAiModal(document.body);
    let saveClicks = 0;
    refs.save.addEventListener("click", () => {
      saveClicks += 1;
    });

    // When
    await injectAiDisclosure(document, {
      enabled: true,
      lyrics: true,
      composition: true,
      full_audio: true,
      partial_audio: false,
      apply_to_all: true,
    });

    // Then: はいが押され、config に従い checkbox が設定され、保存が押される
    expect(yesClicks).toBe(1);
    expect(refs.lyrics.checked).toBe(true);
    expect(refs.music.checked).toBe(true);
    // 「音声すべて/音声の一部」は DOM order[2]/[3] で識別される（finding 2 の前提を固定）
    expect(refs.fullAudio.checked).toBe(true);
    expect(refs.partialAudio.checked).toBe(false);
    expect(refs.applyAll.checked).toBe(true);
    expect(saveClicks).toBe(1);
  });

  it("setCheckbox: 既に目標状態なら click せず、不一致なら click する", async () => {
    // Given: lyrics は既に checked（config も true）、partialAudio は checked（config は false）
    mountInput({ id: "ai-yes", type: "radio" });
    const refs = buildAiModal(document.body);
    refs.lyrics.checked = true;
    refs.partialAudio.checked = true;
    let lyricsClicks = 0;
    let partialClicks = 0;
    refs.lyrics.addEventListener("click", () => {
      lyricsClicks += 1;
    });
    refs.partialAudio.addEventListener("click", () => {
      partialClicks += 1;
    });

    // When
    await injectAiDisclosure(document, {
      enabled: true,
      lyrics: true,
      composition: true,
      full_audio: true,
      partial_audio: false,
      apply_to_all: true,
    });

    // Then: 一致は無操作、不一致のみ click で切替
    expect(lyricsClicks).toBe(0);
    expect(refs.lyrics.checked).toBe(true);
    expect(partialClicks).toBe(1);
    expect(refs.partialAudio.checked).toBe(false);
  });

  it("はい click 後にモーダルが非同期挿入されても MutationObserver で待機して注入する", async () => {
    // Given: はい click でモーダルを microtask 挿入（同期挿入だと observer 経路を通らないため）
    const yes = mountInput({ id: "ai-yes", type: "radio" });
    let refs: ReturnType<typeof buildAiModal> | null = null;
    yes.addEventListener("click", () => {
      Promise.resolve().then(() => {
        refs = buildAiModal(document.body);
      });
    });

    // When
    await injectAiDisclosure(document, { ...SAMPLE_AI });

    // Then: 後挿入されたモーダルにも checkbox が注入される
    expect(refs).not.toBeNull();
    expect(refs!.applyAll.checked).toBe(true);
    expect(refs!.lyrics.checked).toBe(true);
  });

  it("モーダルが現れなければ timeout で FieldNotFoundError（fail-loud）", async () => {
    // Given: はいはあるがモーダルは出ない
    mountInput({ id: "ai-yes", type: "radio" });
    vi.useFakeTimers();

    // When: timeout まで進める
    const pending = injectAiDisclosure(document, { ...SAMPLE_AI }).catch(
      (e) => e,
    );
    await vi.advanceTimersByTimeAsync(AI_MODAL_TIMEOUT_MS + 10);
    const err = await pending;

    // Then
    expect(err).toBeInstanceOf(FieldNotFoundError);
    vi.useRealTimers();
  });

  it("音声 AI checkbox（DOM order 3・4 番目）が無ければ FieldNotFoundError", async () => {
    // Given: checkbox が 3 個しか無い（fullAudio/partialAudio が欠落）モーダル
    mountInput({ id: "ai-yes", type: "radio" });
    const modal = document.createElement("div");
    modal.id = "ai-modal";
    makeCheckbox(modal, { name: "ai_lyrics_1" });
    makeCheckbox(modal, { name: "ai_music_1" });
    makeCheckbox(modal, { id: "ai-apply-all-1" });
    const save = document.createElement("button");
    save.id = "ai-save";
    modal.appendChild(save);
    document.body.appendChild(modal);

    // When
    const err = await injectAiDisclosure(document, { ...SAMPLE_AI }).catch(
      (e) => e,
    );

    // Then
    expect(err).toBeInstanceOf(FieldNotFoundError);
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
