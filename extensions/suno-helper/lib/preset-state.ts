// 連続実行ペーシングの jitter 算出を集約する。
// 実行モード選択と chrome.storage.local の preset 永続化は #1573 で廃止済み。

/**
 * 基準待機 baseMs に ±jitterMs の振れを加える。
 * `baseMs + (random()*2-1)*jitterMs` で [base-jitter, base+jitter] に分布させる。
 * random は DI 可能（テストで min/max を pin する）。production の content からは省略呼び出しで Math.random を使う。
 */
export function applyJitter(baseMs: number, jitterMs: number, random: () => number = Math.random): number {
  return baseMs + (random() * 2 - 1) * jitterMs;
}
