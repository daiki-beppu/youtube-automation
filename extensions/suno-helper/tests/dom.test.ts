// @vitest-environment jsdom
//
// content script の Suno UI 注入ロジックを純関数化した `shared/dom.ts` の回帰テスト。
// 旧 `content.js` の振る舞いを保持しつつ、#807 で判明した日本語 UI 破損および #810 で判明した
// hCaptcha プリロード iframe 誤検知を修正した仕様を担保する:
//   - setNativeValue: prototype の native setter + input/change の bubbling 発火 (React 互換)
//   - resolveFields: lyrics は `data-testid="lyrics-textarea"` で最優先識別 (UI 言語非依存)、
//                    style は lyrics 以外の strict visible textarea、解決不能なら throw (fail-loud)
//   - resolveGenerateButton: 可視 button をラベル正規表現で判別、不在で throw
//   - detectRecaptcha: 可視な recaptcha/hcaptcha iframe のみ検知 (#810、#807 と同じ strict isVisible を共有)
//
// jsdom はレイアウトを行わず `getBoundingClientRect()` が常に 0×0 を返すため、可視判定の対象要素は
// `setRect` (textarea/button) または `markBbox` (iframe, _helpers.ts) で bbox を擬似的に与える。
// production の strict isVisible は bbox 非ゼロ + 親 walk で `display:none`/`visibility:hidden`/
// `opacity:0` を排除する前提。display/visibility/opacity はインライン style で表現する
// (jsdom の getComputedStyle はインライン style を反映する)。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  abortableSleep,
  detectRecaptcha,
  isQueueLimitErrorVisible,
  QUEUE_LIMIT_ERROR_SELECTOR,
  resolveAdvancedFields,
  resolveFields,
  resolveGenerateButton,
  setNativeValue,
  setSliderValue,
} from "../../shared/dom";
import { addCaptchaIframe, addQueueErrorDialog, markBbox } from "./_helpers";

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

