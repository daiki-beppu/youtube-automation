// `lib/messaging.ts` の共有契約テスト。
//
// background ↔ popup ↔ content の型付けは @webext-core/messaging（chrome ランタイム必須）で行うため、
// 実送受信は Playwright 側に委ねる。ここでは 3 者が共有する PROGRESS フェーズ値の契約を固定する。
//
// 設計契約（draft が実装する前提）:
//   - PHASES: 注入の進捗を表す const（content -> popup の PROGRESS で使用）
//   - sendMessage / onMessage: @webext-core/messaging の型付き API を re-export

import { describe, it, expect } from "vitest";
import { PHASES, sendMessage, onMessage } from "../lib/messaging";
import type { InjectRequest } from "../lib/messaging";
import type { SerializedAsset } from "../lib/asset-transfer";

// #813 fallback-overuse 回帰防止（コンパイル時契約）:
// fetchAsset は取得失敗時に throw する（null を返さない）ため、trackAssets の要素は
// 常に SerializedAsset で欠落しない。`(SerializedAsset | null)[]` へ退行させると
// 下の代入が型エラーになり `pnpm compile`（tsc --noEmit）で検出される。
type TrackAssetElement = InjectRequest["trackAssets"][number];
const _trackAssetIsNonNull: SerializedAsset = {} as TrackAssetElement;
void _trackAssetIsNonNull;

describe("PHASES（PROGRESS フェーズ契約）", () => {
  it("注入フローのフェーズを過不足なく定義する", () => {
    // Given / When / Then: content と popup が解釈を共有するフェーズ集合
    expect(new Set(Object.keys(PHASES))).toEqual(
      new Set(["INJECTING", "DONE", "ERROR", "STOPPED"]),
    );
  });

  it("フェーズ値はすべて一意な文字列である", () => {
    // Given
    const values = Object.values(PHASES);

    // Then: 重複が無い（状態の正規化）
    expect(new Set(values).size).toBe(values.length);
    for (const value of values) {
      expect(typeof value).toBe("string");
    }
  });
});

describe("messaging API", () => {
  it("型付き sendMessage / onMessage を公開する", () => {
    // Then: popup/background/content から参照する送受信口が存在する
    expect(typeof sendMessage).toBe("function");
    expect(typeof onMessage).toBe("function");
  });
});
