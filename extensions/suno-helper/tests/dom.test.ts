// @vitest-environment jsdom
//
// content script の Suno UI 注入ロジックを純関数化した `shared/dom.ts` の回帰テスト。
// 旧 `content.js` の振る舞いを 1:1 で保持することを保証する:
//   - setNativeValue: prototype の native setter + input/change の bubbling 発火 (React 互換)
//   - resolveFields: 可視 textarea を placeholder/aria-label で判別、fallback は表示順、不在で throw
//   - resolveGenerateButton: 可視 button をラベル正規表現で判別、不在で throw
//   - detectRecaptcha: recaptcha/hcaptcha iframe の存在検知
//
// jsdom はレイアウトを行わず `offsetParent` が常に null になるため、可視判定の対象要素は
// `markVisible` で offsetParent を擬似的に与える (production は content.js と同じ
// `offsetParent !== null` フィルタを維持する前提)。
import { beforeEach, describe, expect, it, vi } from "vitest";

import { detectRecaptcha, resolveFields, resolveGenerateButton, setNativeValue } from "../../shared/dom";

function markVisible(el: HTMLElement): void {
  Object.defineProperty(el, "offsetParent", { configurable: true, get: () => document.body });
}

function addTextarea(attrs: { placeholder?: string; ariaLabel?: string; visible?: boolean }): HTMLTextAreaElement {
  const ta = document.createElement("textarea");
  if (attrs.placeholder !== undefined) ta.placeholder = attrs.placeholder;
  if (attrs.ariaLabel !== undefined) ta.setAttribute("aria-label", attrs.ariaLabel);
  document.body.appendChild(ta);
  if (attrs.visible !== false) markVisible(ta);
  return ta;
}

function addButton(label: string, visible = true): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.textContent = label;
  document.body.appendChild(btn);
  if (visible) markVisible(btn);
  return btn;
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("setNativeValue: React 互換の値注入", () => {
  it("Given textarea When 値を注入する Then value が更新される", () => {
    const ta = document.createElement("textarea");
    setNativeValue(ta, "lofi chill");
    expect(ta.value).toBe("lofi chill");
  });

  it("Given textarea When 値を注入する Then input イベントが bubbling 付きで発火する", () => {
    const ta = document.createElement("textarea");
    document.body.appendChild(ta);
    const onInput = vi.fn();
    document.body.addEventListener("input", onInput); // bubbling していれば body で捕捉できる

    setNativeValue(ta, "x");

    expect(onInput).toHaveBeenCalledTimes(1);
  });

  it("Given textarea When 値を注入する Then change イベントが bubbling 付きで発火する", () => {
    const ta = document.createElement("textarea");
    document.body.appendChild(ta);
    const onChange = vi.fn();
    document.body.addEventListener("change", onChange);

    setNativeValue(ta, "x");

    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("Given input 要素 When 値を注入する Then value が更新される", () => {
    const input = document.createElement("input");
    setNativeValue(input, "abc");
    expect(input.value).toBe("abc");
  });
});

describe("resolveFields: Style / Lyrics の解決", () => {
  it("Given placeholder 付き 2 欄 When 解決する Then placeholder で style/lyrics を判別する", () => {
    const style = addTextarea({ placeholder: "Style description" });
    const lyrics = addTextarea({ placeholder: "Lyrics" });

    const fields = resolveFields();

    expect(fields.style).toBe(style);
    expect(fields.lyrics).toBe(lyrics);
  });

  it("Given 日本語 placeholder When 解決する Then 日本語ラベルでも判別する", () => {
    const style = addTextarea({ placeholder: "スタイル" });
    const lyrics = addTextarea({ placeholder: "歌詞" });

    const fields = resolveFields();

    expect(fields.style).toBe(style);
    expect(fields.lyrics).toBe(lyrics);
  });

  it("Given placeholder 無し aria-label 有り When 解決する Then aria-label で判別する", () => {
    const style = addTextarea({ ariaLabel: "Genre" });
    const lyrics = addTextarea({ ariaLabel: "lyric" });

    const fields = resolveFields();

    expect(fields.style).toBe(style);
    expect(fields.lyrics).toBe(lyrics);
  });

  it("Given ラベル無し 2 欄 When 解決する Then 表示順 fallback で style=1番目 lyrics=2番目", () => {
    const first = addTextarea({});
    const second = addTextarea({});

    const fields = resolveFields();

    expect(fields.style).toBe(first);
    expect(fields.lyrics).toBe(second);
  });

  it("Given style のみ 1 欄 When 解決する Then lyrics は null になる (fail-loud の前提)", () => {
    const only = addTextarea({ placeholder: "Style" });

    const fields = resolveFields();

    expect(fields.style).toBe(only);
    expect(fields.lyrics).toBeNull();
  });

  it("Given 可視 textarea が無い When 解決する Then throw する (silent スキップしない)", () => {
    addTextarea({ placeholder: "Style", visible: false }); // 非表示は対象外

    expect(() => resolveFields()).toThrow();
  });
});

describe("resolveGenerateButton: Generate ボタンの解決", () => {
  it.each(["Create", "Generate", "生成", "  generate  "])(
    "Given ラベル '%s' When 解決する Then 一致するボタンを返す",
    (label) => {
      const btn = addButton(label);
      expect(resolveGenerateButton()).toBe(btn);
    },
  );

  it("Given 無関係なラベルのボタンのみ When 解決する Then throw する", () => {
    addButton("Submit");
    addButton("キャンセル");

    expect(() => resolveGenerateButton()).toThrow();
  });

  it("Given Generate ボタンが非表示 When 解決する Then throw する", () => {
    addButton("Generate", false);

    expect(() => resolveGenerateButton()).toThrow();
  });
});

describe("detectRecaptcha: チャレンジ検知", () => {
  it("Given recaptcha iframe (src) When 検知する Then true", () => {
    document.body.innerHTML = '<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>';
    expect(detectRecaptcha()).toBe(true);
  });

  it("Given recaptcha iframe (title) When 検知する Then true", () => {
    document.body.innerHTML = '<iframe title="reCAPTCHA challenge"></iframe>';
    expect(detectRecaptcha()).toBe(true);
  });

  it("Given hcaptcha iframe When 検知する Then true", () => {
    document.body.innerHTML = '<iframe src="https://newassets.hcaptcha.com/captcha/v1"></iframe>';
    expect(detectRecaptcha()).toBe(true);
  });

  it("Given チャレンジ無し When 検知する Then false", () => {
    document.body.innerHTML = '<iframe src="https://suno.com/embed"></iframe>';
    expect(detectRecaptcha()).toBe(false);
  });
});
