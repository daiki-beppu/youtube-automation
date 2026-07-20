// background ↔ overlay ↔ runner content の型付きメッセージング（@webext-core/messaging）。
//
// overlay から background relay 経由で runner へ「注入開始 / 停止」を送り、runner の「進捗」を同一タブへ返す。
// 3 者が解釈を共有する進捗フェーズは PHASES で固定する（状態の正規化）。
//
// asset（曲 / ジャケット）は 1 メッセージ 1 件で per-track 分割して送る（#871）。
// 全 track を 1 メッセージにまとめると Base64 化後のバイト列が chrome.tabs.sendMessage の
// 64MiB 上限を超えるため、overlay・runner とも常時 1 asset 分のみメモリ保持する設計にする。

import { defineExtensionMessaging } from "@webext-core/messaging";

import type { DistrokidReleaseRecord } from "../../shared/api";
import type { SerializedAsset } from "./asset-transfer";
import type {
  LocalFetchAssetRequest,
  LocalFetchRequest,
  LocalFetchTextResponse,
} from "./local-fetch";
import type { ReleasePayload } from "./types";

// 注入フローの進捗フェーズ（runner -> overlay の PROGRESS で使用）。
// 値は overlay の表示分岐キーになるため一意な文字列で固定する。
export const PHASES = {
  INJECTING: "injecting",
  DONE: "done",
  ERROR: "error",
  STOPPED: "stopped",
} as const;

export type Phase = (typeof PHASES)[keyof typeof PHASES];

// overlay -> runner: 注入セッションを開始する。テキスト / SELECT 系のみを運び asset は含まない。
// （プロファイル + アルバム名 + リリース日 + 全 track のタイトル / songwriter を一括注入する。）
export interface InjectStartRequest {
  payload: ReleasePayload;
}

// overlay -> runner: 1 track の曲ファイルを注入する。
// asset は overlay 側で fetch 済みのものを直列化して渡す（asset-transfer.ts 参照）。
// trackIndex は payload.release.tracks の 0-indexed 位置。
// fetchAsset は取得失敗時に throw する（null を返さない）ため asset に欠落は生じない。
export interface InjectTrackRequest {
  trackIndex: number;
  asset: SerializedAsset;
}

// overlay -> runner: ジャケットを注入する（release.cover !== null のときのみ送信）。
export interface InjectCoverRequest {
  asset: SerializedAsset;
}

// runner -> overlay の進捗通知。
export interface ProgressMessage {
  phase: Phase;
  message: string;
}

// @webext-core/messaging のプロトコル定義（送信先ごとの引数 / 戻り値の型）。
// 注入は injectStart → injectTrack*（track 数分）→ injectCover?（任意）→ injectFinish の順で送る。
export interface ProtocolMap {
  // background -> overlay: action click で表示状態を切り替える。
  toggleOverlay(): void;
  // overlay -> background: HTTPS page から直接読めない loopback HTTP JSON を取得する。
  fetchLocalText(request: LocalFetchRequest): LocalFetchTextResponse;
  // overlay -> background: loopback HTTP asset を1件ずつ取得・直列化する。
  fetchLocalAsset(request: LocalFetchAssetRequest): SerializedAsset;
  // overlay -> runner: テキスト / SELECT 系を一括注入し、セッションを開始する。
  injectStart(request: InjectStartRequest): void;
  // overlay -> runner: 1 track の曲ファイルを注入する。
  injectTrack(request: InjectTrackRequest): void;
  // overlay -> runner: ジャケットを注入する。
  injectCover(request: InjectCoverRequest): void;
  // overlay -> runner: AI 開示を注入してセッションを完了する。
  injectFinish(): void;
  // overlay -> runner: 進行中の注入を停止する。
  stop(): void;
  // runner -> overlay: 進捗を通知する。
  progress(message: ProgressMessage): void;
  // overlay -> background: 配信済み記録を serve token 付き POST で実行する（#1360）。
  // overlay は server state を更新する POST を直接呼ばず、background の extension origin に
  // 委譲する（ADR-0016 の書き込み境界。suno-helper の postDownloaded と同型）。
  recordRelease(payload: {
    baseUrl: string;
    record: DistrokidReleaseRecord;
  }): void;
}

export const { sendMessage, onMessage } =
  defineExtensionMessaging<ProtocolMap>();
