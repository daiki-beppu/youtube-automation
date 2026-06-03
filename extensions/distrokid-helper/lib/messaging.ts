// background ↔ popup ↔ content の型付きメッセージング（@webext-core/messaging）。
//
// popup から content へ「注入開始 / 停止」を送り、content から popup へ「進捗」を返す。
// 3 者が解釈を共有する進捗フェーズは PHASES で固定する（状態の正規化）。

import { defineExtensionMessaging } from "@webext-core/messaging";
import type { SerializedAsset } from "./asset-transfer";
import type { ReleasePayload } from "./types";

// 注入フローの進捗フェーズ（content -> popup の PROGRESS で使用）。
// 値は popup の表示分岐キーになるため一意な文字列で固定する。
export const PHASES = {
  INJECTING: "injecting",
  DONE: "done",
  ERROR: "error",
  STOPPED: "stopped",
} as const;

export type Phase = (typeof PHASES)[keyof typeof PHASES];

// popup -> content の注入指示。
// asset（曲 / ジャケット）は popup 側で fetch 済みのものを直列化して渡す
// （content からの fetch は CORS で遮断されるため。asset-transfer.ts 参照）。
// trackAssets は payload.release.tracks と同順・同数（全 track を index 順に注入する。#813）。
// fetchAsset は取得失敗時に throw する（null を返さない）ため track 要素に欠落は生じない。
// cover は config 上 optional なため不在時のみ coverAsset が null。
export interface InjectRequest {
  payload: ReleasePayload;
  trackAssets: SerializedAsset[];
  coverAsset: SerializedAsset | null;
}

// content -> popup の進捗通知。
export interface ProgressMessage {
  phase: Phase;
  message: string;
}

// @webext-core/messaging のプロトコル定義（送信先ごとの引数 / 戻り値の型）。
export interface ProtocolMap {
  // popup -> content: テキスト + ファイルを注入する。
  inject(request: InjectRequest): void;
  // popup -> content: 進行中の注入を停止する。
  stop(): void;
  // content -> popup: 進捗を通知する。
  progress(message: ProgressMessage): void;
}

export const { sendMessage, onMessage } = defineExtensionMessaging<ProtocolMap>();
