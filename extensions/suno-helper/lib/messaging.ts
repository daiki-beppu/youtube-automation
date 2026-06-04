// background ↔ content ↔ popup の message を @webext-core/messaging で型付けする。
// payload 定義をここに集約する (要件3)。
import { defineExtensionMessaging } from "@webext-core/messaging";

import type { PromptEntry } from "../../shared/api";
import type { ProgressPayload, SnapshotPayload } from "../../shared/constants";

interface ProtocolMap {
  /** popup → content: 連続実行を開始する。 */
  run(entries: PromptEntry[]): { ok: true };
  /** popup → content: 連続実行を中断する。 */
  stop(): { ok: true };
  /** content → popup: 進捗を通知する。 */
  progress(payload: ProgressPayload): void;
  /** popup → content: 現在の進捗スナップショットを問い合わせる (#852)。未実行は null。 */
  queryProgress(): SnapshotPayload | null;
}

export const { sendMessage, onMessage } = defineExtensionMessaging<ProtocolMap>();
