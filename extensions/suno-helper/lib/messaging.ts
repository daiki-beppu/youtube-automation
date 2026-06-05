// background ↔ content ↔ popup の message を @webext-core/messaging で型付けする。
// payload 定義をここに集約する (要件3)。
import { defineExtensionMessaging } from "@webext-core/messaging";

import type { PromptEntry } from "../../shared/api";
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
  | { entries: PromptEntry[]; playlistName?: string; range?: RunRange; collectionId?: string };

interface ProtocolMap {
  /** popup → content: 連続実行を開始する。 */
  run(payload: RunPayload): { ok: true };
  /** popup → content: 連続実行を中断する。 */
  stop(): { ok: true };
  /** content → popup: 進捗を通知する。 */
  progress(payload: ProgressPayload): void;
  /** popup → content: 現在の進捗スナップショットを問い合わせる (#852)。未実行は null。 */
  queryProgress(): SnapshotPayload | null;
}

export const { sendMessage, onMessage } = defineExtensionMessaging<ProtocolMap>();
