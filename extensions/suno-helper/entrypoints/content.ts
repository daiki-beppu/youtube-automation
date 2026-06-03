// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行 (content script)。
// DOM 操作は shared/dom の純関数へ委譲し、本ファイルは連続実行のフロー制御に専念する。
import type { PromptEntry } from "../../shared/api";
import {
  CLIPS_PER_REQUEST,
  INTER_CREATE_DELAY_MS,
  MAX_INFLIGHT_REQUESTS,
  PHASE,
  QUEUE_ERROR_WAIT_MS,
  SUNO_MATCHES,
} from "../../shared/constants";
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
import { onMessage, sendMessage } from "../lib/messaging";

/** Suno 同時生成キューに積める clip 数の上限（10 リクエスト × 2 clip = 20）。 */
const MAX_GENERATING_CLIPS = MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST;

export default defineContentScript({
  matches: [...SUNO_MATCHES],
  main() {
    let aborted = false;

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
      void sendMessage("progress", { phase: PHASE.GENERATING, index, total });
      await waitForGeneration(button, {
        isAborted: () => aborted,
        timeoutMs: GENERATE_TIMEOUT_MS,
        pollIntervalMs: POLL_INTERVAL_MS,
        settleMs: SETTLE_MS,
      });
    }

    async function runAll(entries: PromptEntry[]): Promise<void> {
      const total = entries.length;
      for (let i = 0; i < total; i++) {
        if (aborted) {
          void sendMessage("progress", { phase: PHASE.STOPPED, index: i, total });
          return;
        }
        try {
          // Suno のキュー上限（20 clip）を超えると後続が silent fail するため、投入前に空きを待つ。
          void sendMessage("progress", { phase: PHASE.WAITING_SLOT, index: i, total });
          await waitForQueueSlot(MAX_GENERATING_CLIPS, {
            isAborted: () => aborted,
            pollIntervalMs: POLL_INTERVAL_MS,
            timeoutMs: GENERATE_TIMEOUT_MS,
            queueErrorWaitMs: QUEUE_ERROR_WAIT_MS,
          });
          if (aborted) {
            void sendMessage("progress", { phase: PHASE.STOPPED, index: i, total });
            return;
          }
          void sendMessage("progress", { phase: PHASE.INJECTING, index: i, total });
          await injectAndGenerate(entries[i], i, total);
          if (aborted) {
            void sendMessage("progress", { phase: PHASE.STOPPED, index: i, total });
            return;
          }
          void sendMessage("progress", { phase: PHASE.DONE, index: i, total });
          // Create→clip-row DOM 反映ラグによる過剰投入 (race) を避けるため、次の投入前に間隔を空ける (#847)。
          await abortableSleep(INTER_CREATE_DELAY_MS, () => aborted);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          void sendMessage("progress", { phase: PHASE.ERROR, index: i, total, message });
          return;
        }
      }
      void sendMessage("progress", { phase: PHASE.FINISHED, total });
    }

    onMessage("run", ({ data }) => {
      aborted = false;
      void runAll(data);
      return { ok: true } as const;
    });

    onMessage("stop", () => {
      aborted = true;
      return { ok: true } as const;
    });
  },
});
