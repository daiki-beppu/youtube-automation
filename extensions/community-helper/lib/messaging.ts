import { defineExtensionMessaging } from "@webext-core/messaging";

import type { CompatibilityResult } from "../../shared/api";
import type { CommunityPhase } from "../../shared/constants";

export type ProgressIndex = 0 | 1 | 2;

export interface RunRequest {
  baseUrl: string;
}

export interface CompatibilityRequest extends RunRequest {
  extensionVersion: string;
}

export interface ProgressMessage {
  index: ProgressIndex;
  phase: CommunityPhase;
  message: string;
}

export interface ProtocolMap {
  /** Popup → background → Studio content: page-origin CORS で /version を確認する。 */
  checkCompatibility(request: CompatibilityRequest): CompatibilityResult;
  /** Popup → background → active Studio content script. */
  run(request: RunRequest): void;
  /** Popup → background → active Studio content script. */
  stop(): void;
  /** Background → Popup. */
  progress(message: ProgressMessage): void;
  /** Content → background. Public progress is emitted after relay. */
  contentProgress(message: ProgressMessage): void;
}

export const { onMessage, sendMessage } =
  defineExtensionMessaging<ProtocolMap>();
