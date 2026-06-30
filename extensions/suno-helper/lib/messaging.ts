// overlay ⇄ background ⇄ runner の message を @webext-core/messaging で型付けする (#892)。
// overlay / runner はともに content script で互いに直接 messaging できないため、background が中継する
// （詳細は lib/overlay-relay.ts）。payload 定義をここに集約する (要件3)。
import { defineExtensionMessaging } from "@webext-core/messaging";

import type { CapturedPlaylist, CollectionSummary, DownloadedPayload, PromptEntry } from "../../shared/api";
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
  shouldDownload?: boolean;
}

/** overlay → runner: Suno UI でユーザーが手動選択した clip を resume 用 ID として採用する。 */
export interface AdoptSelectedClipsPayload {
  expectedClipCount: number;
}

/** runner → background: `/me/playlists` から playlist URL を解決する。 */
export interface ResolvePlaylistUrlPayload {
  playlistName: string;
}

/** runner → background: ダウンロード完了を通知するペイロード (#1146)。 */
export interface DownloadCompletePayload {
  filename: string;
}

/** background → runner: ダウンロード失敗を通知するペイロード (#1217)。 */
export interface DownloadFailedPayload {
  message: string;
}

export type StartDownloadResult = { ok: true } | { ok: false; message: string };

/** overlay → runner: ダウンロードのみ再実行するペイロード (#1251)。 */
export interface RetryDownloadPayload {
  collectionId: string;
  playlistName: string;
  submittedClipIds: string[];
  expectedClipCount?: number;
  sunoPlaylistUrl?: string;
}

interface ProtocolMap {
  /** overlay → background → runner: 連続実行を開始する。 */
  run(payload: RunPayload): { ok: true };
  /** overlay → background → runner: 連続実行を中断する。 */
  stop(): { ok: true };
  /** overlay → background → runner: playlist 追加のみ再実行する。entries 不要。 */
  retryPlaylist(payload: RetryPlaylistPayload): { ok: true };
  /** overlay → background → runner: 手動選択中の clip ID を読む。 */
  adoptSelectedClips(payload: AdoptSelectedClipsPayload): { ok: true; clipIds: string[] };
  /** runner → background: bg `/me/playlists` tab から playlist URL を解決する。 */
  resolvePlaylistUrl(payload: ResolvePlaylistUrlPayload): { url: string };
  /** runner → background → overlay: 進捗を通知する。 */
  progress(payload: ProgressPayload): void;
  /** overlay → background → runner: 現在の進捗スナップショットを問い合わせる (#852)。未実行は null。 */
  queryProgress(): SnapshotPayload | null;
  /** background → overlay content: action クリックで overlay 表示を toggle する (#892)。 */
  toggleOverlay(): void;
  /** runner content: 自身の document（Suno `/me`）から playlist を scrape して返す (#893)。
   *  overlay → background → runner の手動 Capture と、background が開く bg `/me` tab への自動 capture が共用する。 */
  capturePlaylists(): CapturedPlaylist[];
  /** runner → background: Download all 開始を通知し、background の chrome.downloads 監視を起動する (#1146)。
   *  content script は chrome.downloads API にアクセスできないため background に委譲する。 */
  startDownload(payload: { format: string }): StartDownloadResult;
  /** runner → background: Download all 起動前後の失敗時に chrome.downloads watcher を解除する (#1217)。 */
  cancelDownload(): void;
  /** background → runner: chrome.downloads の完了通知を content へ中継する (#1146)。 */
  downloadComplete(payload: DownloadCompletePayload): void;
  /** background → runner: chrome.downloads の失敗通知を content へ中継する (#1217)。 */
  downloadFailed(payload: DownloadFailedPayload): void;
  /** content → background: chrome.debugger で trusted Cmd+P を dispatch する (#1251)。
   *  content script は chrome.debugger API にアクセスできないため background に委譲する。 */
  sendTrustedCmdP(payload: { isMac: boolean }): void;
  /** overlay → background: localhost read API を extension origin から取得する。 */
  fetchCompatibilityWarning(payload: { baseUrl: string; extensionVersion: string }): string;
  /** overlay → background: `/collections` を extension origin から取得する。 */
  fetchCollections(payload: { baseUrl: string }): CollectionSummary[];
  /** overlay → background: `/suno/prompts.json` を extension origin から取得する。 */
  fetchPrompts(payload: { baseUrl: string }): PromptEntry[];
  /** overlay → background: collection prompts を extension origin から取得する。 */
  fetchCollectionPrompts(payload: { baseUrl: string; collectionId: string }): PromptEntry[];
  /** runner → background: token 取得と POST /downloaded を privileged boundary に委譲する (#1217)。 */
  postDownloaded(payload: { baseUrl: string; collectionId: string; body: DownloadedPayload }): void;
  /** overlay → background → runner: ダウンロードのみ再実行する (#1251)。 */
  retryDownload(payload: RetryDownloadPayload): { ok: true };
}

export const { sendMessage, onMessage } = defineExtensionMessaging<ProtocolMap>();
