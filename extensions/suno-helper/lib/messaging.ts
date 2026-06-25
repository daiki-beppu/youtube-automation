// overlay ⇄ background ⇄ runner の message を @webext-core/messaging で型付けする (#892)。
// overlay / runner はともに content script で互いに直接 messaging できないため、background が中継する
// （詳細は lib/overlay-relay.ts）。payload 定義をここに集約する (要件3)。
import { defineExtensionMessaging } from "@webext-core/messaging";

import type { CapturedPlaylist, PromptEntry } from "../../shared/api";
import type { ProgressPayload, SnapshotPayload } from "../../shared/constants";
import type { RunRange } from "./resume-state";

/**
 * run メッセージの payload (#854, #872)。collection mode は playlistName を伴う `{entries, playlistName}`、
 * 単一ファイル mode（旧形式）は `PromptEntry[]` をそのまま渡し content 側で wrap する（後方互換拡張）。
 *   - range: 0-based inclusive な実行範囲 (#872)。未指定は全 entry 実行（従来通り）。
 *   - collectionId: ERROR 停止時に resume state を紐付ける collection 識別子 (#872)。単一ファイル mode は省略。
 */
export type RunPayload =
  | PromptEntry[]
  | {
      entries: PromptEntry[];
      playlistName?: string;
      range?: RunRange;
      collectionId?: string;
      /** 実行対象の 0-based index 列 (#948)。「失敗分のみ再実行」で使う。指定時は range より優先。 */
      indices?: number[];
      /** 再開前の run で観測済みの playlist 対象 clip ID。 */
      submittedClipIds?: string[];
      /** playlist 追加時に揃っているべき clip ID 件数。 */
      playlistExpectedClipCount?: number;
    };

export interface RetryPlaylistPayload {
  playlistName: string;
  submittedClipIds: string[];
  expectedClipCount: number;
  collectionId?: string;
}

/** runner → background: ダウンロード完了を通知するペイロード (#1146)。 */
export interface DownloadCompletePayload {
  downloadId: number;
  filename: string;
}

interface ProtocolMap {
  /** overlay → background → runner: 連続実行を開始する。 */
  run(payload: RunPayload): { ok: true };
  /** overlay → background → runner: 連続実行を中断する。 */
  stop(): { ok: true };
  /** overlay → background → runner: playlist 追加のみ再実行する。entries 不要。 */
  retryPlaylist(payload: RetryPlaylistPayload): { ok: true };
  /** runner → background → overlay: 進捗を通知する。 */
  progress(payload: ProgressPayload): void;
  /** overlay → background → runner: 現在の進捗スナップショットを問い合わせる (#852)。未実行は null。 */
  queryProgress(): SnapshotPayload | null;
  /** background → overlay content: action クリックで overlay 表示を toggle する (#892)。 */
  toggleOverlay(): void;
  /** runner content: 自身の document（Suno `/me`）から playlist を scrape して返す (#893)。
   *  overlay → background → runner の手動 Capture と、background が開く bg `/me` tab への自動 capture が共用する。 */
  capturePlaylists(): CapturedPlaylist[];
  /** runner → background: 連続実行の playlist 化完了時に、bg `/me` tab で capture → POST する自動 trigger を要求する (#893)。
   *  background 側は fail soft（scrape / POST 失敗は warning log のみ）。 */
  requestPlaylistCapture(): void;
  /** runner → background: Download all 開始を通知し、background の chrome.downloads 監視を起動する (#1146)。
   *  content script は chrome.downloads API にアクセスできないため background に委譲する。 */
  startDownload(payload: { collectionId: string; format: string }): void;
  /** background → runner: chrome.downloads の完了通知を content へ中継する (#1146)。 */
  downloadComplete(payload: DownloadCompletePayload): void;
  /** content → background: chrome.debugger で trusted Cmd+P を dispatch する (#1251)。
   *  content script は chrome.debugger API にアクセスできないため background に委譲する。 */
  sendTrustedCmdP(payload: { isMac: boolean }): void;
}

export const { sendMessage, onMessage } = defineExtensionMessaging<ProtocolMap>();
