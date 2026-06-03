// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行 (content script)。
// DOM 操作は shared/dom の純関数へ委譲し、本ファイルは連続実行のフロー制御に専念する。
import type { PromptEntry } from "../../shared/api";
import { PHASE, SUNO_MATCHES } from "../../shared/constants";
import {
  GENERATE_TIMEOUT_MS,
  POLL_INTERVAL_MS,
  SETTLE_MS,
  detectRecaptcha,
  resolveFields,
  resolveGenerateButton,
  setNativeValue,
  sleep,
  waitForGeneration,
} from "../../shared/dom";
import { onMessage, sendMessage } from "../lib/messaging";

export default defineContentScript({
  matches: [...SUNO_MATCHES],
  main() {
    let aborted = false;

    async function injectAndGenerate(entry: PromptEntry, index: number, total: number): Promise<void> {
      const { style, lyrics } = resolveFields();
      setNativeValue(style, entry.style);
      if (entry.lyrics) {
        // 歌詞があるのに Lyrics 欄が見つからないのは設定不整合。silent に飛ばさず停止する。
        if (!lyrics) {
          throw new Error("Lyrics 欄が見つかりません。Instrumental OFF（Custom Mode）になっているか確認してください。");
        }
        setNativeValue(lyrics, entry.lyrics);
      }
      await sleep(SETTLE_MS);

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
          void sendMessage("progress", { phase: PHASE.INJECTING, index: i, total });
          await injectAndGenerate(entries[i], i, total);
          if (aborted) {
            void sendMessage("progress", { phase: PHASE.STOPPED, index: i, total });
            return;
          }
          void sendMessage("progress", { phase: PHASE.DONE, index: i, total });
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