// Song Title 欄は <input>（style/lyrics の <textarea> とは別要素）。#844 で追加。
function addInput(opts: { placeholder?: string; visible?: boolean } = {}): HTMLInputElement {
  const input = document.createElement("input");
  input.type = "text";
  if (opts.placeholder !== undefined) input.placeholder = opts.placeholder;
  document.body.appendChild(input);
  setRect(input, opts.visible === false ? ZERO_RECT : VISIBLE_RECT);
  return input;
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

describe("resolveFields: Song Title 欄の解決 (#844, fail-soft)", () => {
  it("Given placeholder 'Song Title (Optional)' の visible input When 解決する Then title に解決する", () => {
    // style/lyrics の解決を成立させるための最小構成（title 解決の前提）。
    addTextarea({ testId: "lyrics-textarea" });
    addTextarea({ placeholder: "Style description" });
    const title = addInput({ placeholder: "Song Title (Optional)" });

    const fields = resolveFields();

    expect(fields.title).toBe(title);
  });

  it.each(["Song Title (Optional)", "song title", "SONG TITLE", "Enter Song Title here"])(
    "Given placeholder '%s' When 解決する Then 弱い case-insensitive substring match で title に解決する",
    (placeholder) => {
      // (Optional) を含めない弱マッチ + i フラグ（order.md: Suno の表記変更耐性）。
      addTextarea({ testId: "lyrics-textarea" });
      addTextarea({ placeholder: "Style description" });
      const title = addInput({ placeholder });

      const fields = resolveFields();

      expect(fields.title).toBe(title);
    },
  );

  it("Given title input が無い When 解決する Then title は undefined で throw しない (fail-soft)", () => {
    // style/lyrics の fail-loud とは非対称: title 不在は throw せず undefined を返す。
    addTextarea({ testId: "lyrics-textarea" });
    addTextarea({ placeholder: "Style description" });

    const fields = resolveFields();

    expect(fields.title).toBeUndefined();
  });

  it("Given bbox 0 の title input When 解決する Then strict isVisible が除外し undefined", () => {
    addTextarea({ testId: "lyrics-textarea" });
    addTextarea({ placeholder: "Style description" });
    addInput({ placeholder: "Song Title (Optional)", visible: false });

    const fields = resolveFields();

    expect(fields.title).toBeUndefined();
  });

  it("Given visibility:hidden の title input When 解決する Then strict isVisible が除外し undefined", () => {
    addTextarea({ testId: "lyrics-textarea" });
    addTextarea({ placeholder: "Style description" });
    const hiddenTitle = addInput({ placeholder: "Song Title (Optional)" });
    hiddenTitle.style.visibility = "hidden";

    const fields = resolveFields();

    expect(fields.title).toBeUndefined();
  });

  it("Given placeholder が title 非該当の input のみ When 解決する Then title は undefined", () => {
    addTextarea({ testId: "lyrics-textarea" });
    addTextarea({ placeholder: "Style description" });
    addInput({ placeholder: "Search" });

    const fields = resolveFields();

    expect(fields.title).toBeUndefined();
  });

  it("Given title input が存在 When 解決する Then style/lyrics の解決は影響を受けない (input は textarea クエリに混ざらない)", () => {
    // title は <input>、style/lyrics は <textarea>。別クエリのため title 追加で既存解決が壊れないことを担保。
    const lyrics = addTextarea({ testId: "lyrics-textarea" });
    const style = addTextarea({ placeholder: "Style description" });
    addInput({ placeholder: "Song Title (Optional)" });

    const fields = resolveFields();

    expect(fields.lyrics).toBe(lyrics);
    expect(fields.style).toBe(style);
  });

  it("Given lyrics-textarea しか可視でない + title input あり When 解決する Then style 解決不能で throw する (title の fail-soft は style の fail-loud を弱めない)", () => {
    addTextarea({ testId: "lyrics-textarea" });
    addInput({ placeholder: "Song Title (Optional)" });

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

  it("Given Generate ボタンが非表示 (bbox 0) When 解決する Then throw する", () => {
    addButton("Generate", false);

    expect(() => resolveGenerateButton()).toThrow();
  });
});

describe("detectRecaptcha: 可視なチャレンジのみ検知 (#810)", () => {
  describe("可視な challenge iframe は true", () => {
    it("Given 可視 recaptcha iframe (src) When 検知する Then true", () => {
      addCaptchaIframe({ src: "https://www.google.com/recaptcha/api2/anchor" });
      expect(detectRecaptcha()).toBe(true);
    });

    it("Given 可視 recaptcha iframe (title) When 検知する Then true", () => {
      addCaptchaIframe({ title: "reCAPTCHA challenge" });
      expect(detectRecaptcha()).toBe(true);
    });

    it("Given 可視 hcaptcha iframe (src) When 検知する Then true", () => {
      addCaptchaIframe({ src: "https://newassets.hcaptcha.com/captcha/v1" });
      expect(detectRecaptcha()).toBe(true);
    });

    it("Given 可視 hcaptcha iframe (title=hCaptchaチャレンジ) When 検知する Then true (実 challenge 表示時)", () => {
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/x",
        title: "hCaptchaチャレンジ",
      });
      expect(detectRecaptcha()).toBe(true);
    });
  });

  describe("非表示のプリロード hCaptcha iframe は false (誤検知防止)", () => {
    it("Given display:none かつ 0×0 の hCaptcha iframe (実 DOM iframe[0]) When 検知する Then false", () => {
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/x",
        display: "none",
        width: 0,
        height: 0,
      });
      expect(detectRecaptcha()).toBe(false);
    });

    it("Given visibility:hidden + title 無しの hCaptcha プリロード iframe (300×150) When 検知する Then false (誤検知防止の核心)", () => {
      // #875: title が空のプリロード iframe は active challenge ではない。従来 strict isVisible で false。
      // title が non-empty になった瞬間だけ active 判定する遷移は別 describe (title 判定の 4 組合せ) で検証。
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/x",
        visibility: "hidden",
        width: 300,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(false);
    });

    it("Given opacity:0 の hCaptcha iframe When 検知する Then false", () => {
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/x",
        opacity: "0",
        width: 300,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(false);
    });

    it("Given bbox が 0×0 の hCaptcha iframe (style は可視) When 検知する Then false", () => {
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/x",
        width: 0,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(false);
    });
  });

  describe("親要素の非表示も親 walk で排除する", () => {
    it("Given 親 div が display:none の hCaptcha iframe When 検知する Then false", () => {
      const parent = document.createElement("div");
      parent.style.display = "none";
      document.body.appendChild(parent);
      const f = document.createElement("iframe");
      f.src = "https://hcaptcha-assets-prod.suno.com/captcha/v1/x";
      parent.appendChild(f);
      markBbox(f, 300, 150);

      expect(detectRecaptcha()).toBe(false);
    });
  });

  describe("order.md 実 DOM シナリオの回帰ガード", () => {
    it("Given 非表示プリロード iframe 2 個 (display:none + visibility:hidden, title 無し) のみ When 検知する Then false (challenge 未表示時)", () => {
      // #875: title 無しのプリロード iframe は active challenge ではない。title が non-empty に
      // なった瞬間の active 判定 (visibility:hidden 許容) は「title 判定の 4 組合せ」describe で担保する。
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/0",
        display: "none",
        width: 0,
        height: 0,
      });
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/4",
        visibility: "hidden",
        width: 300,
        height: 150,
      });

      expect(detectRecaptcha()).toBe(false);
    });

    it("Given 非表示プリロード 2 個 + 可視 challenge 1 個 When 検知する Then true (実 challenge 表示時のみ検知)", () => {
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/0",
        display: "none",
        width: 0,
        height: 0,
      });
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/4",
        visibility: "hidden",
        width: 300,
        height: 150,
      });
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/visible",
        title: "hCaptchaチャレンジ",
        width: 300,
        height: 150,
      });

      expect(detectRecaptcha()).toBe(true);
    });
  });

  describe("title 判定による active challenge 検知の 4 組合せ (#875, #924)", () => {
    // #875: hCaptcha challenge iframe の title が non-empty になった瞬間を active challenge とみなし、
    // visibility:hidden の中間状態でも捕捉する。title 空のときのみ従来 strict isVisible へ fallback。
    // 真因: silent drop タイミングで title が "" → "hCaptchaチャレンジ" に変化するが visibility:hidden は
    // 維持されるため、従来 strict isVisible では false で素通りしていた。
    // #924: title 非空ヒューリスティックは challenge 系 iframe（#frame=challenge / /bframe）に限定する。
    // anchor / checkbox / badge 系 widget は常時 title を持つため、src に challenge 識別子を含む
    // iframe のみに絞らないと誤検知する。
    // → visibility:hidden の中間状態を捕捉するテストでは src に #frame=challenge を付与する。
    const HCAPTCHA_CHALLENGE_SRC = "https://hcaptcha-assets-prod.suno.com/captcha/v1/x#frame=challenge";

    it("Given title 空 × visible When 検知する Then true (従来 strict isVisible 経路)", () => {
      addCaptchaIframe({ src: HCAPTCHA_CHALLENGE_SRC, width: 300, height: 150 });
      expect(detectRecaptcha()).toBe(true);
    });

    it("Given title 空 × visibility:hidden When 検知する Then false (プリロード誤検知防止)", () => {
      addCaptchaIframe({ src: HCAPTCHA_CHALLENGE_SRC, visibility: "hidden", width: 300, height: 150 });
      expect(detectRecaptcha()).toBe(false);
    });

    it("Given title 非空 × visible When 検知する Then true (active challenge)", () => {
      addCaptchaIframe({ src: HCAPTCHA_CHALLENGE_SRC, title: "hCaptchaチャレンジ", width: 300, height: 150 });
      expect(detectRecaptcha()).toBe(true);
    });

    it("Given challenge 系 src + title 非空 × visibility:hidden When 検知する Then true (#875 隠れ challenge を捕捉)", () => {
      // 本 issue の核心ケース: title="hCaptchaチャレンジ" だが visibility:hidden の中間状態。
      // challenge 系 src (#frame=challenge) のみに title 判定を適用するため、anchor 等は誤検知しない (#924)。
      addCaptchaIframe({
        src: HCAPTCHA_CHALLENGE_SRC,
        title: "hCaptchaチャレンジ",
        visibility: "hidden",
        width: 300,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(true);
    });

    it("Given title 非空 だが bbox 0×0 When 検知する Then false (bbox 判定を title より優先)", () => {
      // bbox 0 チェックを title 判定より前に置く。0×0 のプリロード iframe が title を持っていても
      // 誤検知しない（既存 bbox 0×0 ケースと整合）。
      addCaptchaIframe({ src: HCAPTCHA_CHALLENGE_SRC, title: "hCaptchaチャレンジ", width: 0, height: 0 });
      expect(detectRecaptcha()).toBe(false);
    });

    it("Given 検証完了後の駐機 iframe (title 非空, visibility:hidden, y:-9999) When 検知する Then false (verify 後の恒久誤検知防止)", () => {
      // 実機観測: 自動 verify 後の challenge iframe は title と bbox を保持したまま画面外 (y:-9999) に
      // 駐機する。title 非空ヒューリスティック (#875) がこれを active と誤検知すると、再開しても
      // 即 ERROR で停止し続ける。viewport 上端より完全に上 (rect.bottom <= 0) は active としない。
      addCaptchaIframe({
        src: HCAPTCHA_CHALLENGE_SRC,
        title: "hCaptchaチャレンジ",
        visibility: "hidden",
        width: 300,
        height: 150,
        y: -9999,
      });
      expect(detectRecaptcha()).toBe(false);
    });
  });

  it("Given challenge 類似 iframe 無し When 検知する Then false", () => {
    addCaptchaIframe({ src: "https://suno.com/embed" });
    expect(detectRecaptcha()).toBe(false);
  });

  describe("title 判定は challenge 系 iframe に限定 (#924)", () => {
    // #924: anchor / checkbox / badge 系 widget は常時 title を持つ。
    // title 非空ヒューリスティックを challenge 系（#frame=challenge / /bframe）に限定することで
    // widget の誤検知を防ぐ。

    it("Given hidden hCaptcha checkbox widget (title 非空, visibility:hidden, bbox>0) When 検知する Then false (widget 誤検知防止)", () => {
      // hCaptcha checkbox widget の src は #frame=challenge を含まないため、
      // title 非空でも challenge 系として扱わず isVisible() fallback で false。
      addCaptchaIframe({
        src: "https://newassets.hcaptcha.com/captcha/v1/x/static/hcaptcha.html#frame=checkbox",
        title: "hCaptchaチェックボックス",
        visibility: "hidden",
        width: 300,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(false);
    });

    it("Given hidden reCAPTCHA anchor (title='reCAPTCHA', visibility:hidden, bbox>0) When 検知する Then false (anchor 誤検知防止)", () => {
      // reCAPTCHA anchor widget は title="reCAPTCHA" を常時持つが src に /bframe も #frame=challenge も含まない。
      // challenge 系ではないため title 非空でも isVisible() fallback で false。
      addCaptchaIframe({
        src: "https://www.google.com/recaptcha/api2/anchor?k=x",
        title: "reCAPTCHA",
        visibility: "hidden",
        width: 300,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(false);
    });

    it("Given hidden reCAPTCHA bframe (title 非空, visibility:hidden, bbox>0) When 検知する Then true (/bframe は challenge 系)", () => {
      // reCAPTCHA bframe は /bframe を含む challenge 系 iframe。
      // title 非空 × visibility:hidden でも challenge と判定して true (#875 挙動を維持)。
      addCaptchaIframe({
        src: "https://www.google.com/recaptcha/api2/bframe?k=x",
        title: "reCAPTCHA チャレンジ",
        visibility: "hidden",
        width: 300,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(true);
    });

    it("Given hidden hCaptcha challenge (#frame=challenge, title 非空, visibility:hidden, bbox>0) When 検知する Then true (#875 回帰ガード)", () => {
      // #875 の核心ケース回帰ガード: #frame=challenge 付き hCaptcha challenge は
      // visibility:hidden でも title 非空であれば true。
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/x#frame=challenge",
        title: "hCaptchaチャレンジ",
        visibility: "hidden",
        width: 300,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(true);
    });

    it("Given 可視 anchor widget (src=anchor, visible, bbox>0, title='reCAPTCHA') When 検知する Then true (従来 isVisible 経路の維持)", () => {
      // anchor widget であっても可視であれば isVisible() 経路で true。
      // challenge 系限定は title 非空ヒューリスティックの話であり、可視判定は変わらない。
      addCaptchaIframe({
        src: "https://www.google.com/recaptcha/api2/anchor?k=x",
        title: "reCAPTCHA",
        width: 300,
        height: 150,
      });
      expect(detectRecaptcha()).toBe(true);
    });
  });
});

describe("isQueueLimitErrorVisible: queue 上限エラー toast の検知 (#847)", () => {
  // 契約 (draft が実装する public API, shared/dom.ts):
  //   - QUEUE_LIMIT_ERROR_SELECTOR: string = '[role="dialog"]'
  //   - isQueueLimitErrorVisible(): boolean
  //     = 可視な `[role="dialog"]` のうち英語見出し "generation in progress" を
  //       case-insensitive substring match で含むものがあれば true。
  //     detectRecaptcha (#810) と同じ strict isVisible で非表示 toast 残骸を弾く。

  it('Given QUEUE_LIMIT_ERROR_SELECTOR When 読む Then [role="dialog"] である', () => {
    expect(QUEUE_LIMIT_ERROR_SELECTOR).toBe('[role="dialog"]');
  });

  describe("可視な該当 toast は true", () => {
    it("Given 可視 dialog に 'Generation in progress' When 検知する Then true", () => {
      addQueueErrorDialog();
      expect(isQueueLimitErrorVisible()).toBe(true);
    });

    it("Given 大文字の 'GENERATION IN PROGRESS' When 検知する Then true (case-insensitive)", () => {
      addQueueErrorDialog({ text: "GENERATION IN PROGRESS" });
      expect(isQueueLimitErrorVisible()).toBe(true);
    });

    it("Given 英語見出し + 日本語並列テキスト混在 When 検知する Then true (多言語耐性)", () => {
      // order.md 実 DOM: 英語 H3 + 日本語 SPAN が並ぶ。英語 substring match で多言語に耐える。
      addQueueErrorDialog({
        text: "Generation in progress",
        japanese: "他の曲の生成が完了するまでお待ちいただき、その後もう一度お試しください。",
      });
      expect(isQueueLimitErrorVisible()).toBe(true);
    });

    it("Given ノイズ dialog と該当・可視 dialog が併存 When 検知する Then true (1 個でもあれば検知)", () => {
      addQueueErrorDialog({ text: "Saved to library", japanese: "ライブラリに保存しました" });
      addQueueErrorDialog();
      expect(isQueueLimitErrorVisible()).toBe(true);
    });
  });

  describe("非該当・非可視は false", () => {
    it("Given dialog が無い When 検知する Then false", () => {
      expect(isQueueLimitErrorVisible()).toBe(false);
    });

    it("Given 該当テキストを含まない dialog When 検知する Then false (他種 toast を誤検知しない)", () => {
      addQueueErrorDialog({ text: "Saved to library", japanese: "ライブラリに保存しました" });
      expect(isQueueLimitErrorVisible()).toBe(false);
    });

    it("Given 該当テキストだが display:none + bbox0 の dialog When 検知する Then false (strict isVisible)", () => {
      addQueueErrorDialog({ visible: false });
      expect(isQueueLimitErrorVisible()).toBe(false);
    });

    it("Given 該当テキストだが visibility:hidden の dialog When 検知する Then false", () => {
      const dialog = addQueueErrorDialog();
      dialog.style.visibility = "hidden";
      expect(isQueueLimitErrorVisible()).toBe(false);
    });

    it("Given 該当テキストだが opacity:0 の dialog When 検知する Then false", () => {
      const dialog = addQueueErrorDialog();
      dialog.style.opacity = "0";
      expect(isQueueLimitErrorVisible()).toBe(false);
    });

    it("Given 親が display:none の該当 dialog When 検知する Then false (親 walk で除外)", () => {
      const wrapper = document.createElement("div");
      wrapper.style.display = "none";
      document.body.appendChild(wrapper);
      const dialog = addQueueErrorDialog(); // bbox は非 0。除外理由は親の display:none のみに限定する。
      wrapper.appendChild(dialog); // body 直下から display:none の wrapper 配下へ移す

      expect(isQueueLimitErrorVisible()).toBe(false);
    });

    it("Given 非該当の可視 dialog と 該当の非可視 dialog が併存 When 検知する Then false", () => {
      addQueueErrorDialog({ text: "Saved", japanese: "保存" }); // 可視だが非該当
      addQueueErrorDialog({ visible: false }); // 該当だが非可視
      expect(isQueueLimitErrorVisible()).toBe(false);
    });
  });
});

describe("abortableSleep: 中断可能な待機 (#847)", () => {
  // 契約 (draft が実装する public API, shared/dom.ts):
  //   - abortableSleep(ms: number, isAborted: () => boolean): Promise<void>
  //     = ms 経過 または isAborted() が true になった時点（内部 poll で検知）の早い方で resolve。
  //       sleep と同じく throw / reject しない。
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given 中断されない When ms 経過 Then resolve する", async () => {
    const pending = abortableSleep(100, () => false);
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(100);

    expect(settled).toBe(true);
    await expect(pending).resolves.toBeUndefined();
  });

  it("Given 中断されない When ms 未経過 Then まだ resolve しない (sleep 同様 ms をフル待機)", async () => {
    const pending = abortableSleep(100, () => false);
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(50);
    expect(settled).toBe(false); // 半分では resolve しない

    await vi.advanceTimersByTimeAsync(50);
    await expect(pending).resolves.toBeUndefined();
  });

  it("Given 待機中に中断フラグが立つ When 次の poll Then ms 経過前に resolve する (#847 停止反応性)", async () => {
    // 受け入れ条件「停止押下後 3 秒以内にフロー停止」を満たすため、長い待機 (ここでは 100s) の
    // 途中で中断フラグが立ったら ms を待たず resolve する。粒度は 3 秒以内停止に十分小さい前提で、
    // 中断後 1 秒以内の resolve を contract として pin する（内部 poll の正確値には依存しない）。
    let aborted = false;
    const pending = abortableSleep(100_000, () => aborted);
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(500);
    expect(settled).toBe(false); // まだ中断されていない（フル待機中）

    aborted = true;
    await vi.advanceTimersByTimeAsync(1000);

    expect(settled).toBe(true); // 100s を待たず中断検知で resolve
    await expect(pending).resolves.toBeUndefined();
  });

  it("Given 開始時点で既に中断 When 待機する Then ms を待たず即 resolve する", async () => {
    const pending = abortableSleep(100_000, () => true);

    await vi.advanceTimersByTimeAsync(0); // microtask flush のみ

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given どのケースでも When 待機する Then reject しない (throw しない契約)", async () => {
    const normal = abortableSleep(10, () => false);
    const aborted = abortableSleep(100_000, () => true);

    await vi.advanceTimersByTimeAsync(20);

    await expect(normal).resolves.toBeUndefined();
    await expect(aborted).resolves.toBeUndefined();
  });
});

// radix Slider を模す: ArrowRight/Left の keydown で aria-valuenow を ±1 する。
// 実 Suno の radix Slider root は addEventListener('keydown') で値を駆動するため、
// setSliderValue は focus → keydown dispatch → aria-valuenow 読み戻し検証で動く前提。
function addSlider(opts: { ariaLabel?: string; value: number; visible?: boolean; respond?: boolean }): HTMLElement {
  const slider = document.createElement("div");
  slider.setAttribute("role", "slider");
  if (opts.ariaLabel !== undefined) slider.setAttribute("aria-label", opts.ariaLabel);
  slider.setAttribute("aria-valuenow", String(opts.value));
  slider.setAttribute("tabindex", "0");
  document.body.appendChild(slider);
  setRect(slider, opts.visible === false ? ZERO_RECT : VISIBLE_RECT);
  if (opts.respond !== false) {
    slider.addEventListener("keydown", (e) => {
      const key = (e as KeyboardEvent).key;
      const cur = Number(slider.getAttribute("aria-valuenow"));
      if (key === "ArrowRight") slider.setAttribute("aria-valuenow", String(cur + 1));
      else if (key === "ArrowLeft") slider.setAttribute("aria-valuenow", String(cur - 1));
    });
  }
  return slider;
}

describe("setSliderValue: radix slider への keydown 駆動注入 (#900)", () => {
  // 契約 (draft が実装する public API, shared/dom.ts):
  //   setSliderValue(slider: HTMLElement, target: number): Promise<void>
  //     1. slider.focus()
  //     2. current = Number(slider.getAttribute("aria-valuenow"))
  //     3. delta = target - current。delta>=0 なら ArrowRight、<0 なら ArrowLeft を
  //        |delta| 回 dispatch（KeyboardEvent, bubbles:true, composed:true で radix root へ届かせる）
  //     4. 読み戻し poll（100ms 間隔 × 最大 5 回）で aria-valuenow === target を検証
  //     5. 一致で resolve / 5 回後も不一致なら throw（fail-loud。silent に値ずれを通さない）
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("Given valuenow=50, target=85 When setSliderValue Then ArrowRight×35 で aria-valuenow が 85 になる", async () => {
    const slider = addSlider({ ariaLabel: "Style Influence", value: 50 });
    let rightCount = 0;
    slider.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "ArrowRight") rightCount += 1;
    });

    const pending = setSliderValue(slider, 85);
    await vi.advanceTimersByTimeAsync(1000);

    await expect(pending).resolves.toBeUndefined();
    expect(slider.getAttribute("aria-valuenow")).toBe("85");
    expect(rightCount).toBe(35); // delta = 85 - 50
  });

  it("Given valuenow=90, target=85 When setSliderValue Then ArrowLeft×5 で aria-valuenow が 85 になる", async () => {
    const slider = addSlider({ ariaLabel: "Weirdness", value: 90 });
    let leftCount = 0;
    slider.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "ArrowLeft") leftCount += 1;
    });

    const pending = setSliderValue(slider, 85);
    await vi.advanceTimersByTimeAsync(1000);

    await expect(pending).resolves.toBeUndefined();
    expect(slider.getAttribute("aria-valuenow")).toBe("85");
    expect(leftCount).toBe(5); // |85 - 90|
  });

  it("Given valuenow=85, target=85 (delta 0) When setSliderValue Then keydown を出さず resolve する", async () => {
    const slider = addSlider({ ariaLabel: "Weirdness", value: 85 });
    let keyCount = 0;
    slider.addEventListener("keydown", () => {
      keyCount += 1;
    });

    const pending = setSliderValue(slider, 85);
    await vi.advanceTimersByTimeAsync(1000);

    await expect(pending).resolves.toBeUndefined();
    expect(keyCount).toBe(0);
    expect(slider.getAttribute("aria-valuenow")).toBe("85");
  });

  it("Given valuenow=0, target=40 When setSliderValue Then 起点で focus を呼ぶ", async () => {
    const slider = addSlider({ ariaLabel: "Weirdness", value: 0 });
    const focusSpy = vi.spyOn(slider, "focus");

    const pending = setSliderValue(slider, 40);
    await vi.advanceTimersByTimeAsync(1000);
    await pending;

    expect(focusSpy).toHaveBeenCalled();
  });

  it("Given keydown が bubbling 必要 When setSliderValue Then composed/bubbles 付きで親へ届く（radix root 到達担保）", async () => {
    // 実 Suno の radix Slider root は子 thumb の keydown を bubbling で受ける。
    // dispatchEvent が bubbles:true でなければ root の listener に届かず値が動かない。
    const slider = addSlider({ ariaLabel: "Style Influence", value: 50 });
    let bubbledToBody = 0;
    const handler = (e: Event): void => {
      if ((e as KeyboardEvent).key === "ArrowRight") bubbledToBody += 1;
    };
    document.body.addEventListener("keydown", handler);

    const pending = setSliderValue(slider, 53);
    await vi.advanceTimersByTimeAsync(1000);
    await pending;
    document.body.removeEventListener("keydown", handler);

    expect(bubbledToBody).toBe(3); // body まで bubbling した keydown 数 = delta
  });

  it("Given slider が keydown に反応しない When setSliderValue Then 読み戻し検証に失敗して throw する", async () => {
    // respond:false は値を更新しない壊れた / UI 改装後の slider を模す。読み戻し poll が
    // target に届かないまま尽きたら silent に通さず throw する（fail-loud）。
    const slider = addSlider({ ariaLabel: "Style Influence", value: 50, respond: false });

    const pending = setSliderValue(slider, 85);
    const caught = pending.catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(2000);
    const err = await caught;

    expect(err).toBeInstanceOf(Error);
    expect(slider.getAttribute("aria-valuenow")).toBe("50"); // 値は動いていない
  });
});

