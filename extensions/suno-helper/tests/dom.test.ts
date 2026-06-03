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
  resolveFields,
  resolveGenerateButton,
  setNativeValue,
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

    it("Given visibility:hidden だが 300×150 の hCaptcha iframe (実 DOM iframe[4]) When 検知する Then false", () => {
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/x",
        title: "hCaptchaチャレンジ",
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
    it("Given 非表示プリロード iframe 2 個 (display:none + visibility:hidden) のみ When 検知する Then false (challenge 未表示時)", () => {
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/0",
        display: "none",
        width: 0,
        height: 0,
      });
      addCaptchaIframe({
        src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/4",
        title: "hCaptchaチャレンジ",
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

  it("Given challenge 類似 iframe 無し When 検知する Then false", () => {
    addCaptchaIframe({ src: "https://suno.com/embed" });
    expect(detectRecaptcha()).toBe(false);
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
