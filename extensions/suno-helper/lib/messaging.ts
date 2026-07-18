// overlay ⇄ background ⇄ runner の message を @webext-core/messaging で型付けする (#892)。
// overlay / runner はともに content script で互いに直接 messaging できないため、background が中継する
// （詳細は lib/overlay-relay.ts）。payload 定義をここに集約する (要件3)。
import { defineExtensionMessaging } from "@webext-core/messaging";

import type {
  CollectionSummary,
  DownloadedPayload,
  DurationFilter,
  PromptEntry,
  PromptResponse,
  ServerInfo,
} from "../../shared/api";
import type {
  ProgressPayload,
  RunModeId,
  SnapshotPayload,
} from "../../shared/constants";
import type { LocalServerSource } from "../../shared/constants";
import type { RunRange } from "./resume-state";
import type {
  UnattendedRunRequest,
  UnattendedRunState,
} from "./unattended-run";

/**
 * run メッセージの payload (#854, #872)。
 *   - range: 0-based inclusive な実行範囲 (#872)。未指定は全 entry 実行（従来通り）。
 *   - collectionId: ERROR 停止時に resume state を紐付ける collection 識別子 (#872)。
 */
export interface RunPayload {
  entries: PromptEntry[];
  playlistName: string;
  /** collection 単位 duration guard 閾値 (#1259)。実フィルタは yield guard 側で消費する。 */
  durationFilter?: DurationFilter;
  range?: RunRange;
  collectionId: string;
  /** 生成完了待ちの方式。serial は従来挙動、queue は ACK 後に次 entry を投入する。 */
  runMode: RunModeId;
  regenerateDurationOutliers: boolean;
  durationOutlierWarnings?: Record<number, string>;
  /** 任意の部分実行対象の 0-based index 列。チェック選択や失敗分再実行で使う。指定時は range より優先。 */
  indices?: number[];
  /** 再開前の run で観測済みの playlist 対象 clip ID。 */
  submittedClipIds?: string[];
  /** true のとき submittedClipIds は resume 保存時点で OK clip IDs に正規化済み。 */
  submittedClipIdsAreDurationFiltered?: boolean;
  /** duration filter 後に playlist 追加・download へ採用する OK clip 件数。 */
  playlistExpectedClipCount?: number;
  /** 定期実行だけが付与する上限・checkpoint 契約。未指定の手動 run は従来挙動。 */
  unattended?: {
    request: UnattendedRunRequest;
    deferredIndices: number[];
    leaseToken: string;
  };
}

export interface RetryPlaylistPayload {
  playlistName: string;
  submittedClipIds: string[];
  expectedClipCount: number;
  collectionId: string;
  /** retryPlaylist 入口でも通常 run と同じ duration guard 契約を適用する。 */
  durationFilter?: DurationFilter;
  /** false の run では保存済み NG clip も playlist/download 対象に維持する。 */
  regenerateDurationOutliers: boolean;
  durationOutlierWarnings?: Record<number, string>;
  /** true のとき submittedClipIds は resume 保存時点で OK clip IDs に正規化済み。 */
  submittedClipIdsAreDurationFiltered?: boolean;
  shouldDownload?: boolean;
  /** 定期実行の playlist/download 再開時だけ付与する checkpoint 契約。 */
  unattended?: {
    request: UnattendedRunRequest;
    deferredIndices: number[];
    leaseToken: string;
  };
}

/** overlay → runner: Suno UI でユーザーが手動選択した clip を resume 用 ID として採用する。 */
interface AdoptSelectedClipsPayload {
  expectedClipCount: number;
}

/** runner → background: ダウンロード完了を通知するペイロード (#1146)。 */
interface DownloadCompletePayload {
  filename: string;
}

/** background → runner: ダウンロード失敗を通知するペイロード (#1217)。 */
interface DownloadFailedPayload {
  message: string;
}

type StartDownloadResult = { ok: true } | { ok: false; message: string };