// Suno Exclude styles の native text input を模す（placeholder 完全一致で識別する）。
function addExcludeInput(opts: { visible?: boolean } = {}): HTMLInputElement {
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Exclude styles";
  input.setAttribute("maxlength", "1000");
  document.body.appendChild(input);
  setRect(input, opts.visible === false ? ZERO_RECT : VISIBLE_RECT);
  return input;
}

describe("resolveAdvancedFields: More Options 3 フィールドの解決 (#900, fail-soft)", () => {
  // 契約 (shared/dom.ts):
  //   resolveAdvancedFields(): {
  //     excludeStyles: HTMLInputElement | null;
  //     weirdness: HTMLElement | null;
  //     styleInfluence: HTMLElement | null;
  //   }
  //   挙動: visible 優先・なければ DOM 上の最初の要素。0 件のみ null（fail-soft、throw しない）。
  //   実機検証で More Options collapsed 時に 3 要素とも祖先 display:none で isVisible=false になるが
  //   DOM 自体は残ること、input は閉じてても setNativeValue で React props まで更新されることを確認済み。
  //   そのため strict visible 必須を緩めて collapsed 時にも要素を掴む。Slider は閉開問わず合成イベントが
  //   弾かれるため注入時 fail-soft で吸収する（injectAdvancedFields 側）。

  it("Given 3 要素すべて visible When 解決する Then すべて解決する", () => {
    const exclude = addExcludeInput();
    const weirdness = addSlider({ ariaLabel: "Weirdness", value: 0 });
    const styleInfluence = addSlider({ ariaLabel: "Style Influence", value: 50 });

    const fields = resolveAdvancedFields();

    expect(fields.excludeStyles).toBe(exclude);
    expect(fields.weirdness).toBe(weirdness);
    expect(fields.styleInfluence).toBe(styleInfluence);
  });

  it("Given 要素が何も無い When 解決する Then すべて null（throw しない fail-soft）", () => {
    const fields = resolveAdvancedFields();

    expect(fields.excludeStyles).toBeNull();
    expect(fields.weirdness).toBeNull();
    expect(fields.styleInfluence).toBeNull();
  });

  it("Given Exclude styles input だけ存在 When 解決する Then excludeStyles のみ解決し slider 2 つは null", () => {
    const exclude = addExcludeInput();

    const fields = resolveAdvancedFields();

    expect(fields.excludeStyles).toBe(exclude);
    expect(fields.weirdness).toBeNull();
    expect(fields.styleInfluence).toBeNull();
  });

  it("Given slider 2 つだけ存在 When 解決する Then aria-label で Weirdness / Style Influence を区別する", () => {
    const weirdness = addSlider({ ariaLabel: "Weirdness", value: 0 });
    const styleInfluence = addSlider({ ariaLabel: "Style Influence", value: 50 });

    const fields = resolveAdvancedFields();

    expect(fields.weirdness).toBe(weirdness);
    expect(fields.styleInfluence).toBe(styleInfluence);
    expect(fields.excludeStyles).toBeNull();
  });

  it("Given hidden slider のみ When 解決する Then hidden 要素を返す（collapsed 時の DOM 要素を掴む）", () => {
    // More Options collapsed 時の挙動。strict visible 必須を撤回した結果、hidden でも DOM 上の要素を返す。
    const hidden = addSlider({ ariaLabel: "Weirdness", value: 0, visible: false });

    const fields = resolveAdvancedFields();

    expect(fields.weirdness).toBe(hidden);
  });

  it("Given visibility:hidden の Exclude styles input When 解決する Then 該当 input を返す（collapsed 時も値注入できる）", () => {
    const exclude = addExcludeInput();
    exclude.style.visibility = "hidden";

    const fields = resolveAdvancedFields();

    expect(fields.excludeStyles).toBe(exclude);
  });

  it("Given visible + hidden 混在 When 解決する Then visible を優先する", () => {
    // 同じ selector に複数 hit する誤検出耐性。実機の Suno UI 改装で visible/hidden が混在した場合に visible を選ぶ。
    const hidden = addExcludeInput();
    hidden.style.visibility = "hidden";
    const visible = addExcludeInput();

    const fields = resolveAdvancedFields();

    expect(fields.excludeStyles).toBe(visible);
  });

  it("Given placeholder 不一致の input のみ When 解決する Then excludeStyles は null（厳密 placeholder 一致）", () => {
    const other = document.createElement("input");
    other.placeholder = "Search styles";
    document.body.appendChild(other);
    setRect(other, VISIBLE_RECT);

    const fields = resolveAdvancedFields();

    expect(fields.excludeStyles).toBeNull();
  });
});

