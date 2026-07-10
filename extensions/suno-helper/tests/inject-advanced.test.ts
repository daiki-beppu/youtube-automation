// @vitest-environment jsdom
//
// More Options 3 フィールド (Style Influence / Weirdness / Exclude styles) の注入における
// 非対称契約 (#900 要件4) の回帰テスト。
//
// この判定ロジックを content.ts の injectEntryAndClickGenerate クロージャ内にインライン化すると unit test
// から到達できず、テスト側で再実装する (実呼び出しチェーンを通らない) アンチパターンに陥る。
// そのため resolveAdvancedFields() の解決結果 (fields) と entry の値有無を突き合わせる純ロジックを
// shared/dom.ts::injectAdvancedFields として抽出し、依存 (resolved fields) を引数注入して検証する。
//
// 契約 (shared/dom.ts):
//   injectAdvancedFields(entry, fields): Promise<void>
//     entry:  AdvancedFieldValues { style_influence?, weirdness?, exclude_styles?, vocal_gender? }
//     fields: ResolvedAdvancedFields { excludeStyles, weirdness, styleInfluence, vocalGender: { male, female } }
//   注入順序: Exclude styles (text, 高速) → vocal_gender (click 1 回) → Weirdness → Style Influence
//   各フィールドの非対称契約:
//     - entry に値有 (=== undefined でない) + 対応 selector が null:
//         - exclude_styles / vocal_gender → throw (fail-loud、UI 改装検知)
//         - slider 2 つ → console.warn + onSliderSkip + skip (fail-soft、#1720。値は UI で手動設定でき
//           Create を跨いで永続するため、Suno のリネームによる未検出で run を中断しない)
//     - entry に値無 (=== undefined)                              → skip (fail-soft、後方互換)
//     - entry に値有 + selector 有                                 → 注入する
//       (exclude_styles は setNativeValue / slider 2 つは setSliderValue / vocal_gender は click)
//     - vocal_gender = "neutral" / "auto"                          → click しない (既選択を解除しない)
//     - vocal_gender = "male" / "female" + 対応ボタンが既選択 → click しない (冪等)
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

/**
 * Suno Voice section の Male / Female ボタンペアを模す。
 * 実 DOM 構造: <div><button data-selected>Male</button><button data-selected>Female</button></div>
 */
function makeVocalGenderPair(
  opts: {
    maleSelected?: boolean;
    femaleSelected?: boolean;
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
    return btn;
  };
  return {
    male: make("Male", opts.maleSelected === true),
    female: make("Female", opts.femaleSelected === true),
  };
}

const ALL_NULL: ResolvedAdvancedFields = {
  excludeStyles: null,
  weirdness: null,
  styleInfluence: null,
  vocalGender: { male: null, female: null },
};

