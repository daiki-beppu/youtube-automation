// @vitest-environment jsdom
//
// MAIN world slider 注入ロジック (#973) の回帰テスト。
//
// Suno の slider は onKeyDown 内で isTrusted をチェックし合成 dispatchEvent を弾く。
// slider-bridge は React が DOM 要素に生やす `__reactProps$*` expando から onKeyDown を取得し、
// isTrusted: true の疑似イベントで直接呼び出してチェックを通過させる。
//
// テストでは「isTrusted=false を弾く React 風ハンドラ」を __reactProps$ 偽装で要素に付け、
//   - dispatchEvent では動かない（実機の再現）
//   - setSliderValueViaReact では動く（本修正の検証）
// の両方を確認する。
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  buildSyntheticKeydown,
  findReactKeyDownTarget,
  findSliderElement,
  setSliderValueViaReact,
} from "../lib/slider-bridge";

interface KeydownLike {
  key?: string;
  isTrusted?: boolean;
}

/**
 * Suno の slider を模す: __reactProps$ 偽装で onKeyDown を持ち、isTrusted=false のイベントを無視する。
 * opts.onElement に "self" / "parent" を指定して props の付与先を変えられる（祖先探索の検証用）。
 */
function makeReactSlider(
  value: number,
  opts: {
    rejectUntrusted?: boolean;
    propsOn?: "self" | "parent" | "none";
    handlerThrows?: boolean;
    ariaLabel?: string;
  } = {}
): HTMLElement {
  const parent = document.createElement("div");
  const slider = document.createElement("div");
  slider.setAttribute("role", "slider");
  slider.setAttribute("aria-valuenow", String(value));
  if (opts.ariaLabel) {
    slider.setAttribute("aria-label", opts.ariaLabel);
  }
  parent.appendChild(slider);
  document.body.appendChild(parent);

  const onKeyDown = (e: KeydownLike): void => {
    if (opts.handlerThrows) {
      throw new Error("handler error");
    }
    if (opts.rejectUntrusted !== false && e.isTrusted !== true) {
      return; // Suno の bot 検知を模す
    }
    const cur = Number(slider.getAttribute("aria-valuenow"));
    if (e.key === "ArrowRight")
      slider.setAttribute("aria-valuenow", String(cur + 1));
    else if (e.key === "ArrowLeft")
      slider.setAttribute("aria-valuenow", String(cur - 1));
  };

  const propsOn = opts.propsOn ?? "self";
  if (propsOn === "self") {
    (slider as unknown as Record<string, unknown>).__reactProps$abc123 = {
      onKeyDown,
    };
  } else if (propsOn === "parent") {
    (parent as unknown as Record<string, unknown>).__reactProps$abc123 = {
      onKeyDown,
    };
  }
  return slider;
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("findReactKeyDownTarget: __reactProps$ expando の探索", () => {
  it("Given 要素自身に props 有 When 探索 Then 自身を owner として返す", () => {
    const slider = makeReactSlider(50);
    const found = findReactKeyDownTarget(slider);
    expect(found).not.toBeNull();
    expect(found?.owner).toBe(slider);
  });

  it("Given 祖先に props 有 When 探索 Then 祖先を owner として返す", () => {
    const slider = makeReactSlider(50, { propsOn: "parent" });
    const found = findReactKeyDownTarget(slider);
    expect(found).not.toBeNull();
    expect(found?.owner).toBe(slider.parentElement);
  });

  it("Given props 無し (plain DOM = e2e mock) When 探索 Then null を返す", () => {
    const slider = makeReactSlider(50, { propsOn: "none" });
    expect(findReactKeyDownTarget(slider)).toBeNull();
  });

  it("Given props はあるが onKeyDown 無し When 探索 Then 祖先へ遡って探す", () => {
    const slider = makeReactSlider(50, { propsOn: "parent" });
    (slider as unknown as Record<string, unknown>).__reactProps$xyz = {
      onClick: () => {},
    };
    const found = findReactKeyDownTarget(slider);
    expect(found?.owner).toBe(slider.parentElement);
  });
});

describe("buildSyntheticKeydown: 疑似イベントの SyntheticEvent 互換性", () => {
  it("Given 生成した疑似イベント Then isTrusted=true で nativeEvent.isTrusted も true", () => {
    const el = document.createElement("div");
    const event = buildSyntheticKeydown("ArrowRight", el, el);
    expect(event.isTrusted).toBe(true);
    expect((event.nativeEvent as KeydownLike).isTrusted).toBe(true);
    expect(event.key).toBe("ArrowRight");
  });

  it("Given preventDefault 呼び出し Then defaultPrevented が true になる", () => {
    const el = document.createElement("div");
    const event = buildSyntheticKeydown("ArrowLeft", el, el);
    (event.preventDefault as () => void)();
    expect(event.defaultPrevented).toBe(true);
  });
});

describe("setSliderValueViaReact: React onKeyDown 直接呼び出しによる注入", () => {
  it("Given isTrusted チェック付き slider When dispatchEvent Then 動かない（実機の再現）", () => {
    const slider = makeReactSlider(50);
    // 合成イベントの dispatch では __reactProps$ のハンドラは呼ばれず、仮に呼ばれても isTrusted=false で弾かれる
    slider.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })
    );
    expect(slider.getAttribute("aria-valuenow")).toBe("50");
  });

  it("Given isTrusted チェック付き slider When setSliderValueViaReact(95) Then 95 まで動く", async () => {
    const slider = makeReactSlider(51);
    await expect(setSliderValueViaReact(slider, 95)).resolves.toBe(true);
    expect(slider.getAttribute("aria-valuenow")).toBe("95");
  });

  it("Given target < current When 注入 Then ArrowLeft 方向に動いて到達する", async () => {
    const slider = makeReactSlider(50);
    await expect(setSliderValueViaReact(slider, 45)).resolves.toBe(true);
    expect(slider.getAttribute("aria-valuenow")).toBe("45");
  });

  it("Given target === current When 注入 Then 何もせず true", async () => {
    const slider = makeReactSlider(50);
    await expect(setSliderValueViaReact(slider, 50)).resolves.toBe(true);
  });

  it("Given React props 無し (plain DOM) When 注入 Then false（合成イベント経路へ縮退）", async () => {
    const slider = makeReactSlider(50, { propsOn: "none" });
    await expect(setSliderValueViaReact(slider, 60)).resolves.toBe(false);
    expect(slider.getAttribute("aria-valuenow")).toBe("50");
  });

  it("Given ハンドラを呼んでも値が動かない When 注入 Then false（無限ループしない）", async () => {
    const slider = makeReactSlider(50);
    // ハンドラはあるが値を動かさないケース（UI 改装等）
    (slider as unknown as Record<string, unknown>).__reactProps$abc123 = {
      onKeyDown: () => {},
    };
    await expect(setSliderValueViaReact(slider, 60)).resolves.toBe(false);
  });

  it("Given ハンドラが throw する When 注入 Then false（fail-soft）", async () => {
    const slider = makeReactSlider(50, { handlerThrows: true });
    await expect(setSliderValueViaReact(slider, 60)).resolves.toBe(false);
  });

  it("Given aria-valuenow 不在 When 注入 Then false", async () => {
    const slider = makeReactSlider(50);
    slider.removeAttribute("aria-valuenow");
    await expect(setSliderValueViaReact(slider, 60)).resolves.toBe(false);
  });
});