// Suno Voice section の Male / Female ボタンペアを模す。
// 実 DOM 構造: <div><button data-selected>Male</button><button data-selected>Female</button></div>
function addVocalGenderButtons(
  opts: {
    maleSelected?: boolean;
    femaleSelected?: boolean;
    visible?: boolean;
  } = {},
): { male: HTMLButtonElement; female: HTMLButtonElement } {
  const wrapper = document.createElement("div");
  document.body.appendChild(wrapper);
  const make = (label: string, selected: boolean): HTMLButtonElement => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("data-selected", selected ? "true" : "false");
    btn.textContent = label;
    wrapper.appendChild(btn);
    setRect(btn, opts.visible === false ? ZERO_RECT : VISIBLE_RECT);
    return btn;
  };
  return {
    male: make("Male", opts.maleSelected === true),
    female: make("Female", opts.femaleSelected === true),
  };
}

describe("resolveAdvancedFields: vocal gender (Male / Female) ボタン解決", () => {
  // 契約: resolveAdvancedFields() が ResolvedAdvancedFields.vocalGender = { male, female } を返す。
  //   - SELECTOR は `button[data-selected][type="button"]` で候補を全 query → textContent === "Male"/"Female" で絞り込み
  //   - visible 優先・なければ DOM 上の最初の要素（pickPreferVisible）
  //   - 不在は null（fail-soft、throw しない）
  //   - 判定は case-sensitive（"male" lowercase は拾わない、誤検出耐性）

  it("Given Male / Female ボタン両方存在 When 解決する Then 両方解決する", () => {
    const { male, female } = addVocalGenderButtons();

    const fields = resolveAdvancedFields();

    expect(fields.vocalGender.male).toBe(male);
    expect(fields.vocalGender.female).toBe(female);
  });

  it("Given Male のみ存在 When 解決する Then male: ボタン / female: null", () => {
    const wrapper = document.createElement("div");
    document.body.appendChild(wrapper);
    const male = document.createElement("button");
    male.type = "button";
    male.setAttribute("data-selected", "false");
    male.textContent = "Male";
    wrapper.appendChild(male);
    setRect(male, VISIBLE_RECT);

    const fields = resolveAdvancedFields();

    expect(fields.vocalGender.male).toBe(male);
    expect(fields.vocalGender.female).toBeNull();
  });

  it("Given Male / Female ボタンが何も存在しない When 解決する Then 両方 null（resolveAdvancedFields は throw しない）", () => {
    const fields = resolveAdvancedFields();

    expect(fields.vocalGender.male).toBeNull();
    expect(fields.vocalGender.female).toBeNull();
  });

  it("Given visible Male + hidden Male 混在 When 解決する Then visible を優先する", () => {
    // pickPreferVisible 流用確認（UI 再構築で同 label の button が一時的に複数残った場合の耐性）。
    const wrapper = document.createElement("div");
    document.body.appendChild(wrapper);
    const hidden = document.createElement("button");
    hidden.type = "button";
    hidden.setAttribute("data-selected", "false");
    hidden.textContent = "Male";
    wrapper.appendChild(hidden);
    setRect(hidden, ZERO_RECT);
    const visible = document.createElement("button");
    visible.type = "button";
    visible.setAttribute("data-selected", "false");
    visible.textContent = "Male";
    wrapper.appendChild(visible);
    setRect(visible, VISIBLE_RECT);

    const fields = resolveAdvancedFields();

    expect(fields.vocalGender.male).toBe(visible);
  });

  it('Given textContent が "male" lowercase の偽 button のみ When 解決する Then male: null（厳密 case-sensitive）', () => {
    // 誤検出耐性: Suno の他 UI ("e-mail" の "mail" 等) を拾わないために case-sensitive 完全一致で判定する。
    const wrapper = document.createElement("div");
    document.body.appendChild(wrapper);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("data-selected", "false");
    btn.textContent = "male";
    wrapper.appendChild(btn);
    setRect(btn, VISIBLE_RECT);

    const fields = resolveAdvancedFields();

    expect(fields.vocalGender.male).toBeNull();
  });
});
