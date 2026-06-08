// 1-click 自動再開 (#892 要件6) の range 構築ロジックの回帰テスト。
//
// 旧挙動: ResumeBanner「再開」は range UI を 1-based で prefill するだけで止まり、
//         ユーザーが「連続実行」を再押下して初めて生成が走り出した（2 操作）。
// 新挙動 (要件6): 「再開」1 クリックで run() まで自動実行する。React state は次レンダ反映で
//         closure から読めないため、acceptResume は 0-based inclusive な RunRange を
//         ローカルに構築して run({ range }) へ引数で渡す（order.md §2）。
//
// その「0-based RunRange 構築」を純関数 resumeRunRange へ抽出して tester surface とする
// （@testing-library/react 未導入のため、フック本体ではなく純関数で担保する＝既存 plan §6 の推奨）。
// 想定インターフェース（draft step で lib/resume-state.ts に追加すること。range SSOT に同居）:
//   export function resumeRunRange(banner: ResumeBanner): RunRange
//   // 失敗 entry (0-based failedIndex) から末尾 (total-1) まで。手動経路と同じ絶対 index を返す。
import { describe, expect, it } from "vitest";

import { resolveRunRange, resumeBannerRange, resumeRunRange } from "../lib/resume-state";
import type { ResumeBanner } from "../lib/resume-state";

function makeBanner(overrides: Partial<ResumeBanner> = {}): ResumeBanner {
  return { failedIndex: 19, total: 24, ...overrides };
}

describe("resumeRunRange: バナー承認 → 自動 run() に渡す 0-based inclusive range (要件6)", () => {
  it("Given failedIndex=19, total=24 When 構築 Then 0-based inclusive {19, 23}（失敗 entry〜末尾）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 19, total: 24 }))).toEqual({ start: 19, end: 23 });
  });

  it("Given failedIndex=0 (先頭で失敗), total=3 When 構築 Then {0, 2}（全域を再実行）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 0, total: 3 }))).toEqual({ start: 0, end: 2 });
  });

  it("Given failedIndex=total-1 (末尾で失敗), total=3 When 構築 Then 単一要素 {2, 2}", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 2, total: 3 }))).toEqual({ start: 2, end: 2 });
  });

  it("Given total=1 の単一 entry が先頭で失敗 When 構築 Then {0, 0}", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 0, total: 1 }))).toEqual({ start: 0, end: 0 });
  });
});

// 要件6 の核心契約: 1-click 自動再開（resumeRunRange を直接 run へ）と、
// 旧来の「prefill (resumeBannerRange) → run ボタン (resolveRunRange)」経路が
// 同一の絶対 index を生むこと。新経路が UI round-trip を飛ばしても挙動が一致する保証。
describe("整合性: 自動再開 range が prefill→手動 run 経路と同一 index になる (要件6)", () => {
  it("Given failedIndex=19/total=24 When 両経路で range 算出 Then 0-based {19,23} で一致する", () => {
    const banner = makeBanner({ failedIndex: 19, total: 24 });

    const auto = resumeRunRange(banner); // 1-click 経路: 直接 0-based
    const prefilled = resumeBannerRange(banner); // 旧経路: 1-based UI prefill
    const viaUi = resolveRunRange(prefilled.start, prefilled.end, banner.total); // 旧経路: run で 0-based 化

    expect(auto).toEqual(viaUi);
    expect(auto).toEqual({ start: 19, end: 23 });
  });

  it("Given failedIndex=0/total=3 When 両経路で range 算出 Then 一致する（先頭失敗の境界）", () => {
    const banner = makeBanner({ failedIndex: 0, total: 3 });

    const auto = resumeRunRange(banner);
    const prefilled = resumeBannerRange(banner);
    const viaUi = resolveRunRange(prefilled.start, prefilled.end, banner.total);

    expect(auto).toEqual(viaUi);
  });

  it("Given failedIndex=2/total=3 When 両経路で range 算出 Then 単一要素で一致する（末尾失敗の境界）", () => {
    const banner = makeBanner({ failedIndex: 2, total: 3 });

    const auto = resumeRunRange(banner);
    const prefilled = resumeBannerRange(banner);
    const viaUi = resolveRunRange(prefilled.start, prefilled.end, banner.total);

    expect(auto).toEqual(viaUi);
    expect(auto).toEqual({ start: 2, end: 2 });
  });
});
