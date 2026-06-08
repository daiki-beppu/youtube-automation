// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行 (content script)。
// DOM 操作は shared/dom の純関数へ委譲し、本ファイルは連続実行のフロー制御に専念する。
import type { PromptEntry } from "../../shared/api";
import {
  CLIPS_PER_REQUEST,
  INJECT_ACK_TIMEOUT_MS,
  INTER_CREATE_DELAY_MS,
  MAX_INFLIGHT_REQUESTS,
  MAX_INJECT_RETRY,
  PHASE,
  type ProgressPayload,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
  type SnapshotPayload,
  SUNO_MATCHES,
} from "../../shared/constants";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import { clearResumeStateForCollection, type RunRange, writeResumeState } from "../lib/resume-state";
import { injectWithVerification } from "../lib/inject-retry";
import {
  abortableSleep,
  GENERATE_TIMEOUT_MS,
  POLL_INTERVAL_MS,
  SETTLE_MS,
  detectRecaptcha,
  getInFlightClipCount,
  injectAdvancedFields,
  resolveAdvancedFields,
  resolveFields,
  resolveGenerateButton,
  setNativeValue,
  waitForGeneration,
  waitForInFlightIncrease,
  waitForQueueSlot,
} from "../../shared/dom";
import {
  clickPlaylistRowByName,
  fillPlaylistNameAndCreate,
  multiSelectClips,
  openAddToPlaylistDialogViaCmdP,
  selectRecentClips,
  waitForPlaylistDialogClose,
} from "../../shared/playlist-dom";
import { onMessage, sendMessage } from "../lib/messaging";

/** Suno 同時生成キューに積める clip 数の上限（10 リクエスト × 2 clip = 20）。 */
const MAX_GENERATING_CLIPS = MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST;

export default defineContentScript({
  matches: [...SUNO_MATCHES],
  main() {
    let aborted = false;
    // 連続実行の二重起動ガード (#892 要件7)。runAll 実行中の run 再着信を弾く。
    let running = false;
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
      // Custom Mode > More Options の 3 フィールド (#900)。radix slider への注入は keydown dispatch
      // (ArrowRight/Left, bubbles:true composed:true) を採用した。実機検証で radix Slider root の
      // keydown listener に合成イベントが届き aria-valuenow が動くことを確認済み（pointer event 合成
      // fallback は不要だった）。entry に値があり selector が不在なら injectAdvancedFields が throw する
      // (fail-loud)。値が無ければ skip する (fail-soft、後方互換)。
      await injectAdvancedFields(entry, resolveAdvancedFields());
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
      // 直近 entry 数 × 2 clip を multi-select する。selectRecentClips は生成中 / 完了を区別せず
      // scroller 配下の multi-select ボタンから per-clip row を導出して拾う（未完成分は Suno 側で
      // playlist 追加後に生成完了時点で自動反映される）。
      // clip row が 1 件も無ければ selectRecentClips が fail-loud throw する（#881）。
      const rows = selectRecentClips(entryCount * CLIPS_PER_REQUEST);
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

    interface RunOptions {
      // 0-based inclusive な実行範囲 (#872)。未指定は全 entry。判断A: range 指定でも entries 全体と
      // 絶対 index を保ち、range 内の entry だけを処理する（slice 再採番による index ズレを起こさない）。
      range?: RunRange;
      // ERROR 停止時に resume state を紐付ける collection 識別子 (#872)。単一ファイル mode は undefined。
      collectionId?: string;
      // collection mode のときの playlist 名 (#854)。全 entry 完了後の clip 一括追加に使う。
      playlistName?: string;
    }

    async function runAll(entries: PromptEntry[], options: RunOptions): Promise<void> {
      const { range, collectionId, playlistName } = options;
      const total = entries.length;
      const startIndex = range ? range.start : 0;
      const endIndex = range ? range.end : total - 1;
      for (let i = startIndex; i <= endIndex; i++) {
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
            // queue 空き待ちは single clip 完了待ち (GENERATE_TIMEOUT_MS) とは別系統の 5 分 (#864 root cause 1)。
            timeoutMs: QUEUE_SLOT_WAIT_TIMEOUT_MS,
            queueErrorWaitMs: QUEUE_ERROR_WAIT_MS,
          });
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, index: i, total });
            return;
          }
          emitProgress({ phase: PHASE.INJECTING, index: i, total });
          // inject 後に in-flight が CLIPS_PER_REQUEST 増えたか検証し、silent drop なら同じ entry を retry する (#864 root cause 3)。
          await injectWithVerification({
            inject: () => injectAndGenerate(entries[i], i, total),
            getInFlightClipCount,
            waitForInFlightIncrease,
            isAborted: () => aborted,
            clipsPerRequest: CLIPS_PER_REQUEST,
            maxRetry: MAX_INJECT_RETRY,
            ackTimeoutMs: INJECT_ACK_TIMEOUT_MS,
            pollIntervalMs: POLL_INTERVAL_MS,
            describeEntry: () => `entry ${i} (${entries[i].title ?? entries[i].name})`,
          });
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
          // 失敗 index を永続化し、次回 popup 起動時の再開バナーで提示する (#872 要件3)。
          // collection 識別子が無い単一ファイル mode は再開対象を特定できないため永続化しない。
          if (collectionId) {
            void writeResumeState({ collectionId, failedIndex: i, total, timestamp: Date.now() });
          }
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
      // 全 entry 完了。この collection の resume state を消去する (#872 要件5)。
      if (collectionId) {
        void clearResumeStateForCollection(collectionId);
      }
      emitProgress({ phase: PHASE.FINISHED, total });
    }

    onMessage("run", ({ data }) => {
      // 二重実行ガード (#892 要件7)。実行中の run 再着信は no-op で ack のみ返す（再開連打対策）。
      if (running) {
        return { ok: true } as const;
      }
      running = true;
      aborted = false;
      // 後方互換: 旧形式の配列 payload は { entries } に wrap する (#854)。range / collectionId は無し。
      const { entries, playlistName, range, collectionId } = Array.isArray(data)
        ? { entries: data, playlistName: undefined, range: undefined, collectionId: undefined }
        : data;
      currentSnapshot = initSnapshot(entries, playlistName);
      void runAll(entries, { range, collectionId, playlistName }).finally(() => {
        running = false;
      });
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
