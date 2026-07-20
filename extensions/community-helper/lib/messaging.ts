import { defineExtensionMessaging } from "@webext-core/messaging";

import type { CommunityPost, CompatibilityResult } from "../../shared/api";
import type { SerializedAsset } from "../../shared/asset-transfer";
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
  total: 3;
}

export interface ErrorMessage {
  message: string;
}

export interface CommunityImageRequest extends RunRequest {
  index: ProgressIndex;
}

export interface ProtocolMap {
  /** Background → overlay: action click で表示状態を切り替える。 */
  toggleOverlay(): void;
  /** Overlay → background: extension origin から /version を確認する。 */
  checkCompatibility(request: CompatibilityRequest): CompatibilityResult;
  /** Overlay → background → sender tab の YouTube posts runner. */
  run(request: RunRequest): void;
  /** Overlay → background → sender tab の YouTube posts runner. */
  stop(): void;
  /** Content → background: extension origin で投稿 JSON を取得する。 */
  fetchCommunityPosts(request: RunRequest): CommunityPost[];
  /** Content → background: extension origin で画像を取得する。 */
  fetchCommunityImage(request: CommunityImageRequest): SerializedAsset;
  /** Background → sender tab overlay. */
  progress(message: ProgressMessage): void;
  /** Background → sender tab overlay. */
  error(message: ErrorMessage): void;
  /** Content → background. Public progress is emitted after relay. */
  contentProgress(message: ProgressMessage): void;
  /** Content → background. Public error is emitted after relay. */
  contentError(message: ErrorMessage): void;
}

export const { onMessage, sendMessage } =
  defineExtensionMessaging<ProtocolMap>();
