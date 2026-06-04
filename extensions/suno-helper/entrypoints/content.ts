// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行 (content script)。
// DOM 操作は shared/dom の純関数へ委譲し、本ファイルは連続実行のフロー制御に専念する。
import type { PromptEntry } from "../../shared/api";
import {
  CLIPS_PER_REQUEST,
  INTER_CREATE_DELAY_MS,
  MAX_INFLIGHT_REQUESTS,
  PHASE,
  type ProgressPayload,
  QUEUE_ERROR_WAIT_MS,
  type SnapshotPayload,
  SUNO_MATCHES,
} from "../../shared/constants";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import {
  abortableSleep,
  GENERATE_TIMEOUT_MS,
  POLL_INTERVAL_MS,
  SETTLE_MS,
  detectRecaptcha,
  resolveFields,
  resolveGenerateButton,
  setNativeValue,
  waitForGeneration,
  waitForQueueSlot,
} from "../../shared/dom";
import {
  clickPlaylistRowByName,
  fillPlaylistNameAndCreate,
  multiSelectClips,
  openAddToPlaylistDialogViaCmdP,
  selectRecentCompletedClips,
  waitForPlaylistDialogClose,
} from "../../shared/playlist-dom";
import { onMessage, sendMessage } from "../lib/messaging";

/** Suno 同時生成キューに積める clip 数の上限（10 リクエスト × 2 clip = 20）。 */
const MAX_GENERATING_CLIPS = MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST;

