// extractPlaylistName (#854) の契約テスト。
//
// collection ID から Suno playlist 名 (`<channel>-<theme>`) を導出する純パーサ。
// pickInitialCollectionId と同種の fail-loud 純関数として shared/api.ts に同居する。
//
// 契約 (draft が実装すべき public API、shared/api.ts):
//   - extractPlaylistName(collectionId: string): string
//     1. 末尾 `-collection` を剥がす（無ければそのまま）
//     2. `-` で分割し parts[0] が 8 桁日付 (^\d{8}$) かつ parts.length >= 3 を検証
//     3. 検証 NG は throw（fail-loud。silent に空文字や undefined を返さない）
//     4. OK なら parts.slice(1).join("-")（= 日付を除いた <channel>-<theme>）を返す
//
// 例: 20260601-rjn-dawn-cloud-fold-collection -> rjn-dawn-cloud-fold
import { describe, expect, it } from "vitest";

import { extractPlaylistName } from "../../shared/api";

describe("extractPlaylistName: 正常系（collection ID から playlist 名を導出）", () => {
  it("Given `-collection` 付き id When 抽出する Then 日付を除いた <channel>-<theme> を返す", () => {
    expect(extractPlaylistName("20260601-rjn-dawn-cloud-fold-collection")).toBe("rjn-dawn-cloud-fold");
  });

  it("Given 複数ハイフンのテーマ (soulful-grooves) When 抽出する Then 残りを `-` で連結して返す", () => {
    expect(extractPlaylistName("20260520-clm-soulful-grooves-collection")).toBe("clm-soulful-grooves");
  });

  it("Given `-collection` 無しの id When 抽出する Then 接尾辞剥がし無しで同じ結果を返す", () => {
    // 接尾辞剥がしは endsWith ガード付き。`-collection` が無くても日付 + parts 検証だけで通る。
    expect(extractPlaylistName("20260601-rjn-dawn-cloud-fold")).toBe("rjn-dawn-cloud-fold");
  });

  it("Given ちょうど 3 parts (date-channel-theme) When 抽出する Then <channel>-<theme> を返す（境界値）", () => {
    expect(extractPlaylistName("20260601-rjn-dawn")).toBe("rjn-dawn");
  });
});

describe("extractPlaylistName: 異常系（fail-loud で throw）", () => {
  it("Given 先頭が 8 桁日付でない id When 抽出する Then throw する（日付なし）", () => {
    expect(() => extractPlaylistName("rjn-dawn-cloud-fold-collection")).toThrow();
  });

  it("Given parts が 3 未満の id When 抽出する Then throw する（theme 欠落）", () => {
    // `-collection` 剥がし後 `20260601-rjn` は parts 2 個 < 3 → 不正フォーマット。
    expect(() => extractPlaylistName("20260601-rjn-collection")).toThrow();
  });

  it("Given 日付が 8 桁でない (7 桁) id When 抽出する Then throw する（境界の桁数厳密）", () => {
    expect(() => extractPlaylistName("2026060-rjn-dawn-cloud")).toThrow();
  });

  it("Given 日付に英字混入の id When 抽出する Then throw する（^\\d{8}$ の数値限定）", () => {
    expect(() => extractPlaylistName("2026060a-rjn-dawn-cloud")).toThrow();
  });

  it("Given throw 時 When メッセージを読む Then 不正な collection id を握りつぶさず含める", () => {
    expect(() => extractPlaylistName("bad-id")).toThrow(/bad-id/);
  });
});
