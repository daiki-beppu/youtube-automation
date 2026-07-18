// @vitest-environment jsdom
//
// `shared/visibility.ts` の strict 可視判定テスト（#813）。
// `shared/dom.ts` に private で埋もれていた `isVisible` を切り出して export 化した module。
// distrokid-helper はこれを `../../shared/visibility` から import し、hidden 要素
// （例: type=hidden の #artistName）を注入対象から排除する（受け入れ基準）。
//
// 契約（draft が実装する前提）:
//   - isVisible(el): bbox 0 / display:none / visibility:hidden / opacity:0 を排除し、
//     自身〜祖先を walk して隠れていない場合のみ true。
//
// jsdom はレイアウトを行わず getBoundingClientRect() が常に全 0 を返すため、
// 可視要素には setRect で bbox を擬似付与する（production の strict isVisible は
// getBoundingClientRect の width/height と親要素の display/visibility/opacity を見る）。

import { beforeEach, describe, expect, it } from "vitest";

import { isVisible } from "../../shared/visibility";

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

function setRect(el: HTMLElement, rect: DOMRect): void {
  el.getBoundingClientRect = () => rect;
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("isVisible", () => {
  it("bbox 非 0 で隠しスタイルが無ければ true", () => {
    // Given
    const el = document.createElement("input");
    document.body.appendChild(el);
    setRect(el, VISIBLE_RECT);

    // Then
    expect(isVisible(el)).toBe(true);
  });

  it("bbox 0 の要素は false（type=hidden / 非マウント相当）", () => {
    // Given: 隠し入力（artistName のような type=hidden を想定）
    const el = document.createElement("input");
    el.type = "hidden";
    document.body.appendChild(el);
    setRect(el, ZERO_RECT);

    // Then
    expect(isVisible(el)).toBe(false);
  });

  it("自身が visibility:hidden なら false", () => {
    // Given
    const el = document.createElement("input");
    el.style.visibility = "hidden";
    document.body.appendChild(el);
    setRect(el, VISIBLE_RECT);

    // Then
    expect(isVisible(el)).toBe(false);
  });

  it("自身が opacity:0 なら false", () => {
    // Given
    const el = document.createElement("input");
    el.style.opacity = "0";
    document.body.appendChild(el);
    setRect(el, VISIBLE_RECT);

    // Then
    expect(isVisible(el)).toBe(false);
  });

  it("親が display:none なら祖先 walk で false（bbox は非 0 でも）", () => {
    // Given: 自身の bbox は可視だが親が display:none
    const wrapper = document.createElement("div");
    wrapper.style.display = "none";
    const el = document.createElement("input");
    wrapper.appendChild(el);
    document.body.appendChild(wrapper);
    setRect(el, VISIBLE_RECT);

    // Then
    expect(isVisible(el)).toBe(false);
  });
});