export default defineContentScript({
  matches: [...SUNO_MATCHES],
  main() {
    let aborted = false;
    // popup を閉じても進捗を維持・復元するための SSOT (#852)。run 開始で initSnapshot、
    // 以降は emitProgress が sendMessage より前に同期更新する（queryProgress と race しないため）。
    let currentSnapshot: SnapshotPayload | null = null;

    function emitProgress(payload: ProgressPayload): void {
      if (!currentSnapshot) {
        // run ハンドラで initSnapshot 済みのため到達しない。万一来たら不変条件違反として fail-loud。
        throw new Error("progress emit before run initialization");
      }
      currentSnapshot = applyProgress(currentSnapshot, payload);
      void sendMessage("progress", payload);
    }

    async function injectAndGenerate(entry: PromptEntry, index: number, total: number): Promise<void> {
      const { style, lyrics, title } = resolveFields();
      setNativeValue(style, entry.style);
      if (lyrics) {
        // 空文字でも上書きする。instrumental パターン (entry.lyrics === "") のとき前パターンの歌詞を残さない。
        setNativeValue(lyrics, entry.lyrics);
      } else if (entry.lyrics) {
        // 歌詞があるのに Lyrics 欄が見つからないのは設定不整合。silent に飛ばさず停止する。
        throw new Error("Lyrics 欄が見つかりません。Instrumental OFF（Custom Mode）になっているか確認してください。");
      }
      if (title) {
        // Song Title は entry.title 優先、無ければ entry.name で代替する (#844)。
        setNativeValue(title, entry.title ?? entry.name);
      } else {
        // title 欄不在は Suno 側 UI 改装の可能性。style/lyrics と違い fail-soft（警告のみで続行）。
        console.warn("Song Title 欄が見つかりませんでした。タイトル注入を skip して続行します。");
      }
      await abortableSleep(SETTLE_MS, () => aborted);

      if (detectRecaptcha()) {
        throw new Error("reCAPTCHA を検知しました。手動で解決してから再開してください。");
      }

      const button = resolveGenerateButton();
      button.click();
      // Generate 押下後は最大 GENERATE_TIMEOUT_MS の生成完了待ちに入る。注入中と区別して表示する。
      emitProgress({ phase: PHASE.GENERATING, index, total });
      await waitForGeneration(button, {
        isAborted: () => aborted,
        timeoutMs: GENERATE_TIMEOUT_MS,
        pollIntervalMs: POLL_INTERVAL_MS,
        settleMs: SETTLE_MS,
      });
    }

    /**
     * 全 clip を multi-select → Cmd+P で Add to Playlist dialog → 名前注入 → Create Playlist の一連を実行する (#854)。
     * 各ステップ間に abortableSleep を挟み、停止押下に素早く反応する。
     */
    async function addClipsToPlaylist(entryCount: number, playlistName: string): Promise<void> {
      emitProgress({ phase: PHASE.ADDING_TO_PLAYLIST, total: entryCount, message: playlistName });
      // 直近生成の完了 clip（entry 数 × 2 clip）を multi-select する。
      const rows = selectRecentCompletedClips(entryCount * CLIPS_PER_REQUEST);
      await multiSelectClips(rows);
      await abortableSleep(SETTLE_MS, () => aborted);

      const dialog = await openAddToPlaylistDialogViaCmdP();
      await abortableSleep(SETTLE_MS, () => aborted);

      await fillPlaylistNameAndCreate(dialog, playlistName);
      // Suno の Cmd+P dialog 仕様: Create Playlist は空 playlist を作るだけで、
      // 選択中 clip は追加されない。dialog 内 list に出現した新規 row を改めて click して
      // clip を紐付ける（同名 row が複数並ぶ場合は DOM 順で最後 = 直前作成分を選ぶ）。
      await abortableSleep(SETTLE_MS, () => aborted);
      await clickPlaylistRowByName(dialog, playlistName);
      await waitForPlaylistDialogClose({
        isAborted: () => aborted,
        pollIntervalMs: POLL_INTERVAL_MS,
        timeoutMs: GENERATE_TIMEOUT_MS,
      });
    }

    async function runAll(entries: PromptEntry[], playlistName?: string): Promise<void> {
      const total = entries.length;
      for (let i = 0; i < total; i++) {
        if (aborted) {
          emitProgress({ phase: PHASE.STOPPED, index: i, total });
          return;
        }
        try {
          // Suno のキュー上限（20 clip）を超えると後続が silent fail するため、投入前に空きを待つ。
          emitProgress({ phase: PHASE.WAITING_SLOT, index: i, total });
          await waitForQueueSlot(MAX_GENERATING_CLIPS, {
            isAborted: () => aborted,
            pollIntervalMs: POLL_INTERVAL_MS,
            timeoutMs: GENERATE_TIMEOUT_MS,
            queueErrorWaitMs: QUEUE_ERROR_WAIT_MS,
          });
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, index: i, total });
            return;
          }
          emitProgress({ phase: PHASE.INJECTING, index: i, total });
          await injectAndGenerate(entries[i], i, total);
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, index: i, total });
            return;
          }
          emitProgress({ phase: PHASE.DONE, index: i, total });
          // Create→clip-row DOM 反映ラグによる過剰投入 (race) を避けるため、次の投入前に間隔を空ける (#847)。
          await abortableSleep(INTER_CREATE_DELAY_MS, () => aborted);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          emitProgress({ phase: PHASE.ERROR, index: i, total, message });
          return;
        }
      }
      // collection mode のみ: 全 entry 生成後、FINISHED 直前に clip 一括 playlist 追加を実行する (#854)。
      if (playlistName) {
        if (aborted) {
          emitProgress({ phase: PHASE.STOPPED, total });
          return;
        }
        try {
          await addClipsToPlaylist(total, playlistName);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          emitProgress({ phase: PHASE.ERROR, total, message });
          return;
        }
        if (aborted) {
          emitProgress({ phase: PHASE.STOPPED, total });
          return;
        }
      }
      emitProgress({ phase: PHASE.FINISHED, total });
    }

    onMessage("run", ({ data }) => {
      aborted = false;
      // 後方互換: 旧形式の配列 payload は { entries } に wrap する (#854)。
      const { entries, playlistName } = Array.isArray(data) ? { entries: data, playlistName: undefined } : data;
      currentSnapshot = initSnapshot(entries, playlistName);
      void runAll(entries, playlistName);
      return { ok: true } as const;
    });

    onMessage("stop", () => {
      aborted = true;
      return { ok: true } as const;
    });

    // popup 再 open 時の進捗復元 (#852)。run 未実行は null（buildRestoreState が従来表示へフォールバック）。
    onMessage("queryProgress", () => currentSnapshot);
  },
});
