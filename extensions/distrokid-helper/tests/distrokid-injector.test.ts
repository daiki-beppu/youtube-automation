// @vitest-environment jsdom
//
// `lib/distrokid-injector.ts` のテキスト注入ロジックの契約テスト。
// ファイル注入（DataTransfer 経由）は jsdom 非対応のため Playwright (tests/e2e) が担う。
//
// 設計契約（draft が実装する前提）:
//   - setNativeValue(el, value): prototype の native value setter で値をセットし
//     "input" と "change" を bubbles:true で発火（React 互換）
//   - injectProfile(root, profile): 6 個の静的プロファイルを PROFILE_SELECTORS で解決し注入。
//     セレクタが 1 つでも未検出なら FieldNotFoundError を throw（fail-loud、silent skip 禁止）
//   - injectRelease(root, release): album_title は必須注入、release_date は null ならスキップ
//   - injectAll(root, payload): profile + release のテキストを注入（ファイルは別経路）
//   - 送信系ボタン（「続ける」）は一切操作しない

import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  setNativeValue,
  injectProfile,
  injectRelease,
  injectAll,
  PROFILE_SELECTORS,
  RELEASE_SELECTORS,
  FieldNotFoundError,
} from "../lib/distrokid-injector";
import type { DistrokidProfile, ReleaseData, ReleasePayload } from "../lib/types";

// `[name="x"]` / `input[name="x"]` 形式のセレクタから name 属性値を取り出す。
// 想定外のセレクタ形式なら fail-loud（draft がセレクタ方式を変えたらここで気付ける）。
function nameFromSelector(selector: string): string {
  const match = selector.match(/\[name="([^"]+)"\]/);
  if (!match) {
    throw new Error(
      `テストヘルパは [name="..."] 形式のセレクタを前提とします。実際: ${selector}`,
    );
  }
  return match[1];
}

// 与えられたセレクタ群に一致する <input> を持つ <form> を構築する。
function buildForm(selectors: Record<string, string>): HTMLFormElement {
  const form = document.createElement("form");
  for (const selector of Object.values(selectors)) {
    const input = document.createElement("input");
    input.setAttribute("name", nameFromSelector(selector));
    form.appendChild(input);
  }
  return form;
}

const SAMPLE_PROFILE: DistrokidProfile = {
  artist_name: "City Nights",
  language: "English",
  main_genre: "Electronic",
  songwriter: "Jane Doe",
  apple_music_credit: "Jane Doe",
  track_type: "Instrumental",
};