/**
 * 実 React の再レンダー挙動を模す slider (#979)。
 * keydown のたびに「render 時点の値を捕捉した新しい closure」へ __reactProps$ の onKeyDown を
 * 差し替える。古い handler は捕捉済みの値を基準に再セットするだけなので、同じ handler を
 * 使い回すと 1 step 目以降は同じ値を上書きし続けて動かない（実機で確認した stale handler 問題）。
 */
function makeRerenderingReactSlider(value: number): HTMLElement {
  const slider = document.createElement("div");
  slider.setAttribute("role", "slider");
  slider.setAttribute("aria-valuenow", String(value));
  document.body.appendChild(slider);
  const render = (current: number): void => {
    const onKeyDown = (e: KeydownLike): void => {
      if (e.isTrusted !== true) {
        return;
      }
      const next =
        e.key === "ArrowRight"
          ? current + 1
          : e.key === "ArrowLeft"
            ? current - 1
            : current;
      slider.setAttribute("aria-valuenow", String(next));
      render(next); // setState → 再レンダー: props を新 closure に差し替え
    };
    (slider as unknown as Record<string, unknown>).__reactProps$abc123 = {
      onKeyDown,
    };
  };
  render(value);
  return slider;
}

describe("setSliderValueViaReact: 再レンダーで handler が差し替わる slider (#979)", () => {
  it("Given 捕捉した handler の使い回し When 連打 Then 1 step で止まる（バグの再現）", () => {
    const slider = makeRerenderingReactSlider(50);
    const stale = findReactKeyDownTarget(slider);
    expect(stale).not.toBeNull();
    for (let i = 0; i < 5; i++) {
      stale?.handler(buildSyntheticKeydown("ArrowLeft", stale.owner, slider));
    }
    // 古い closure は「50 を基準に 49 をセット」し続けるため 49 から動かない
    expect(slider.getAttribute("aria-valuenow")).toBe("49");
  });

  it("Given 毎 step 再取得する実装 When setSliderValueViaReact(10) Then 10 まで完走する", async () => {
    const slider = makeRerenderingReactSlider(50);
    await expect(setSliderValueViaReact(slider, 10)).resolves.toBe(true);
    expect(slider.getAttribute("aria-valuenow")).toBe("10");
  });

  it("Given 増加方向 When setSliderValueViaReact(55) Then ArrowRight で到達する", async () => {
    const slider = makeRerenderingReactSlider(50);
    await expect(setSliderValueViaReact(slider, 55)).resolves.toBe(true);
    expect(slider.getAttribute("aria-valuenow")).toBe("55");
  });
});

describe("findSliderElement: aria-label による slider 解決", () => {
  it("Given Style Influence slider 有 When 解決 Then 該当要素を返す", () => {
    makeReactSlider(50, { ariaLabel: "Weirdness" });
    const target = makeReactSlider(51, { ariaLabel: "Style Influence" });
    expect(findSliderElement("Style Influence")).toBe(target);
  });

  it("Given 該当 slider 無し When 解決 Then null を返す", () => {
    expect(findSliderElement("Style Influence")).toBeNull();
  });
});
