// extractPlaylistName の契約テスト。
//
// collection ID + theme から Suno playlist 名 (`<channel> | <theme>`) を導出する純パーサ。
// pickInitialCollectionId と同種の fail-loud 純関数として shared/api.ts に同居する。
//
// 契約 (shared/api.ts):
//   - extractPlaylistName(collectionId: string, theme: string): string
//     1. theme が空文字なら throw
//     2. 末尾 `-collection` を剥がす（無ければそのまま）
//     3. 末尾が `-<theme>` で終わることを検証（不整合は fail-loud）
//     4. theme を剥がした残りを `-` で分割し、parts[0] が 8 桁日付 (^\d{8}$) かつ parts.length >= 2 を検証
//     5. 検証 NG は throw（fail-loud。silent に空文字や undefined を返さない）
//     6. OK なら `${parts.slice(1).join("-")} | ${theme}` を返す
//
// 例:
//   - ("20260601-rjn-dawn-cloud-fold-collection", "dawn-cloud-fold") -> "rjn | dawn-cloud-fold"
//   - ("20260520-soulful-grooves-midnight-mood-collection", "midnight-mood") -> "soulful-grooves | midnight-mood"
import { describe, expect, it } from "vitest";

import { extractPlaylistName } from "../../shared/api";

describe("extractPlaylistName: 正常系（<channel> | <theme> 形式で導出）", () => {
  it("Given 単一 word channel + 複数 word theme When 抽出する Then `rjn | dawn-cloud-fold` を返す", () => {
    expect(
      extractPlaylistName(
        "20260601-rjn-dawn-cloud-fold-collection",
        "dawn-cloud-fold"
      )
    ).toBe("rjn | dawn-cloud-fold");
  });

  it("Given 複数 word channel (soulful-grooves) + 複数 word theme When 抽出する Then channel もハイフン保持して `|` で分離する", () => {
    expect(
      extractPlaylistName(
        "20260520-soulful-grooves-midnight-mood-collection",
        "midnight-mood"
      )
    ).toBe("soulful-grooves | midnight-mood");
  });

  it("Given `-collection` 無しの id When 抽出する Then 接尾辞剥がし無しで同じ結果を返す", () => {
    expect(
      extractPlaylistName("20260601-rjn-dawn-cloud-fold", "dawn-cloud-fold")
    ).toBe("rjn | dawn-cloud-fold");
  });

  it("Given 1 word theme + 1 word channel When 抽出する Then `rjn | dawn` を返す（境界値）", () => {
    expect(extractPlaylistName("20260601-rjn-dawn", "dawn")).toBe("rjn | dawn");
  });
});

describe("extractPlaylistName: 異常系（fail-loud で throw）", () => {
  it("Given 空の theme When 抽出する Then throw する", () => {
    expect(() =>
      extractPlaylistName("20260601-rjn-dawn-cloud-fold-collection", "")
    ).toThrow();
  });

  it("Given id が theme と不整合 When 抽出する Then throw する（末尾照合失敗）", () => {
    // theme が "dawn-cloud-fold" のはずなのに id 末尾が "wrong-theme" 系
    expect(() =>
      extractPlaylistName(
        "20260601-rjn-other-theme-collection",
        "dawn-cloud-fold"
      )
    ).toThrow(/theme と collection id/);
  });

  it("Given 先頭が 8 桁日付でない id When 抽出する Then throw する（日付なし）", () => {
    expect(() =>
      extractPlaylistName("rjn-dawn-cloud-fold-collection", "dawn-cloud-fold")
    ).toThrow();
  });

  it("Given theme 剥がし後に channel が空 When 抽出する Then throw する", () => {
    // `-collection` 剥がし → `20260601-dawn-cloud-fold`、theme `dawn-cloud-fold` 剥がし → `20260601`
    // → parts = ["20260601"]、parts.length < 2 で throw
    expect(() =>
      extractPlaylistName(
        "20260601-dawn-cloud-fold-collection",
        "dawn-cloud-fold"
      )
    ).toThrow();
  });

  it("Given 日付が 8 桁でない (7 桁) id When 抽出する Then throw する（境界の桁数厳密）", () => {
    expect(() =>
      extractPlaylistName("2026060-rjn-dawn-cloud", "dawn-cloud")
    ).toThrow();
  });

  it("Given 日付に英字混入の id When 抽出する Then throw する（^\\d{8}$ の数値限定）", () => {
    expect(() =>
      extractPlaylistName("2026060a-rjn-dawn-cloud", "dawn-cloud")
    ).toThrow();
  });

  it("Given throw 時 When メッセージを読む Then 不正な collection id を握りつぶさず含める", () => {
    expect(() => extractPlaylistName("bad-id", "theme")).toThrow(/bad-id/);
  });
});
