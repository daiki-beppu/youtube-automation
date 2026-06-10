// 拡張間で共有する strict 可視判定。
//
// `offsetParent !== null` だけでは display 以外で隠れた要素（visibility:hidden / opacity:0）や
// bbox 0 の非マウント要素を拾ってしまう。注入対象の解決時に type=hidden の隠し input
// （例: distrokid.com/new の #artistName）を排除するため、bbox と祖先 walk で厳密に判定する。

/**
 * strict 可視判定。bbox 0 を除外し、自身〜祖先を walk して
 * display:none / visibility:hidden / opacity:0 を排除する。
 */
export function isVisible(el: HTMLElement): boolean {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) {
    return false;
  }
  let node: Element | null = el;
  while (node) {
    const style = getComputedStyle(node);
    if (
      style.display === "none" ||
      style.visibility === "hidden" ||
      style.opacity === "0"
    ) {
      return false;
    }
    node = node.parentElement;
  }
  return true;
}
