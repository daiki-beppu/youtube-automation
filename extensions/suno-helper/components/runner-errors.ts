// useSunoRunner のエラー整形ヘルパ純関数（テスタビリティのため wxt 依存を排して分離）。
// 拡張をリロードした後 Suno タブをハードリロードしないと出る Chrome 標準エラー
// (`Could not establish connection. Receiving end does not exist.`) を検知して、
// popup の案内に対処法（⌘+Shift+R）を含める。
// #852: content の snapshot を popup の status 文字列 / 復元 state へ変換する純関数も同居する。
import { PHASE, type ProgressLog, type SnapshotPayload } from "../../shared/constants";

/** popup の再 open 復元に使う state。useSunoRunner の restore effect がそのまま React state へ流す。 */
export interface RestoreState {
  collectionId: string;
  entries: SnapshotPayload["entries"];
  itemStates: SnapshotPayload["itemStates"];
  isRunning: boolean;
  status: string;
  isError: boolean;
  // collection mode の playlist 名 (#854)。再 open 時の display only 表示に使う。
  playlistName?: string;
  // ERROR 停止した entry の 0-based index (#872 要件3)。chrome.storage の resume state と二重化し、
  // popup の再開バナーの冗長ソースとして消費する。ERROR phase 到達時のみ確定、それ以外は undefined。
  failedIndex?: number;
  // リトライ上限まで失敗しスキップされた entry の 0-based index 一覧 (#948)。
  failedIndices?: number[];
  // playlist 追加対象として generate response から観測済みの clip ID 一覧。
  submittedClipIds?: string[];
  // playlist 追加時に揃っているべき clip ID 件数。
  playlistExpectedClipCount?: number;
}

function formatSeconds(value: number): string {
  return `${Math.round(value)}s`;
}

function formatDurationLimit(log: Extract<ProgressLog, { kind: "duration-check" }>): string {
  if (log.ok) {
    return "";
  }
  if (log.maxSec !== undefined && log.durationSec > log.maxSec) {
    return ` (max ${formatSeconds(log.maxSec)})`;
  }
  if (log.minSec !== undefined && log.durationSec < log.minSec) {
    return ` (min ${formatSeconds(log.minSec)})`;
  }
  if (log.maxSec !== undefined) {
    return ` (max ${formatSeconds(log.maxSec)})`;
  }
  if (log.minSec !== undefined) {
    return ` (min ${formatSeconds(log.minSec)})`;
  }
  return "";
}

function formatProgressLog(log: ProgressLog): { text: string; error?: boolean } {
  switch (log.kind) {
    case "duration-check": {
      const mark = log.ok ? "✓" : "✗";
      return {
        text: `"${log.entryName}": ${formatSeconds(log.durationSec)} ${mark}${formatDurationLimit(log)}`,
      };
    }
    case "retry":
      return { text: `"${log.entryName}": リトライ ${log.attempt}/${log.max}` };
    case "skip":
      return { text: `"${log.entryName}": 全滅 — スキップ` };
    default: {
      const exhaustive: never = log;
      throw new Error(`未知の progress log: ${String(exhaustive)}`);
    }
  }
}

function formatAllowedProgressLog(progress: SnapshotPayload["progress"]): { text: string; error?: boolean } | null {
  if (!progress.log) {
    return null;
  }
  switch (progress.phase) {
    case PHASE.DONE:
      return progress.log.kind === "duration-check" ? formatProgressLog(progress.log) : null;
    case PHASE.WAITING_SLOT:
      return progress.log.kind === "retry" ? formatProgressLog(progress.log) : null;
    case PHASE.ENTRY_FAILED:
      return progress.log.kind === "skip" ? formatProgressLog(progress.log) : null;
    default:
      return null;
  }
}

/**
 * 直近 progress（と entry 名解決用の entries）を popup の status 文字列へ変換する。
 * content の snapshot 構築 (live) と popup の再 open 復元 (restore) の双方が同一文言を使うための SSOT。
 * 参照するのは progress / entries のみ（itemStates / isRunning は読まない）ため、引数も両者に絞る。
 */
