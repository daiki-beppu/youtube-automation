// @vitest-environment jsdom
//
// content script の Suno UI 注入ロジックを純関数化した `shared/dom.ts` の回帰テスト。
// 旧 `content.js` の振る舞いを保持しつつ、#807 で判明した日本語 UI 破損を修正した仕様を担保する:
//   - setNativeValue: prototype の native setter + input/change の bubbling 発火 (React 互換)
//   - resolveFields: lyrics は `data-testid="lyrics-textarea"` で最優先識別 (UI 言語非依存)、
//                    style は lyrics 以外の strict visible textarea、解決不能なら throw (fail-loud)
//   - resolveGenerateButton: 可視 button をラベル正規表現で判別、不在で throw
//   - detectRecaptcha: recaptcha/hcaptcha iframe の存在検知
//
// jsdom はレイアウトを行わず `getBoundingClientRect()` が常に全 0 を返すため、可視判定の
// 対象要素は `setRect` で bbox を擬似的に与える (production の strict isVisible は
// `getBoundingClientRect` の width/height と親要素の display/visibility/opacity を見る前提)。
import { beforeEach, describe, expect, it, vi } from "vitest";

import { detectRecaptcha, resolveFields, resolveGenerateButton, setNativeValue } from "../../shared/dom";

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

// strict isVisible は getBoundingClientRect を見るため、jsdom では bbox を明示 stub する。
function setRect(el: HTMLElement, rect: DOMRect): void {
  el.getBoundingClientRect = () => rect;
}

function addTextarea(
  opts: { testId?: string; placeholder?: string; ariaLabel?: string; visible?: boolean } = {},
): HTMLTextAreaElement {
  const ta = document.createElement("textarea");
  if (opts.testId !== undefined) ta.setAttribute("data-testid", opts.testId);
  if (opts.placeholder !== undefined) ta.placeholder = opts.placeholder;
  if (opts.ariaLabel !== undefined) ta.setAttribute("aria-label", opts.ariaLabel);
  document.body.appendChild(ta);
  setRect(ta, opts.visible === false ? ZERO_RECT : VISIBLE_RECT);
  return ta;
}

function addButton(label: string, visible = true): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.textContent = label;
  document.body.appendChild(btn);
  setRect(btn, visible ? VISIBLE_RECT : ZERO_RECT);
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

describe("resolveFields: data-testid ベースの Style / Lyrics 解決 (#807)", () => {
  it("Given lyrics-textarea と別の visible textarea When 解決する Then data-testid で lyrics を、残りを style とする", () => {
    const lyrics = addTextarea({ testId: "lyrics-textarea", placeholder: "What do you want your lyrics to be about?" });
    const style = addTextarea({ placeholder: "Style description" });

    const fields = resolveFields();

    expect(fields.lyrics).toBe(lyrics);
    expect(fields.style).toBe(style);
  });

  it("Given lyrics-textarea が DOM 上で style より先 When 解決する Then 表示順ではなく data-testid で識別する", () => {
    const lyrics = addTextarea({ testId: "lyrics-textarea" });
    const style = addTextarea({ placeholder: "Style description" });

    const fields = resolveFields();

    // 旧実装は areas[0] を style にしていた。順序 fallback の復活を禁ずる回帰ガード。
    expect(fields.lyrics).toBe(lyrics);
    expect(fields.style).toBe(style);
  });

  it("Given 日本語 UI (style placeholder がジャンル語彙) When 解決する Then placeholder 非依存で正しく振り分ける", () => {
    // #807 の再現入力: 日本語ロケールでは style placeholder が「ジャンル例の語彙」になり
    // 旧 stylePlaceholder regex に一致しない。data-testid 識別ならこの入力でも壊れない。
    const lyrics = addTextarea({
      testId: "lyrics-textarea",
      placeholder: "What do you want your lyrics to be about? Suno will write new lyrics every generation.",
    });
    const style = addTextarea({ placeholder: "地下の罠, コントラルト, リズミカルなベース, ソフトパンク, メリスマ" });

    const fields = resolveFields();

    expect(fields.lyrics).toBe(lyrics);
    expect(fields.style).toBe(style);
  });

  it("Given lyrics-textarea しか可視でない When 解決する Then Style 解決不能で throw する (silent な上書きを禁ずる)", () => {
    addTextarea({ testId: "lyrics-textarea" });

    expect(() => resolveFields()).toThrow();
  });

  it("Given data-testid 無しの visible textarea 1 枚 (instrumental) When 解決する Then style に解決し lyrics は null", () => {
    const only = addTextarea({ placeholder: "地下の罠, コントラルト, リズミカルなベース" });

    const fields = resolveFields();

    expect(fields.style).toBe(only);
    expect(fields.lyrics).toBeNull();
  });

  it("Given 可視 textarea が無い When 解決する Then throw する (silent スキップしない)", () => {
    addTextarea({ testId: "lyrics-textarea", visible: false });
    addTextarea({ placeholder: "Style description", visible: false });

    expect(() => resolveFields()).toThrow();
  });

  it("Given bbox 0 の textarea (Simple Mode) が混在 When 解決する Then strict isVisible が除外する", () => {
    // bbox 0 の lyrics-textarea は data-testid を持っていても可視集合から除外され、
    // 可視は style 1 枚のみ → lyrics は null になる (hidden な Simple Mode 要素を拾わない)。
    addTextarea({ testId: "lyrics-textarea", visible: false });
    const style = addTextarea({ placeholder: "Style description" });

    const fields = resolveFields();

    expect(fields.style).toBe(style);
    expect(fields.lyrics).toBeNull();
  });

  it("Given 自身が visibility:hidden の lyrics-textarea When 解決する Then strict isVisible が除外する", () => {
    const hiddenLyrics = addTextarea({ testId: "lyrics-textarea" });
    hiddenLyrics.style.visibility = "hidden";
    const style = addTextarea({ placeholder: "Style description" });

    const fields = resolveFields();

    expect(fields.style).toBe(style);
    expect(fields.lyrics).toBeNull();
  });

  it("Given 自身が opacity:0 の lyrics-textarea When 解決する Then strict isVisible が除外する", () => {
    const hiddenLyrics = addTextarea({ testId: "lyrics-textarea" });
    hiddenLyrics.style.opacity = "0";
    const style = addTextarea({ placeholder: "Style description" });

    const fields = resolveFields();

    expect(fields.style).toBe(style);
    expect(fields.lyrics).toBeNull();
  });

  it("Given 親が display:none の lyrics-textarea When 解決する Then 親要素 walk で除外する", () => {
    const wrapper = document.createElement("div");
    wrapper.style.display = "none";
    document.body.appendChild(wrapper);
    const hiddenLyrics = document.createElement("textarea");
    hiddenLyrics.setAttribute("data-testid", "lyrics-textarea");
    wrapper.appendChild(hiddenLyrics);
    setRect(hiddenLyrics, VISIBLE_RECT); // bbox は非 0。除外理由は親の display:none のみに限定する。

    const style = addTextarea({ placeholder: "Style description" });

    const fields = resolveFields();

    expect(fields.style).toBe(style);
    expect(fields.lyrics).toBeNull();
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

  it("Given Generate ボタンが非表示 (bbox 0) When 解決する Then throw する", () => {
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
