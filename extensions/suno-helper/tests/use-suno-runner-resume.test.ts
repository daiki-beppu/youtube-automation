// 1-click 自動再開 (#892 要件6) の range 構築ロジックの回帰テスト。
//
// 現行挙動 (要件6): 「再開」1 クリックで run() まで自動実行する。React state は次レンダ反映で
//         closure から読めないため、acceptResume は 0-based inclusive な RunRange を
//         ローカルに構築して run({ range }) へ引数で渡す（order.md §2）。
//
// その「0-based RunRange 構築」を純関数 resumeRunRange へ抽出して tester surface とする
// （@testing-library/react 未導入のため、フック本体ではなく純関数で担保する＝既存 plan §6 の推奨）。
//   export function resumeRunRange(banner: ResumeBanner): RunRange
//   // 失敗 entry (0-based failedIndex) から末尾 (total-1) までの絶対 index を返す。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { resumeRunRange } from "../lib/resume-state";
import type { ResumeBanner } from "../lib/resume-state";
import {
  buildFailedEntriesRunOverrides,
  buildResumeRunOverrides,
  buildRunPayload,
  buildSelectedEntriesRunOverrides,
} from "../lib/run-overrides";

function makeBanner(overrides: Partial<ResumeBanner> = {}): ResumeBanner {
  return { failedIndex: 19, total: 24, ...overrides };
}

const read = (rel: string): string =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");

describe("resumeRunRange: バナー承認 → 自動 run() に渡す 0-based inclusive range (要件6)", () => {
  it("Given failedIndex=19, total=24 When 構築 Then 0-based inclusive {19, 23}（失敗 entry〜末尾）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 19, total: 24 }))).toEqual({
      start: 19,
      end: 23,
    });
  });

  it("Given failedIndex=0 (先頭で失敗), total=3 When 構築 Then {0, 2}（全域を再実行）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 0, total: 3 }))).toEqual({
      start: 0,
      end: 2,
    });
  });

  it("Given failedIndex=total-1 (末尾で失敗), total=3 When 構築 Then 単一要素 {2, 2}", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 2, total: 3 }))).toEqual({
      start: 2,
      end: 2,
    });
  });

  it("Given total=1 の単一 entry が先頭で失敗 When 構築 Then {0, 0}", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 0, total: 1 }))).toEqual({
      start: 0,
      end: 0,
    });
  });
});

// #898: playlist phase で STOPPED したときは entry が全件 done のため、保存する failedIndex は
// `total`（最終 entry の次）になる（plan 7b）。その値で再開すると entry ループは空回しし、
// playlist 追加のみが再実行される。resumeRunRange は無改修でこの境界を扱う（要件6）ことを担保する。
describe("resumeRunRange: playlist phase 停止 (failedIndex=total) は空 entry range を返す (#898 要件6/7b)", () => {
  it("Given failedIndex=total=8 (全 entry done 後の playlist 停止) When 構築 Then {8, 7}（start>end の空 entry range）", () => {
    // start(8) > end(7) なので runAll の for ループは 1 度も回らず、playlist phase だけが再実行される。
    expect(resumeRunRange(makeBanner({ failedIndex: 8, total: 8 }))).toEqual({
      start: 8,
      end: 7,
    });
  });

  it("Given failedIndex=total=1 (単一 entry 完了後の playlist 停止) When 構築 Then {1, 0}（空 entry range）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 1, total: 1 }))).toEqual({
      start: 1,
      end: 0,
    });
  });

  it("Given playlist 停止の failedIndex=total When start と end を比べる Then start > end（entry を 1 件も再生成しない）", () => {
    const range = resumeRunRange(makeBanner({ failedIndex: 5, total: 5 }));

    expect(range.start).toBeGreaterThan(range.end);
  });
});