beforeEach(() => {
  document.body.innerHTML = "";
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

describe("injectProfile", () => {
  it("6 個の静的プロファイルを全フィールドに注入する", () => {
    // Given
    const form = buildForm(PROFILE_SELECTORS);
    document.body.appendChild(form);

    // When
    injectProfile(form, SAMPLE_PROFILE);

    // Then: PROFILE_SELECTORS のキーごとに対応値が入っている
    for (const key of Object.keys(PROFILE_SELECTORS) as (keyof DistrokidProfile)[]) {
      const el = form.querySelector<HTMLInputElement>(PROFILE_SELECTORS[key]);
      expect(el, `${key} の入力要素が見つからない`).not.toBeNull();
      expect(el!.value).toBe(SAMPLE_PROFILE[key]);
    }
  });

  it("フィールドが 1 つでも欠けていれば FieldNotFoundError を throw する（fail-loud）", () => {
    // Given: artist_name の入力要素だけ取り除く
    const form = buildForm(PROFILE_SELECTORS);
    const artist = form.querySelector(PROFILE_SELECTORS.artist_name);
    artist?.remove();
    document.body.appendChild(form);

    // When / Then: silent skip せず throw
    expect(() => injectProfile(form, SAMPLE_PROFILE)).toThrow(FieldNotFoundError);
  });
});

describe("injectRelease", () => {
  const baseRelease: ReleaseData = {
    album_title: "Summer Vibes",
    tracks: [],
    cover: null,
    release_date: "2026-07-01",
  };

  it("album_title と release_date を注入する", () => {
    // Given
    const form = buildForm(RELEASE_SELECTORS);
    document.body.appendChild(form);

    // When
    injectRelease(form, baseRelease);

    // Then
    expect(
      form.querySelector<HTMLInputElement>(RELEASE_SELECTORS.album_title)!.value,
    ).toBe("Summer Vibes");
    expect(
      form.querySelector<HTMLInputElement>(RELEASE_SELECTORS.release_date)!.value,
    ).toBe("2026-07-01");
  });

  it("release_date が null ならスキップし、欄が無くても throw しない", () => {
    // Given: release_date の入力欄を持たない form（null はデータ仕様上の正常値）
    const form = document.createElement("form");
    const album = document.createElement("input");
    album.setAttribute("name", nameFromSelector(RELEASE_SELECTORS.album_title));
    form.appendChild(album);
    document.body.appendChild(form);
    const release: ReleaseData = { ...baseRelease, release_date: null };

    // When / Then: スキップされ例外は発生しない
    expect(() => injectRelease(form, release)).not.toThrow();
    expect(album.value).toBe("Summer Vibes");
  });

  it("album_title の入力欄が無ければ FieldNotFoundError を throw する（fail-loud）", () => {
    // Given: release_date 欄のみで album_title 欄が無い
    const form = document.createElement("form");
    const date = document.createElement("input");
    date.setAttribute("name", nameFromSelector(RELEASE_SELECTORS.release_date));
    form.appendChild(date);
    document.body.appendChild(form);

    // When / Then
    expect(() => injectRelease(form, baseRelease)).toThrow(FieldNotFoundError);
  });
});

describe("injectAll（envelope 取り違え防止）", () => {
  it("profile は payload.profile から、album/date は payload.release から読む", () => {
    // Given: profile と release で別々の値を持つ完全ペイロード
    const form = document.createElement("form");
    for (const selector of [
      ...Object.values(PROFILE_SELECTORS),
      ...Object.values(RELEASE_SELECTORS),
    ]) {
      const input = document.createElement("input");
      input.setAttribute("name", nameFromSelector(selector));
      form.appendChild(input);
    }
    document.body.appendChild(form);

    const payload: ReleasePayload = {
      profile: SAMPLE_PROFILE,
      release: {
        album_title: "Summer Vibes",
        tracks: [],
        cover: null,
        release_date: "2026-07-01",
      },
    };

    // When
    injectAll(form, payload);

    // Then: artist は profile 由来、album は release 由来（入れ子を取り違えていない）
    expect(
      form.querySelector<HTMLInputElement>(PROFILE_SELECTORS.artist_name)!.value,
    ).toBe("City Nights");
    expect(
      form.querySelector<HTMLInputElement>(RELEASE_SELECTORS.album_title)!.value,
    ).toBe("Summer Vibes");
    // album 欄に profile の値が混入していないこと
    expect(
      form.querySelector<HTMLInputElement>(RELEASE_SELECTORS.album_title)!.value,
    ).not.toBe("City Nights");
  });

  it("送信系ボタン（「続ける」）を一切クリックしない", () => {
    // Given: 注入対象フォーム + クリック監視付きの「続ける」ボタン
    const form = document.createElement("form");
    for (const selector of [
      ...Object.values(PROFILE_SELECTORS),
      ...Object.values(RELEASE_SELECTORS),
    ]) {
      const input = document.createElement("input");
      input.setAttribute("name", nameFromSelector(selector));
      form.appendChild(input);
    }
    const continueBtn = document.createElement("button");
    continueBtn.type = "button";
    continueBtn.textContent = "続ける";
    const clickSpy = vi.fn();
    continueBtn.addEventListener("click", clickSpy);
    form.appendChild(continueBtn);
    document.body.appendChild(form);

    const payload: ReleasePayload = {
      profile: SAMPLE_PROFILE,
      release: {
        album_title: "Summer Vibes",
        tracks: [],
        cover: null,
        release_date: "2026-07-01",
      },
    };

    // When
    injectAll(form, payload);

    // Then: 送信ボタンは押されない（規約遵守・要件 #7）
    expect(clickSpy).not.toHaveBeenCalled();
  });
});
