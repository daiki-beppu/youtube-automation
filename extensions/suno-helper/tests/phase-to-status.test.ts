// phaseToStatus (#852) の回帰テスト。
//
// snapshot の直近 progress を popup の status 文字列へ変換する純関数。useSunoRunner の live
// handler が phase ごとに inline で組み立てていた文字列を SSOT 化し、content の snapshot 構築
// (live) と popup の再 open 復元 (restore) の双方が同一の文言を使えるようにする。
// 既存 live 文字列 (useSunoRunner.ts:90/93/96/102/106/110) を厳密に維持することを担保する。
import { describe, expect, it } from "vitest";

import { PHASE } from "../../shared/constants";
import type { ProgressPayload } from "../../shared/constants";
import { phaseToStatus } from "../components/runner-errors";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import { makePromptEntries, snapshotOptions } from "./_helpers";

/** 指定 progress を適用した snapshot を作る（phaseToStatus は progress / entries を読む）。 */
function snapWith(payload: ProgressPayload) {
  return applyProgress(initSnapshot(makePromptEntries(3), snapshotOptions()), payload);
}

/** snapshot を phaseToStatus の (progress, entries) 引数へ展開して呼ぶ。 */
function statusOf(payload: ProgressPayload) {
  const snap = snapWith(payload);
  return phaseToStatus(snap.progress, snap.entries);
}

describe("phaseToStatus: 非終了 phase の進捗文言（live と同一）", () => {
  it.each<[string, ProgressPayload, string]>([
    ["INJECTING", { phase: PHASE.INJECTING, index: 0, total: 3 }, "[1/3] 注入中: pattern-1"],
    ["WAITING_SLOT", { phase: PHASE.WAITING_SLOT, index: 1, total: 3 }, "[2/3] 生成キューの空き待ち…"],
    [
      "WAITING_CAPTCHA",
      { phase: PHASE.WAITING_CAPTCHA, index: 1, total: 3 },
      "[2/3] captcha 解消待ち…（多くは自動で解消します）",
    ],
    ["GENERATING", { phase: PHASE.GENERATING, index: 2, total: 3 }, "[3/3] 生成待ち…"],
    ["DONE", { phase: PHASE.DONE, index: 0, total: 3 }, "[1/3] 完了"],
  ])("Given phase=%s When phaseToStatus Then text=%j・error は falsy", (_label, payload, expected) => {
    const result = statusOf(payload);

    expect(result.text).toBe(expected);
    expect(result.error).toBeFalsy();
  });
});

describe("phaseToStatus: 終了 phase の文言と error フラグ", () => {
  it("Given FINISHED When phaseToStatus Then 完了文言・error は falsy", () => {
    const result = statusOf({ phase: PHASE.FINISHED, total: 3 });

    expect(result.text).toBe("完了: 3 パターンを実行しました。");
    expect(result.error).toBeFalsy();
  });

  it("Given STOPPED When phaseToStatus Then 停止文言・error=true", () => {
    const result = statusOf({ phase: PHASE.STOPPED, index: 0, total: 3 });

    expect(result.text).toBe("停止しました。手動で続行できます。");
    expect(result.error).toBe(true);
  });

  it("Given ERROR (message 付き) When phaseToStatus Then 中断文言に message を含み error=true", () => {
    const result = statusOf({ phase: PHASE.ERROR, index: 1, total: 3, message: "reCAPTCHA を検知しました。" });

    expect(result.text).toBe("中断: reCAPTCHA を検知しました。");
    expect(result.error).toBe(true);
  });

  it("Given ERROR (message 無し) When phaseToStatus Then message 部は空文字で握りつぶさず表示する", () => {
    const result = statusOf({ phase: PHASE.ERROR, index: 1, total: 3 });

    expect(result.text).toBe("中断: ");
    expect(result.error).toBe(true);
  });
});

describe("phaseToStatus: ADDING_TO_PLAYLIST の進捗文言 (#854)", () => {
  it("Given ADDING_TO_PLAYLIST (message=playlist 名) When phaseToStatus Then playlist 名入りの追加中文言・error は falsy", () => {
    // playlist 名は ProgressPayload.message で運ぶ（専用フィールドを足さず既存経路で表示する）。
    const result = statusOf({ phase: PHASE.ADDING_TO_PLAYLIST, total: 3, message: "rjn-dawn-cloud-fold" });

    expect(result.text).toBe("Playlist 'rjn-dawn-cloud-fold' へ追加中…");
    expect(result.error).toBeFalsy();
  });
});

describe("phaseToStatus: INJECTING の entry 名解決", () => {
  it("Given entries を持つ snap When INJECTING index=2 Then 対応する entry 名を文言に含める", () => {
    const result = statusOf({ phase: PHASE.INJECTING, index: 2, total: 3 });

    expect(result.text).toBe("[3/3] 注入中: pattern-3");
  });
});

describe("phaseToStatus: ENTRY_FAILED / 失敗付き FINISHED (#948)", () => {
  it("Given ENTRY_FAILED When 変換する Then スキップ文言を返し error フラグは立てない（run 継続中）", () => {
    const { text, error } = phaseToStatus(
      { phase: PHASE.ENTRY_FAILED, index: 2, total: 55, message: "生成キューの空き待ちが失敗" },
      [],
    );
    expect(text).toContain("[3/55]");
    expect(text).toContain("スキップ");
    expect(error).toBeFalsy();
  });

  it("Given message 付き FINISHED（失敗スキップあり） When 変換する Then 一部失敗を明示し error フラグを立てる", () => {
    const { text, error } = phaseToStatus(
      { phase: PHASE.FINISHED, total: 55, message: "2 件の entry が失敗しました (entry 3, 7)" },
      [],
    );
    expect(text).toContain("一部失敗");
    expect(text).toContain("entry 3, 7");
    expect(error).toBe(true);
  });

  it("Given message 無し FINISHED When 変換する Then 従来文言のまま（後方互換）", () => {
    const { text, error } = phaseToStatus({ phase: PHASE.FINISHED, total: 10 }, []);
    expect(text).toBe("完了: 10 パターンを実行しました。");
    expect(error).toBeFalsy();
  });
});
