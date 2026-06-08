// @vitest-environment jsdom
//
// More Options 3 フィールド (Style Influence / Weirdness / Exclude styles) の注入における
// 非対称契約 (#900 要件4) の回帰テスト。
//
// この判定ロジックを content.ts の injectAndGenerate クロージャ内にインライン化すると unit test
// から到達できず、テスト側で再実装する (実呼び出しチェーンを通らない) アンチパターンに陥る。
// そのため resolveAdvancedFields() の解決結果 (fields) と entry の値有無を突き合わせる純ロジックを
// shared/dom.ts::injectAdvancedFields として抽出し、依存 (resolved fields) を引数注入して検証する。
//
// 契約 (draft が実装する public API、shared/dom.ts):
//   injectAdvancedFields(entry, fields): Promise<void>
//     entry:  { style_influence?: number; weirdness?: number; exclude_styles?: string }
//     fields: { excludeStyles: HTMLInputElement | null; weirdness: HTMLElement | null; styleInfluence: HTMLElement | null }
//   注入順序: Exclude styles (text, 高速) → Weirdness → Style Influence
//   各フィールドの非対称契約:
//     - entry に値有 (=== undefined でない) + 対応 selector が null → throw (fail-loud、UI 改装検知)
//     - entry に値無 (=== undefined)                              → skip (fail-soft、後方互換)
//     - entry に値有 + selector 有                                 → 注入する
//       (exclude_styles は setNativeValue / slider 2 つは setSliderValue)
//   値の有無判定は `!== undefined`。0 や "" の falsy 値を truthy 判定で脱落させない。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { injectAdvancedFields, type ResolvedAdvancedFields } from "../../shared/dom";

/** radix Slider を模す: ArrowRight/Left の keydown で aria-valuenow を ±1 する。respond:false は無反応。 */
function makeSlider(value: number, opts: { respond?: boolean } = {}): HTMLElement {
  const slider = document.createElement("div");
  slider.setAttribute("role", "slider");
  slider.setAttribute("aria-valuenow", String(value));
  slider.setAttribute("tabindex", "0");
  document.body.appendChild(slider);
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

/** Suno Exclude styles の native text input を模す。 */
function makeExcludeInput(): HTMLInputElement {
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Exclude styles";
  document.body.appendChild(input);
  return input;
}

const ALL_NULL: ResolvedAdvancedFields = {
  excludeStyles: null,
  weirdness: null,
  styleInfluence: null,
};

beforeEach(() => {
  document.body.innerHTML = "";
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("injectAdvancedFields: 非対称契約 (fail-loud / fail-soft, #900)", () => {
  describe("値有 + selector 不在 → throw (fail-loud)", () => {
    it("Given entry.style_influence 有 + styleInfluence selector null When 注入 Then throw する", async () => {
      await expect(injectAdvancedFields({ style_influence: 85 }, ALL_NULL)).rejects.toThrow();
    });

    it("Given entry.weirdness 有 + weirdness selector null When 注入 Then throw する", async () => {
      await expect(injectAdvancedFields({ weirdness: 30 }, ALL_NULL)).rejects.toThrow();
    });

    it("Given entry.exclude_styles 有 + excludeStyles selector null When 注入 Then throw する", async () => {
      await expect(injectAdvancedFields({ exclude_styles: "hyperpop, edm" }, ALL_NULL)).rejects.toThrow();
    });
  });

  describe("値無 → skip (fail-soft)", () => {
    it("Given entry に advanced フィールド無し + 全 selector null When 注入 Then throw せず resolve する", async () => {
      await expect(injectAdvancedFields({}, ALL_NULL)).resolves.toBeUndefined();
    });

    it("Given entry に値無 + selector は存在 When 注入 Then selector を一切触らない", async () => {
      const slider = makeSlider(50);
      const exclude = makeExcludeInput();

      await injectAdvancedFields({}, { excludeStyles: exclude, weirdness: slider, styleInfluence: slider });

      expect(slider.getAttribute("aria-valuenow")).toBe("50");
      expect(exclude.value).toBe("");
    });
  });

  describe("値有 + selector 有 → 注入する", () => {
    it("Given entry.exclude_styles 有 + input 有 When 注入 Then setNativeValue で値が入る", async () => {
      const exclude = makeExcludeInput();

      const pending = injectAdvancedFields(
        { exclude_styles: "hyperpop, edm" },
        { excludeStyles: exclude, weirdness: null, styleInfluence: null },
      );
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(exclude.value).toBe("hyperpop, edm");
    });

    it("Given entry.weirdness=30 + slider 有 When 注入 Then aria-valuenow が 30 になる", async () => {
      const weirdness = makeSlider(0);

      const pending = injectAdvancedFields({ weirdness: 30 }, { excludeStyles: null, weirdness, styleInfluence: null });
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(weirdness.getAttribute("aria-valuenow")).toBe("30");
    });

    it("Given entry.style_influence=85 + slider 有 When 注入 Then aria-valuenow が 85 になる", async () => {
      const styleInfluence = makeSlider(50);

      const pending = injectAdvancedFields(
        { style_influence: 85 },
        { excludeStyles: null, weirdness: null, styleInfluence },
      );
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(styleInfluence.getAttribute("aria-valuenow")).toBe("85");
    });

    it("Given entry.weirdness=0 + slider 有 When 注入 Then 0 を注入する（falsy でも !== undefined で通す）", async () => {
      // current 50 → target 0 (ArrowLeft×50)。truthy 判定だと 0 が skip され値ずれが残る。
      const weirdness = makeSlider(50);

      const pending = injectAdvancedFields({ weirdness: 0 }, { excludeStyles: null, weirdness, styleInfluence: null });
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(weirdness.getAttribute("aria-valuenow")).toBe("0");
    });
  });

  describe("注入順序: Exclude styles → Weirdness → Style Influence", () => {
    it("Given 3 フィールド全て設定 When 注入 Then 指定順で副作用が起きる", async () => {
      const order: string[] = [];
      const exclude = makeExcludeInput();
      exclude.addEventListener("input", () => {
        if (!order.includes("exclude")) order.push("exclude");
      });
      const weirdness = makeSlider(0);
      weirdness.addEventListener("keydown", () => {
        if (!order.includes("weirdness")) order.push("weirdness");
      });
      const styleInfluence = makeSlider(0);
      styleInfluence.addEventListener("keydown", () => {
        if (!order.includes("style_influence")) order.push("style_influence");
      });

      const pending = injectAdvancedFields(
        { exclude_styles: "hyperpop", weirdness: 30, style_influence: 85 },
        { excludeStyles: exclude, weirdness, styleInfluence },
      );
      await vi.advanceTimersByTimeAsync(3000);
      await pending;

      expect(order).toEqual(["exclude", "weirdness", "style_influence"]);
    });
  });
});
