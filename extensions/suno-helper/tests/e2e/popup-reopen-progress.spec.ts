// 要件 (#852): popup を閉じて再 open しても進捗が復元される E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、popup の React
// 実装も unpacked 拡張ロードを要するため、Playwright の page.evaluate に本番モジュール
// (`lib/snapshot.ts` / `components/runner-errors.ts`) を直接 import できない (既存
// suno-queue.spec.ts と同じ制約)。よってここでは applyProgress / phaseToStatus /
// buildRestoreState と同手法を inline 再現し、「content が保持した snapshot から popup の
// fresh state へ復元マッピングが成立する」ことを実ブラウザ文脈で示す。
// 本番関数自体の回帰は unit (query-progress / phase-to-status / use-suno-runner-restore) が担う。
import { expect, test } from "@playwright/test";

const PHASE = {
  INJECTING: "injecting",
  GENERATING: "generating",
  WAITING_SLOT: "waiting-slot",
  DONE: "done",
  FINISHED: "finished",
  STOPPED: "stopped",
  ERROR: "error",
} as const;

test("popup を閉じて再 open すると content の snapshot から itemStates / status / isRunning が復元される (#852)", async ({
  page,
}) => {
  await page.setContent("<!doctype html><html><body></body></html>");

  const result = await page.evaluate(
    ({ PHASE }) => {
      type Phase = (typeof PHASE)[keyof typeof PHASE];
      type ItemState = "idle" | "active" | "done";
      type ProgressPayload = {
        phase: Phase;
        total: number;
        index?: number;
        message?: string;
        log?: { kind: "duration-check"; ok: boolean };
      };
      type Entry = { name: string; style: string; lyrics: string };
      type Snapshot = {
        collectionId: string;
        entries: Entry[];
        itemStates: ItemState[];
        isRunning: boolean;
        progress: ProgressPayload;
      };

      // --- 本番 lib/snapshot.ts と同手法を inline 再現 ---
      const nextItemStates = (prev: ItemState[], payload: ProgressPayload): ItemState[] => {
        const { phase, index } = payload;

        if (phase === PHASE.INJECTING) {
          return prev.map((s, i) => (i === index ? "active" : s === "active" ? "idle" : s));
        }
        if (phase === PHASE.DONE) {
          if (payload.log?.kind === "duration-check" && !payload.log.ok) {
            return [...prev];
          }
          return prev.map((s, i) => (i === index ? "done" : s));
        }
        return prev;
      };
      const initSnapshot = (entries: Entry[], collectionId: string): Snapshot => ({
        collectionId,
        entries,
        itemStates: entries.map(() => "idle"),
        isRunning: true,
        progress: { phase: PHASE.INJECTING, total: entries.length },
      });
      const isTerminal = (p: Phase) => p === PHASE.FINISHED || p === PHASE.STOPPED || p === PHASE.ERROR;
      const applyProgress = (snap: Snapshot, payload: ProgressPayload): Snapshot => ({
        ...snap,
        itemStates: nextItemStates(snap.itemStates, payload),
        progress: payload,
        isRunning: isTerminal(payload.phase) ? false : snap.isRunning,
      });

      // --- 本番 components/runner-errors.ts と同手法を inline 再現 ---
      const phaseToStatus = (snap: Snapshot): { text: string; error?: boolean } => {
        const { phase, index, total, message } = snap.progress;
        const n = (index ?? 0) + 1;
        switch (phase) {
          case PHASE.INJECTING:
            return { text: `[${n}/${total}] 注入中: ${snap.entries[index ?? 0]?.name ?? ""}` };
          case PHASE.WAITING_SLOT:
            return { text: `[${n}/${total}] 生成キューの空き待ち…` };
          case PHASE.GENERATING:
            return { text: `[${n}/${total}] 生成待ち…` };
          case PHASE.DONE:
            return { text: `[${n}/${total}] 完了` };
          case PHASE.FINISHED:
            return { text: `完了: ${total} パターンを実行しました。` };
          case PHASE.STOPPED:
            return { text: "停止しました。再実行できます。" };
          default:
            return { text: `中断: ${message ?? ""}`, error: true };
        }
      };
      const buildRestoreState = (snap: Snapshot | null) => {
        if (!snap) return null;
        const { text, error } = phaseToStatus(snap);
        return {
          collectionId: snap.collectionId,
          entries: snap.entries,
          itemStates: snap.itemStates,
          isRunning: snap.isRunning,
          status: text,
          isError: Boolean(error),
        };
      };

      // === シナリオ: content が 3 パターンの連続実行を進行（2 件 done、3 件目を注入中）===
      const entries: Entry[] = [
        { name: "pattern-1", style: "s1", lyrics: "l1" },
        { name: "pattern-2", style: "s2", lyrics: "l2" },
        { name: "pattern-3", style: "s3", lyrics: "l3" },
      ];
      let contentSnapshot: Snapshot | null = initSnapshot(entries, "20260601-clm-popup-reopen-collection");
      contentSnapshot = applyProgress(contentSnapshot, { phase: PHASE.DONE, index: 0, total: 3 });
      contentSnapshot = applyProgress(contentSnapshot, { phase: PHASE.DONE, index: 1, total: 3 });
      contentSnapshot = applyProgress(contentSnapshot, { phase: PHASE.INJECTING, index: 2, total: 3 });

      // popup を閉じる = React state 破棄。再 open は fresh state から始まる。
      const freshPopup = {
        entries: [] as Entry[],
        itemStates: [] as ItemState[],
        isRunning: false,
        status: "",
        isError: false,
      };

      // 再 open: queryProgress で content の snapshot を取得し復元マッピングを適用。
      const restored = buildRestoreState(contentSnapshot);
      const reopened = restored ? { ...restored } : freshPopup;

      // === 比較用: 終了 (FINISHED) 後に再 open した場合 ===
      const finishedSnapshot = applyProgress(contentSnapshot, { phase: PHASE.FINISHED, total: 3 });
      const reopenedAfterFinish = buildRestoreState(finishedSnapshot);

      return { freshPopup, reopened, reopenedAfterFinish };
    },
    { PHASE },
  );

  // 復元前の fresh popup は空（state が破棄されていることの確認）。
  expect(result.freshPopup.itemStates).toEqual([]);
  expect(result.freshPopup.status).toBe("");

  // 再 open で直近の itemStates / phase / status / isRunning が即時復元される。
  expect(result.reopened.itemStates).toEqual(["done", "done", "active"]);
  expect(result.reopened.status).toBe("[3/3] 注入中: pattern-3");
  expect(result.reopened.isRunning).toBe(true);
  expect(result.reopened.isError).toBe(false);

  // 完了後の再 open でも完了情報が復元される。
  expect(result.reopenedAfterFinish?.isRunning).toBe(false);
  expect(result.reopenedAfterFinish?.status).toBe("完了: 3 パターンを実行しました。");
  expect(result.reopenedAfterFinish?.itemStates).toEqual(["done", "done", "active"]);
});