/** overlay → runner: ダウンロードのみ再実行するペイロード (#1251)。 */
export interface RetryDownloadPayload {
  collectionId: string;
  submittedClipIds: string[];
  expectedClipCount?: number;
  /** 定期実行の download 再開時だけ付与する checkpoint 契約。 */
  unattended?: {
    request: UnattendedRunRequest;
    deferredIndices: number[];
    leaseToken: string;
  };
}

interface ProtocolMap {
  /** content / overlay → background: 拡張更新後の実行コンテキストを確認する。 */
  extensionVersionHandshake(payload: { version: string }): {
    version: string;
    matches: boolean;
  };
  /** overlay → background → runner: 連続実行を開始する。 */
  run(
    payload: RunPayload
  ): { ok: true } | { ok: false; busy: true } | { ok: false; error: string };
  /** overlay → background → runner: 連続実行を中断する。 */
  stop(): { ok: true };
  /** overlay → background → runner: playlist 追加のみ再実行する。entries 不要。 */
  retryPlaylist(
    payload: RetryPlaylistPayload
  ): { ok: true } | { ok: false; busy: true };
  /** overlay → background → runner: 手動選択中の clip ID を読む。 */
  adoptSelectedClips(payload: AdoptSelectedClipsPayload): {
    ok: true;
    clipIds: string[];
  };
  /** runner → background → overlay: 進捗を通知する。 */
  progress(payload: ProgressPayload): void;
  /** overlay → background → runner: 現在の進捗スナップショットを問い合わせる (#852)。未実行は null。 */
  queryProgress(): SnapshotPayload | null;
  /** scheduler / overlay → runner: 直近の定期実行 checkpoint・手動介入理由を読む。 */
  queryUnattendedState(): UnattendedRunState | null;
  /** background → overlay content: action クリックで overlay 表示を toggle する (#892)。 */
  toggleOverlay(): void;
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
  discoverServerSources(): LocalServerSource[];
  fetchCompatibilityWarning(payload: {
    baseUrl: string;
    extensionVersion: string;
  }): string;
  /** overlay → background: `/server-info` を extension origin から取得する。 */
  fetchServerInfo(payload: { baseUrl: string }): ServerInfo;
  /** overlay → background: `/collections` を extension origin から取得する。 */
  fetchCollections(payload: { baseUrl: string }): CollectionSummary[];
  /** overlay → background: collection prompts を extension origin から取得する。 */
  fetchCollectionPrompts(payload: {
    baseUrl: string;
    collectionId: string;
  }): PromptEntry[];
  /** overlay → background: collection prompts と metadata を extension origin から取得する。 */
  fetchCollectionPromptResponse(payload: {
    baseUrl: string;
    collectionId: string;
  }): PromptResponse;
  /** runner -> background: consume a short-lived server-side command once. */
  consumeUnattendedRequest(payload: {
    baseUrl: string;
    nonce: string;
  }): unknown;
  acquireUnattendedLease(payload: {
    collectionId: string;
    requestId: string;
  }): {
    acquired: boolean;
    token?: string;
  };
  heartbeatUnattendedLease(payload: {
    collectionId: string;
    token: string;
  }): void;
  releaseUnattendedLease(payload: {
    collectionId: string;
    token: string;
  }): void;
  /** runner → background: token 取得と POST /downloaded を privileged boundary に委譲する (#1217)。
   *  部分完了時はサーバーの warning を返す (#1913)。 */
  postDownloaded(payload: {
    baseUrl: string;
    collectionId: string;
    body: DownloadedPayload;
  }): {
    warning: string | null;
  };
  /** overlay → background → runner: ダウンロードのみ再実行する (#1251)。 */
  retryDownload(
    payload: RetryDownloadPayload
  ): { ok: true } | { ok: false; busy: true };
}

export const { sendMessage, onMessage } =
  defineExtensionMessaging<ProtocolMap>();