export function phaseToStatus(
  progress: SnapshotPayload["progress"],
  entries: SnapshotPayload["entries"],
): { text: string; error?: boolean } {
  const logStatus = formatAllowedProgressLog(progress);
  if (logStatus) {
    return logStatus;
  }

  const { phase, index, total, message } = progress;
  const n = (index ?? 0) + 1;
  switch (phase) {
    case PHASE.INJECTING:
      return { text: `[${n}/${total}] 注入中: ${entries[index ?? 0]?.name ?? ""}` };
    case PHASE.WAITING_SLOT:
      // message は bridge 縮退の明示 (#948)。通常時は undefined で従来文言のまま。
      return { text: `[${n}/${total}] 生成キューの空き待ち…${message ? `（${message}）` : ""}` };
    case PHASE.WAITING_CAPTCHA:
      return { text: `[${n}/${total}] captcha 解消待ち…（多くは自動で解消します）` };
    case PHASE.GENERATING:
      return { text: `[${n}/${total}] 生成待ち…` };
    case PHASE.DONE:
      return { text: `[${n}/${total}] 完了` };
    case PHASE.ENTRY_FAILED:
      // entry 単位の失敗スキップ (#948)。run 全体は継続するため error フラグは立てない（status は黄信号扱い）。
      return { text: `[${n}/${total}] 失敗のためスキップ: ${message ?? ""}` };
    case PHASE.DOWNLOADING:
      return { text: `ダウンロード中…${message ? `（${message}）` : ""}` };
    case PHASE.ADDING_TO_PLAYLIST:
      // playlist 名は ProgressPayload.message で運ぶ（専用フィールドを足さず既存経路で表示する）。
      return { text: `Playlist '${message ?? ""}' へ追加中…` };
    case PHASE.FINISHED:
      // 失敗スキップ付き完走 (#948) は message に失敗一覧が載る。無ければ従来文言。
      return message
        ? { text: `完了（一部失敗）: ${message}`, error: true }
        : { text: `完了: ${total} パターンを実行しました。` };
    case PHASE.STOPPED:
      return { text: "停止しました。手動で続行できます。", error: true };
    case PHASE.ERROR:
      return { text: `中断: ${message ?? ""}`, error: true };
    default: {
      // Phase は閉じた union。新 phase を追加すると型エラーになり、未知値の silent 表示を防ぐ（Fail Fast）。
      const exhaustive: never = phase;
      throw new Error(`未知の phase: ${String(exhaustive)}`);
    }
  }
}

/**
 * content の snapshot を popup の復元 state へ変換する。
 * snapshot 無し (null) は復元せず従来表示へフォールバックするため null を返す（silent fallback の根拠）。
 */
export function buildRestoreState(snap: SnapshotPayload | null): RestoreState | null {
  if (!snap) {
    return null;
  }
  const { text, error } = phaseToStatus(snap.progress, snap.entries);
  return {
    collectionId: snap.collectionId,
    entries: snap.entries,
    itemStates: snap.itemStates,
    isRunning: snap.isRunning,
    status: text,
    isError: Boolean(error),
    playlistName: snap.playlistName,
    failedIndex: snap.failedIndex,
    failedIndices: snap.failedIndices,
    submittedClipIds: snap.submittedClipIds,
    playlistExpectedClipCount: snap.playlistExpectedClipCount,
  };
}

/**
 * content script 未注入の典型エラーを検知する。
 * 拡張をリロードした後に Suno タブをハードリロードしないと、古い content script が落ちた
 * まま新しい script が注入されず、popup → tab の sendMessage が
 * `Could not establish connection. Receiving end does not exist.` で失敗する。
 */
export function isContentScriptMissingError(message: string): boolean {
  return /receiving end does not exist|could not establish connection/i.test(message);
}

export function formatRunError(message: string): string {
  if (isContentScriptMissingError(message)) {
    return `開始失敗: ${message}\nSuno タブをハードリロード (⌘+Shift+R / Ctrl+Shift+R) してから再度実行してください。`;
  }
  return `開始失敗: ${message}\nSuno の Custom Mode 画面を開いた状態で実行してください。`;
}

export function formatStopError(message: string): string {
  if (isContentScriptMissingError(message)) {
    return `停止リクエスト失敗: ${message}\nSuno タブをハードリロード (⌘+Shift+R / Ctrl+Shift+R) してから再度実行してください。`;
  }
  return `停止リクエスト失敗: ${message}`;
}

/**
 * background の fire-and-forget 中継（toggleOverlay 等）が reject したときの SW console ログを決める。
 * content script 未注入（非 Suno タブでのアイコンクリック / 拡張リロード後の stale タブ）は想定内なので
 * info に落とし、それ以外は warn で残す。catch せず放置すると未処理 rejection として
 * chrome://extensions のエラーバッジを汚染するため、必ず本関数経由で消費する（#937）。
 */
export function describeRelayFailure(action: string, message: string): { level: "info" | "warn"; text: string } {
  if (isContentScriptMissingError(message)) {
    return {
      level: "info",
      text: `[suno-helper] ${action} の中継先がありません（Suno タブ以外、または拡張リロード後はタブをハードリロードしてください）: ${message}`,
    };
  }
  return { level: "warn", text: `[suno-helper] ${action} の中継に失敗しました: ${message}` };
}