// #898: runAll は defineContentScript 内の closure で export を持たず unit import できないため、
// content.ts をソーステキストとして読み、STOPPED 箇所すべてで resume save が走る構造を機械担保する
// （ssot-dedup.test.ts の read() 手法を雛形）。実装前は失敗し、draft step の実装後に pass する。
describe("content.ts: STOPPED phase は resume state を保存する (#898 要件1/2/3/7)", () => {
  const contentSource = read("../entrypoints/content.ts");
  const downloadFlowSource = read("../lib/download-flow.ts");
  const queueRunnerSource = read("../lib/queue-runner.ts");
  const runnerSources = `${contentSource}\n${downloadFlowSource}\n${queueRunnerSource}`;

  it("Given runner sources When PHASE.STOPPED emit を数える Then 正確に 18 箇所（定期実行の安全停止 checkpoint を含む）", () => {
    const stoppedEmits =
      runnerSources.match(
        /(?:emitProgress|deps\.emitProgress|options\.emitProgress)\(\{\s*phase: PHASE\.STOPPED/g
      ) ?? [];

    expect(stoppedEmits).toHaveLength(18);
  });

  it("Given ループ内 STOPPED のうち未 click 箇所 When 直前を読む Then persistInterruptState(i) が隣接する（serial / queue ループ先頭の 2 箇所）", () => {
    // attempt 中（waitForQueueSlot / injectEntryAndClickGenerate）の中断は entry-retry の outcome=aborted で
    // 一元処理され、resolveInterruptIndex で補正した interruptIndex を使う（未 click なら i と等価）。
    const contentLoopStops =
      contentSource.match(
        /persistInterruptState\(i, orderPosition\);\s*emitProgress\(\{\s*phase: PHASE\.STOPPED,\s*index: i,\s*total,?\s*\}\)/g
      ) ?? [];
    const queueLoopStops =
      queueRunnerSource.match(
        /options\.persistInterruptState\(index, orderPosition\);\s*options\.emitProgress\(\{\s*phase: PHASE\.STOPPED,\s*index,\s*total: options\.total,?\s*\}\)/g
      ) ?? [];

    expect([...contentLoopStops, ...queueLoopStops]).toHaveLength(2);
  });

  it("Given injectWithVerification 後の STOPPED 4 箇所 When 直前を読む Then resolveInterruptIndex で補正した interruptIndex を使う (#924/#1268/#1586)", () => {
    // Generate click 済みの場合は重複を防ぐため interruptIndex = i+1 に補正して persist / emit する。
    // #1268 で duration guard の完了待ち / 評価後の中断経路が同じ補正パターンを使う。
    const contentPostInjectStops =
      contentSource.match(
        /persistInterruptState\(interruptIndex, orderPosition\);\s*emitProgress\(\{\s*phase: PHASE\.STOPPED,\s*index: interruptIndex,\s*total,?\s*\}\)/g
      ) ?? [];
    const queuePostInjectStops =
      queueRunnerSource.match(
        /options\.persistInterruptState\(interruptIndex, orderPosition\);\s*options\.emitProgress\(\{\s*phase: PHASE\.STOPPED,\s*index: interruptIndex,\s*total: options\.total,?\s*\}\)/g
      ) ?? [];

    expect([...contentPostInjectStops, ...queuePostInjectStops]).toHaveLength(
      4
    );
  });

  it("Given playlist / download phase STOPPED 4 箇所 When 直前を読む Then persistInterruptState(total) が隣接する（全 entry done 後 + 最終生成完了待ち + download 中断）", () => {
    const playlistStops =
      contentSource.match(
        /persistInterruptState\(total\);\s*emitProgress\(\{ phase: PHASE\.STOPPED, total \}\)/g
      ) ?? [];

    expect(playlistStops).toHaveLength(4);
  });

  it("Given persistInterruptState 定義 When 中身を読む Then failedIndex/total/timestamp を writeResumeState する（要件1/3）", () => {
    // failedIndex 名を rename せず流用すること（要件3）。引数 interruptedIndex を failedIndex に載せる。
    // ERROR / STOPPED 両 phase 共通ヘルパー（dry-duplication 解消, AI-898-001）。
    expect(contentSource).toMatch(
      /function persistInterruptState\([\s\S]*?interruptedIndex: number,[\s\S]*?orderPosition\?: number,[\s\S]*?explicitRemainingIndices\?: number\[\],?[\s\S]*?\): void \{[\s\S]*?resumeStateWrite = resumeStateWrite[\s\S]*?\.then\(\(\) =>[\s\S]*?writeResumeState\(\{\s*collectionId,\s*failedIndex: interruptedIndex,\s*total,\s*timestamp: Date\.now\(\),/
    );
  });
});

// #898: 既存 ERROR / FINISHED 経路の resume 挙動を STOPPED 追加で壊さないこと（要件4/5）を機械担保する。
// この 2 件は実装前後どちらでも pass する（不変経路の回帰検出器）。
describe("content.ts: 既存 ERROR / FINISHED の resume 挙動は回帰しない (#898 要件4/5)", () => {
  const contentSource = read("../entrypoints/content.ts");

  it("Given ERROR phase When 読む Then resolveInterruptIndex で補正した interruptIndex で emit・persist する (#924)", () => {
    // #924 修正: ERROR catch は resolveInterruptIndex(i, submitted, isNotAcknowledged) で interruptIndex を決め、
    // emitProgress・persistInterruptState の両方に interruptIndex を渡す（両系統の failedIndex を一致させる）。
    expect(contentSource).toMatch(
      /emitProgress\(\{\s*phase: PHASE\.ERROR,\s*index: interruptIndex,\s*total,\s*message,?\s*\}\);[\s\S]*?persistInterruptState\(interruptIndex, orderPosition\);/
    );
  });

  it("Given FINISHED phase When 読む Then clearResumeStateForCollection で resume state を消す（要件5）", () => {
    // #1411: 完了時リロードの前に消去完了を保証するため void → await（fire-and-forget だと
    // リロード後の ResumeBanner が「中断からの再開」と誤判定しうる）。
    expect(contentSource).toMatch(
      /await clearResumeStateForCollection\(collectionId\);[\s\S]*?emitProgress\(\{ phase: PHASE\.FINISHED, total \}\)/
    );
  });
});

describe("submitted clip ID resume wiring: failed-only rerun / playlist-only resume (#1183)", () => {
  const contentSource = read("../entrypoints/content.ts");
  const runnerSource = read("../components/useSunoRunner.ts");

  it("Given failed-only rerun の入力 When payload を構築する Then indices と保存済み playlist 情報が同じ戻り値に入る", () => {
    const overrides = buildFailedEntriesRunOverrides([2, 7], {
      submittedClipIds: ["clip-a", "clip-b"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });

    expect(overrides).toEqual({
      indices: [2, 7],
      submittedClipIds: ["clip-a", "clip-b"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });
  });

  it("Given playlist-only resume の入力 When payload を構築する Then range と保存済み playlist 情報が同じ戻り値に入る", () => {
    const banner = makeBanner({ failedIndex: 4, total: 4 });
    const overrides = buildResumeRunOverrides(banner, {
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 4,
    });

    expect(overrides).toEqual({
      range: { start: 4, end: 3 },
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 4,
    });
  });

  it("Given resume overrides When run 送信用 payload を構築する Then entries/range と playlist resume fields が同じ戻り値に入る", () => {
    const entries = [
      { name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" },
    ];
    const overrides = buildResumeRunOverrides(
      makeBanner({ failedIndex: 1, total: 3 }),
      {
        submittedClipIds: ["clip-a", "clip-b"],
        submittedClipIdsAreDurationFiltered: true,
        playlistExpectedClipCount: 2,
      }
    );

    const payload = buildRunPayload({
      entries,
      playlistName: "target-playlist",
      range: overrides.range,
      collectionId: "collection-a",
      runMode: "queue",
      regenerateDurationOutliers: true,
      overrides,
    });

    expect(payload).toEqual({
      entries,
      playlistName: "target-playlist",
      range: { start: 1, end: 2 },
      collectionId: "collection-a",
      runMode: "queue",
      regenerateDurationOutliers: true,
      indices: undefined,
      submittedClipIds: ["clip-a", "clip-b"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });
  });

  it("Given indices 部分実行の resume state When payload を構築する Then range ではなく残り indices を渡す", () => {
    const overrides = buildResumeRunOverrides(
      makeBanner({ failedIndex: 2, total: 5, remainingIndices: [2, 4] }),
      {
        submittedClipIds: ["clip-a", "clip-b"],
        submittedClipIdsAreDurationFiltered: true,
        playlistExpectedClipCount: 6,
      }
    );

    expect(overrides).toEqual({
      indices: [2, 4],
      submittedClipIds: ["clip-a", "clip-b"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 6,
    });
  });

  it("Given failed-only overrides When run 送信用 payload を構築する Then indices と playlist resume fields が同じ戻り値に入る", () => {
    const entries = [
      { name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" },
    ];
    const overrides = buildFailedEntriesRunOverrides([0, 2], {
      submittedClipIds: ["clip-a", "clip-c"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });

    const payload = buildRunPayload({
      entries,
      playlistName: "target-playlist",
      range: undefined,
      collectionId: "collection-a",
      runMode: "serial",
      regenerateDurationOutliers: true,
      overrides,
    });

    expect(payload).toEqual({
      entries,
      playlistName: "target-playlist",
      range: undefined,
      collectionId: "collection-a",
      runMode: "serial",
      regenerateDurationOutliers: true,
      indices: [0, 2],
      submittedClipIds: ["clip-a", "clip-c"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });
  });

  it("Given 全 entry が選択済み When selection overrides を構築する Then indices を省略して全実行扱いにする", () => {
    expect(
      buildSelectedEntriesRunOverrides({
        selectedEntries: [true, true, true],
        itemStates: ["idle", "idle", "idle"],
        entryCount: 3,
      })
    ).toBeUndefined();
  });

  it("Given 一部 entry が未選択 When selection overrides を構築する Then 選択済み 0-based indices を返す", () => {
    expect(
      buildSelectedEntriesRunOverrides({
        selectedEntries: [true, false, true, false],
        itemStates: ["idle", "idle", "idle", "idle"],
        entryCount: 4,
      })
    ).toEqual({ indices: [0, 2] });
  });

  it("Given selection が未初期化で done entry がある When selection overrides を構築する Then done 以外を既定選択にする", () => {
    expect(
      buildSelectedEntriesRunOverrides({
        selectedEntries: [],
        itemStates: ["idle", "done", "failed"],
        entryCount: 3,
      })
    ).toEqual({ indices: [0, 2] });
  });

  it("Given 全 entry が未選択 When selection overrides を構築する Then 空 indices を送らず fail-loud にする", () => {
    expect(() =>
      buildSelectedEntriesRunOverrides({
        selectedEntries: [false, false, false],
        itemStates: ["idle", "idle", "idle"],
        entryCount: 3,
      })
    ).toThrow("実行対象が選択されていません。");
  });

  it("Given durationFilter When run 送信用 payload を構築する Then payload に保持する", () => {
    const entries = [
      { name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" },
    ];

    const payload = buildRunPayload({
      entries,
      playlistName: "target-playlist",
      durationFilter: { min_sec: 75, max_sec: 240 },
      range: undefined,
      collectionId: "collection-a",
      runMode: "queue",
      overrides: undefined,
    });

    expect(payload).toMatchObject({
      entries,
      playlistName: "target-playlist",
      durationFilter: { min_sec: 75, max_sec: 240 },
      collectionId: "collection-a",
      runMode: "queue",
    });
  });

  it("Given 異常値再生成 option When payload を構築する Then default ON と override OFF が効く", () => {
    const base = {
      entries: [
        { name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" },
      ],
      playlistName: "target-playlist",
      range: undefined,
      collectionId: "collection-a",
      runMode: "serial" as const,
    };

    expect(
      buildRunPayload({ ...base, overrides: undefined })
        .regenerateDurationOutliers
    ).toBe(true);
    expect(
      buildRunPayload({
        ...base,
        regenerateDurationOutliers: true,
        overrides: { regenerateDurationOutliers: false },
      }).regenerateDurationOutliers
    ).toBe(false);
  });

  it("Given run mode state When useSunoRunner を読む Then run 送信用 payload へ投入方式を渡す", () => {
    expect(runnerSource).toMatch(
      /const \[runModeId, setRunModeId\] = useState<RunModeId>\(DEFAULT_RUN_MODE_ID\)/
    );
    // 読込失敗は既定 serial のまま warn fallback（unhandled rejection にしない）。
    expect(runnerSource).toMatch(
      /void readRunModeId\(\)\s*\.then\(setRunModeId\)\s*\.catch\(/
    );
    expect(runnerSource).toMatch(/runMode: runModeId/);
  });

  it("Given 中断 run の投入方式 When 再開・失敗分再実行する Then popup の現在選択ではなく resume state の runMode を引き継ぐ (#1586)", () => {
    expect(runnerSource).toMatch(/return persistedResume\.runMode;/);
    expect(runnerSource).toMatch(
      /\.\.\.buildResumeRunOverrides\(resumeBanner, \{[\s\S]*?\}\),\s*runMode: runModeForResume,/
    );
    expect(runnerSource).toMatch(
      /\.\.\.buildFailedEntriesRunOverrides\(failedEntries, \{[\s\S]*?\}\),\s*runMode: runModeForResume,/
    );
  });

  it("Given 旧 ResumeState に期待件数が無い When useSunoRunner を読む Then total から期待件数を復元して渡す", () => {
    expect(runnerSource).toMatch(
      /resolvePlaylistExpectedClipCountForResume\(\s*persistedResume\.playlistExpectedClipCount,\s*persistedResume\.total,?\s*\)/
    );
  });

  it("Given content run start When data payload を読む Then playlist resume 情報を runAll に渡す", () => {
    expect(contentSource).toMatch(
      /const \{[\s\S]*?entries,[\s\S]*?playlistName,[\s\S]*?durationFilter,[\s\S]*?range,[\s\S]*?collectionId,[\s\S]*?indices,[\s\S]*?submittedClipIds,[\s\S]*?playlistExpectedClipCount,[\s\S]*?\} = assertRunPayload\(data\);[\s\S]*?void runAll\(entries, \{[\s\S]*?durationFilter,[\s\S]*?submittedClipIds,[\s\S]*?playlistExpectedClipCount,[\s\S]*?\}\)/
    );
  });

  it("Given playlist phase When content.ts を読む Then 保存済み ID と今回観測 ID を resolvePlaylistClipIds で合成してから scrollAndMultiSelectByIds で row 解決する", () => {
    expect(contentSource).toMatch(
      /const rawSubmittedIds = resolvePlaylistClipIds\(\s*previousSubmittedClipIds,\s*currentSubmittedIds,\s*expectedClipCount,?\s*\);[\s\S]*?const plan = buildPlaylistClipPlan\([\s\S]*?scrollAndMultiSelectByIds\(plan\.clipIds,/
    );
    expect(contentSource).toMatch(
      /verifiedPlaylistClipCount = await addClipsToPlaylist\([\s\S]*?previousSubmittedClipIds,[\s\S]*?playlistTargetClipCount,[\s\S]*?entries,/
    );
  });

  it("Given resume / failed-only rerun When content.ts を読む Then raw 合成期待数は保存済み OK 件数と別計算にする", () => {
    expect(contentSource).toMatch(
      /const expectedRawPlaylistClipCount =[\s\S]*?order\.length === 0[\s\S]*?\? \(playlistExpectedClipCount \?\? total \* CLIPS_PER_REQUEST\)[\s\S]*?: new Set\(previousSubmittedClipIds\)\.size \+\s*order\.length \* CLIPS_PER_REQUEST;/
    );
    expect(contentSource).toMatch(
      /const shouldRunDownloadAfterPlaylist =\s*expectedRawPlaylistClipCount >= total \* CLIPS_PER_REQUEST;/
    );
  });

  it("Given queue mode When content.ts を読む Then playlist 期待数は queue mapping から解決して渡す", () => {
    expect(contentSource).toMatch(
      /const expectedPlaylistClipCount =[\s\S]*?options\.runMode === "queue" && queueClipIdsByEntry !== null[\s\S]*?\? countQueuePlaylistClipIds\(\s*previousSubmittedClipIds,\s*queueClipIdsByEntry,?\s*\)[\s\S]*?: expectedRawPlaylistClipCount;/
    );
  });

  it("Given resume state persist When content.ts を読む Then queue は raw ID を保持し playlist 後は OK clip 情報で上書きできる", () => {
    expect(contentSource).toMatch(
      /const currentSubmittedIds = tracker\.getSubmittedIds\(\);[\s\S]*?const fallbackPlaylistPersistInfo =[\s\S]*?options\.runMode === "queue"[\s\S]*?\? resolveRawPlaylistPersistInfo\(\s*previousSubmittedClipIds,\s*currentSubmittedIds,?\s*\)[\s\S]*?: resolvePlaylistPersistInfo\([\s\S]*?previousSubmittedClipIds,[\s\S]*?currentSubmittedIds,[\s\S]*?options\.durationFilter,[\s\S]*?options\.submittedClipIdsAreDurationFiltered === true,?[\s\S]*?\);[\s\S]*?const playlistSubmittedClipIds =[\s\S]*?playlistPersistInfo\?\.submittedClipIds \?\?\s*fallbackPlaylistPersistInfo\.submittedClipIds;[\s\S]*?const submittedClipIdsAreDurationFiltered =[\s\S]*?playlistPersistInfo\?\.submittedClipIdsAreDurationFiltered \?\?[\s\S]*?fallbackPlaylistPersistInfo\.submittedClipIdsAreDurationFiltered;[\s\S]*?const playlistExpectedCount =[\s\S]*?playlistPersistInfo\?\.playlistExpectedClipCount \?\?\s*fallbackPlaylistPersistInfo\.playlistExpectedClipCount;[\s\S]*?submittedClipIds: playlistSubmittedClipIds,[\s\S]*?submittedClipIdsAreDurationFiltered,[\s\S]*?playlistExpectedClipCount: playlistExpectedCount,/
    );
  });

  it("Given playlist error persist When content.ts を読む Then snapshot に failedIndex も保持する", () => {
    expect(contentSource).toMatch(
      /currentSnapshot =[\s\S]*?\{\s*\.\.\.currentSnapshot,\s*failedIndex: interruptedIndex,[\s\S]*?submittedClipIds: playlistSubmittedClipIds,[\s\S]*?playlistExpectedClipCount: playlistExpectedCount,/
    );
  });

  it("Given playlist error When content.ts を読む Then ERROR progress に index=total を載せる", () => {
    expect(contentSource).toMatch(
      /emitProgress\(\{ phase: PHASE\.ERROR, index: total, total, message \}\);/
    );
  });

  it("Given playlist-only resume cannot resolve playlistName When useSunoRunner を読む Then silent return せず UI にエラーを出す", () => {
    expect(runnerSource).toMatch(
      /if \(!playlistName\) \{[\s\S]*?report\(\s*"playlist 名を解決できないため、playlist 追加を再開できません。コレクションを選択し直してください。",\s*true,?\s*\);[\s\S]*?return;/
    );
  });

  it("Given OK clip 数が full collection 件数より少ない When retryPlaylist を読む Then shouldDownload は resume 完走状態で判定する", () => {
    expect(runnerSource).toMatch(
      /const shouldDownload =\s*resumeBanner !== null &&\s*resumeBanner\.failedIndex >= resumeBanner\.total &&\s*!resumeBanner\.remainingIndices\?\.length;/
    );
    expect(runnerSource).not.toMatch(
      /expectedClipCount >= fullCollectionClipCount/
    );
  });

  it("Given playlist-only resume When retryPlaylist を読む Then durationFilter と正規化済み ID 契約を payload に載せる", () => {
    expect(runnerSource).toMatch(
      /sendMessage\("retryPlaylist", \{[\s\S]*?durationFilter: durationFilterForResume,[\s\S]*?submittedClipIdsAreDurationFiltered:\s*submittedClipIdsAreDurationFilteredForResume,[\s\S]*?shouldDownload,[\s\S]*?\}\)/
    );
  });

  it("Given 手動採用 When useSunoRunner を読む Then 未検証 ID として保存し retryPlaylist 側で duration filter を通す", () => {
    expect(runnerSource).toMatch(
      /submittedClipIds: result\.clipIds,[\s\S]*?durationFilter,[\s\S]*?submittedClipIdsAreDurationFiltered: false,[\s\S]*?playlistExpectedClipCount: result\.clipIds\.length,/
    );
    expect(runnerSource).toMatch(
      /setRestoredSubmittedClipIdsAreDurationFiltered\(false\);/
    );
  });
});