beforeEach(() => {
  document.body.innerHTML = "";
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("injectAdvancedFields: 非対称契約 (fail-loud / fail-soft, #900)", () => {
  describe("値有 + selector 不在 → exclude_styles は throw、slider は warn-skip (#1720)", () => {
    it("Given entry.style_influence 有 + styleInfluence selector null When 注入 Then throw せず warn + onSliderSkip で skip する", async () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const onSliderSkip = vi.fn();

      await expect(injectAdvancedFields({ style_influence: 85 }, ALL_NULL, { onSliderSkip })).resolves.toBeUndefined();

      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("Style Influence slider が見つかりません"));
      expect(onSliderSkip).toHaveBeenCalledWith("Style Influence");
      warnSpy.mockRestore();
    });

    it("Given entry.weirdness 有 + weirdness selector null When 注入 Then throw せず warn + onSliderSkip で skip する", async () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const onSliderSkip = vi.fn();

      await expect(injectAdvancedFields({ weirdness: 30 }, ALL_NULL, { onSliderSkip })).resolves.toBeUndefined();

      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("Weirdness slider が見つかりません"));
      expect(onSliderSkip).toHaveBeenCalledWith("Weirdness");
      warnSpy.mockRestore();
    });

    it("Given 両 slider 有 + 両 selector null When 注入 Then run を止めず両方 skip を通知する", async () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const onSliderSkip = vi.fn();

      await expect(
        injectAdvancedFields({ weirdness: 30, style_influence: 85 }, ALL_NULL, { onSliderSkip }),
      ).resolves.toBeUndefined();

      expect(onSliderSkip).toHaveBeenCalledTimes(2);
      expect(onSliderSkip).toHaveBeenNthCalledWith(1, "Weirdness");
      expect(onSliderSkip).toHaveBeenNthCalledWith(2, "Style Influence");
      warnSpy.mockRestore();
    });

    it("Given slider selector null + onSliderSkip 省略 When 注入 Then throw せず console.warn のみで skip する", async () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      await expect(injectAdvancedFields({ weirdness: 30 }, ALL_NULL)).resolves.toBeUndefined();

      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("Weirdness slider が見つかりません"));
      warnSpy.mockRestore();
    });

    it("Given entry.exclude_styles 有 + excludeStyles selector null When 注入 Then throw する", async () => {
      await expect(injectAdvancedFields({ exclude_styles: "hyperpop, edm" }, ALL_NULL)).rejects.toThrow(
        /その他のオプション/,
      );
    });
  });

  describe("値無 → skip (fail-soft)", () => {
    it("Given entry に advanced フィールド無し + 全 selector null When 注入 Then throw せず resolve する", async () => {
      await expect(injectAdvancedFields({}, ALL_NULL)).resolves.toBeUndefined();
    });

    it("Given entry に値無 + selector は存在 When 注入 Then selector を一切触らない", async () => {
      const slider = makeSlider(50);
      const exclude = makeExcludeInput();

      await injectAdvancedFields(
        {},
        { ...ALL_NULL, excludeStyles: exclude, weirdness: slider, styleInfluence: slider },
      );

      expect(slider.getAttribute("aria-valuenow")).toBe("50");
      expect(exclude.value).toBe("");
    });
  });

  describe("値有 + selector 有 → 注入する", () => {
    it("Given entry.exclude_styles 有 + input 有 When 注入 Then setNativeValue で値が入る", async () => {
      const exclude = makeExcludeInput();

      const pending = injectAdvancedFields(
        { exclude_styles: "hyperpop, edm" },
        { ...ALL_NULL, excludeStyles: exclude },
      );
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(exclude.value).toBe("hyperpop, edm");
    });

    it("Given entry.weirdness=30 + slider 有 When 注入 Then aria-valuenow が 30 になる", async () => {
      const weirdness = makeSlider(0);

      const pending = injectAdvancedFields({ weirdness: 30 }, { ...ALL_NULL, weirdness });
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(weirdness.getAttribute("aria-valuenow")).toBe("30");
    });

    it("Given entry.style_influence=85 + slider 有 When 注入 Then aria-valuenow が 85 になる", async () => {
      const styleInfluence = makeSlider(50);

      const pending = injectAdvancedFields({ style_influence: 85 }, { ...ALL_NULL, styleInfluence });
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(styleInfluence.getAttribute("aria-valuenow")).toBe("85");
    });

    it("Given entry.weirdness=0 + slider 有 When 注入 Then 0 を注入する（falsy でも !== undefined で通す）", async () => {
      // current 50 → target 0 (ArrowLeft×50)。truthy 判定だと 0 が skip され値ずれが残る。
      const weirdness = makeSlider(50);

      const pending = injectAdvancedFields({ weirdness: 0 }, { ...ALL_NULL, weirdness });
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(weirdness.getAttribute("aria-valuenow")).toBe("0");
    });
  });

  describe("bridge 経由の slider 注入 (#973)", () => {
    // options.bridgeSetSlider があれば MAIN world bridge 経由（React onKeyDown 直接呼び出し）を
    // 優先し、bridge が false / throw なら合成 dispatchEvent 経路へ縮退する。
    it("Given bridge 成功 When 注入 Then 合成イベント経路は使われない", async () => {
      const styleInfluence = makeSlider(50, { respond: false }); // dispatch では動かない slider
      styleInfluence.setAttribute("aria-label", "Style Influence");
      const bridgeSetSlider = vi.fn().mockResolvedValue(true);

      const pending = injectAdvancedFields(
        { style_influence: 95 },
        { ...ALL_NULL, styleInfluence },
        { bridgeSetSlider },
      );
      await vi.advanceTimersByTimeAsync(2000);
      await expect(pending).resolves.toBeUndefined();

      expect(bridgeSetSlider).toHaveBeenCalledWith("Style Influence", 95);
    });

    it("Given bridge 失敗 (false) When 注入 Then 合成イベント経路へ縮退して注入する", async () => {
      const weirdness = makeSlider(50); // dispatch で動く slider（e2e mock 相当）
      weirdness.setAttribute("aria-label", "Weirdness");
      const bridgeSetSlider = vi.fn().mockResolvedValue(false);

      const pending = injectAdvancedFields({ weirdness: 55 }, { ...ALL_NULL, weirdness }, { bridgeSetSlider });
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(weirdness.getAttribute("aria-valuenow")).toBe("55");
    });

    it("Given bridge throw When 注入 Then 合成イベント経路へ縮退する（fail-soft）", async () => {
      const weirdness = makeSlider(50);
      weirdness.setAttribute("aria-label", "Weirdness");
      const bridgeSetSlider = vi.fn().mockRejectedValue(new Error("bridge error"));

      const pending = injectAdvancedFields({ weirdness: 55 }, { ...ALL_NULL, weirdness }, { bridgeSetSlider });
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(weirdness.getAttribute("aria-valuenow")).toBe("55");
    });

    it("Given bridge も合成イベントも失敗 When 注入 Then warn + skip（従来どおり）", async () => {
      const styleInfluence = makeSlider(50, { respond: false });
      styleInfluence.setAttribute("aria-label", "Style Influence");
      const bridgeSetSlider = vi.fn().mockResolvedValue(false);
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const pending = injectAdvancedFields(
        { style_influence: 95 },
        { ...ALL_NULL, styleInfluence },
        { bridgeSetSlider },
      );
      await vi.advanceTimersByTimeAsync(2000);
      await expect(pending).resolves.toBeUndefined();

      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("Style Influence slider 注入を skip"),
        expect.any(Error),
      );
      warnSpy.mockRestore();
    });
  });

  describe("slider 注入失敗 → warn + skip (fail-soft, Suno bot 対策耐性)", () => {
    // 実機検証で Suno の slider が isTrusted=false の合成イベントを onKeyDown 内で弾くと判明。
    // dispatchEvent ベースの setSliderValue は原理的に動かず throw する。連続生成を止めると
    // ユーザー体験が大きく劣化するため、本層では throw を catch して warn + skip に吸収する。
    // (#973 で MAIN world bridge 経由の React onKeyDown 直接呼び出し経路を追加。本 describe は
    // bridge 不使用時の従来縮退を担保する)
    it("Given weirdness slider が反応しない When 注入 Then throw せず console.warn する", async () => {
      const weirdness = makeSlider(50, { respond: false });
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const pending = injectAdvancedFields({ weirdness: 30 }, { ...ALL_NULL, weirdness });
      await vi.advanceTimersByTimeAsync(2000);
      await expect(pending).resolves.toBeUndefined();

      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("Weirdness slider 注入を skip"), expect.any(Error));
      warnSpy.mockRestore();
    });

    it("Given weirdness slider が反応しない + onSliderSkip 有 When 注入 Then skip を通知する（#1720、観測可能性）", async () => {
      const weirdness = makeSlider(50, { respond: false });
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const onSliderSkip = vi.fn();

      const pending = injectAdvancedFields({ weirdness: 30 }, { ...ALL_NULL, weirdness }, { onSliderSkip });
      await vi.advanceTimersByTimeAsync(2000);
      await expect(pending).resolves.toBeUndefined();

      expect(onSliderSkip).toHaveBeenCalledWith("Weirdness");
      warnSpy.mockRestore();
    });

    it("Given style_influence slider が反応しない When 注入 Then throw せず console.warn する", async () => {
      const styleInfluence = makeSlider(50, { respond: false });
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const pending = injectAdvancedFields({ style_influence: 85 }, { ...ALL_NULL, styleInfluence });
      await vi.advanceTimersByTimeAsync(2000);
      await expect(pending).resolves.toBeUndefined();

      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("Style Influence slider 注入を skip"),
        expect.any(Error),
      );
      warnSpy.mockRestore();
    });

    it("Given weirdness 失敗 + style_influence 反応する When 注入 Then weirdness は skip、style_influence は注入する", async () => {
      // weirdness 失敗が後続 slider 投入を巻き込んで止めないことを担保（連続生成継続の必要条件）
      const weirdness = makeSlider(50, { respond: false });
      const styleInfluence = makeSlider(50);
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const pending = injectAdvancedFields(
        { weirdness: 30, style_influence: 85 },
        { ...ALL_NULL, weirdness, styleInfluence },
      );
      await vi.advanceTimersByTimeAsync(3000);
      await pending;

      expect(weirdness.getAttribute("aria-valuenow")).toBe("50");
      expect(styleInfluence.getAttribute("aria-valuenow")).toBe("85");
      expect(warnSpy).toHaveBeenCalledTimes(1);
      warnSpy.mockRestore();
    });

    it("Given exclude_styles + 両 slider 失敗 When 注入 Then exclude_styles は入る、両 slider は warn", async () => {
      const exclude = makeExcludeInput();
      const weirdness = makeSlider(50, { respond: false });
      const styleInfluence = makeSlider(50, { respond: false });
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const pending = injectAdvancedFields(
        { exclude_styles: "hyperpop", weirdness: 30, style_influence: 85 },
        { ...ALL_NULL, excludeStyles: exclude, weirdness, styleInfluence },
      );
      await vi.advanceTimersByTimeAsync(5000);
      await pending;

      expect(exclude.value).toBe("hyperpop");
      expect(weirdness.getAttribute("aria-valuenow")).toBe("50");
      expect(styleInfluence.getAttribute("aria-valuenow")).toBe("50");
      expect(warnSpy).toHaveBeenCalledTimes(2);
      warnSpy.mockRestore();
    });
  });

  describe("vocal_gender 注入 (Male / Female ボタン click)", () => {
    // 契約:
    //   - vocal_gender = "male" → fields.vocalGender.male.click() (data-selected=false の時のみ)
    //   - vocal_gender = "female" → fields.vocalGender.female.click() (data-selected=false の時のみ)
    //   - vocal_gender = "neutral" / "auto" → click しない (既選択を解除しない)
    //   - vocal_gender 未指定 → click しない (両方 null でも throw しない、fail-soft)
    //   - vocal_gender 値有 + 対応ボタン null → throw (fail-loud)

    it('Given vocal_gender="male" + Male 未選択 When 注入 Then Male.click() で data-selected=true、Female 不変', async () => {
      const { male, female } = makeVocalGenderPair();
      const maleClick = vi.spyOn(male, "click");
      const femaleClick = vi.spyOn(female, "click");
      // click を listen して data-selected トグルを再現（Suno UI を模す）
      male.addEventListener("click", () => male.setAttribute("data-selected", "true"));

      await injectAdvancedFields({ vocal_gender: "male" }, { ...ALL_NULL, vocalGender: { male, female } });

      expect(maleClick).toHaveBeenCalledTimes(1);
      expect(femaleClick).not.toHaveBeenCalled();
      expect(male.getAttribute("data-selected")).toBe("true");
      expect(female.getAttribute("data-selected")).toBe("false");
    });

    it('Given vocal_gender="male" + Male 既選択 When 注入 Then click せず冪等', async () => {
      const { male, female } = makeVocalGenderPair({ maleSelected: true });
      const maleClick = vi.spyOn(male, "click");
      const femaleClick = vi.spyOn(female, "click");

      await injectAdvancedFields({ vocal_gender: "male" }, { ...ALL_NULL, vocalGender: { male, female } });

      expect(maleClick).not.toHaveBeenCalled();
      expect(femaleClick).not.toHaveBeenCalled();
    });

    it('Given vocal_gender="female" + Female 未選択 When 注入 Then Female.click() のみ', async () => {
      const { male, female } = makeVocalGenderPair();
      const maleClick = vi.spyOn(male, "click");
      const femaleClick = vi.spyOn(female, "click");
      female.addEventListener("click", () => female.setAttribute("data-selected", "true"));

      await injectAdvancedFields({ vocal_gender: "female" }, { ...ALL_NULL, vocalGender: { male, female } });

      expect(femaleClick).toHaveBeenCalledTimes(1);
      expect(maleClick).not.toHaveBeenCalled();
      expect(female.getAttribute("data-selected")).toBe("true");
    });

    it('Given vocal_gender="neutral" + Male 既選択 When 注入 Then どちらも click せず既選択を保持', async () => {
      // "neutral" / "auto" は「Suno に任せる」解釈なので既選択を解除しない（拡張は触らない）。
      const { male, female } = makeVocalGenderPair({ maleSelected: true });
      const maleClick = vi.spyOn(male, "click");
      const femaleClick = vi.spyOn(female, "click");

      await injectAdvancedFields({ vocal_gender: "neutral" }, { ...ALL_NULL, vocalGender: { male, female } });

      expect(maleClick).not.toHaveBeenCalled();
      expect(femaleClick).not.toHaveBeenCalled();
      expect(male.getAttribute("data-selected")).toBe("true");
    });

    it('Given vocal_gender="auto" When 注入 Then どちらも click しない', async () => {
      const { male, female } = makeVocalGenderPair();
      const maleClick = vi.spyOn(male, "click");
      const femaleClick = vi.spyOn(female, "click");

      await injectAdvancedFields({ vocal_gender: "auto" }, { ...ALL_NULL, vocalGender: { male, female } });

      expect(maleClick).not.toHaveBeenCalled();
      expect(femaleClick).not.toHaveBeenCalled();
    });

    it('Given vocal_gender="male" + Male ボタン null When 注入 Then throw (fail-loud)', async () => {
      await expect(injectAdvancedFields({ vocal_gender: "male" }, ALL_NULL)).rejects.toThrow(
        /Vocal gender button \(male\)/,
      );
    });

    it("Given vocal_gender 未指定 + 両ボタン null When 注入 Then throw しない (fail-soft、後方互換)", async () => {
      await expect(injectAdvancedFields({}, ALL_NULL)).resolves.toBeUndefined();
    });

    it('Given exclude_styles + vocal_gender="male" 同時指定 When 注入 Then 両方適用される', async () => {
      const exclude = makeExcludeInput();
      const { male, female } = makeVocalGenderPair();
      const maleClick = vi.spyOn(male, "click");
      male.addEventListener("click", () => male.setAttribute("data-selected", "true"));

      await injectAdvancedFields(
        { exclude_styles: "hyperpop", vocal_gender: "male" },
        { ...ALL_NULL, excludeStyles: exclude, vocalGender: { male, female } },
      );

      expect(exclude.value).toBe("hyperpop");
      expect(maleClick).toHaveBeenCalledTimes(1);
      expect(male.getAttribute("data-selected")).toBe("true");
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
        { ...ALL_NULL, excludeStyles: exclude, weirdness, styleInfluence },
      );
      await vi.advanceTimersByTimeAsync(3000);
      await pending;

      expect(order).toEqual(["exclude", "weirdness", "style_influence"]);
    });
  });
});
