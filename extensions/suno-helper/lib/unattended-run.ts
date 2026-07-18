import type { CollectionSummary } from "../../shared/api";
import {
  CLIPS_PER_REQUEST,
  PHASE,
  type ProgressPayload,
} from "../../shared/constants";
import type { ResumeState } from "./resume-state";
import type { DownloadFormat } from "./storage";

const LAUNCH_PREFIX = "#suno-helper-unattended=";
const DOWNLOAD_FORMATS = new Set<DownloadFormat>(["mp3", "m4a", "wav"]);

export interface UnattendedRunLimits {
  /** 1回の定期実行で新たに処理する entry 数。残りは checkpoint へ繰り越す。 */
  maxEntries: number;
  /** Suno に同時投入できる request 数（1 request = 2 clips）。 */
  maxConcurrentGenerations: number;
  /** entry 単位の一時失敗を再試行する回数。 */
  maxRetries: number;
}

export interface UnattendedRunRequest {
  version: 1;
  requestId: string;
  baseUrl: string;
  collectionId: string;
  entryIndices?: number[];
  downloadFormat: DownloadFormat;
  limits: UnattendedRunLimits;
}

export interface UnattendedLaunchEnvelope {
  version: 1;
  baseUrl: string;
  nonce: string;
}

export type UnattendedStopReason =
  | "login-required"
  | "captcha-required"
  | "cost-confirmation-required"
  | "ui-incompatible"
  | "existing-playlist"
  | "run-error";

export type UnattendedRunStatus =
  | "running"
  | "checkpoint"
  | "manual-intervention"
  | "completed";

export interface UnattendedRunState {
  requestId: string;
  collectionId: string;
  status: UnattendedRunStatus;
  checkpoint: "entries" | "playlist" | "download" | "complete";
  pendingEntryIndices: number[];
  stopReason?: UnattendedStopReason;
  requiredAction?: string;
  message?: string;
  updatedAt: number;
}

export type UnattendedRunPlan =
  | { kind: "complete"; reason: "already-downloaded" }
  | {
      kind: "manual-intervention";
      reason: UnattendedStopReason;
      requiredAction: string;
    }
  | {
      kind: "retry-playlist";
      submittedClipIds: string[];
      expectedClipCount: number;
    }
  | {
      kind: "retry-download";
      submittedClipIds: string[];
      expectedClipCount: number;
    }
  | {
      kind: "run";
      indices: number[];
      deferredIndices: number[];
      previousSubmittedClipIds: string[];
      playlistExpectedClipCount: number | undefined;
    };

export function hasCompleteUnattendedArtifacts(
  collection: CollectionSummary,
  minimumExpectedFileCount: number
): boolean {
  return (
    collection.status === "downloaded" &&
    collection.music_downloaded === true &&
    typeof collection.expected_file_count === "number" &&
    collection.expected_file_count >= minimumExpectedFileCount &&
    collection.downloaded_count >= collection.expected_file_count &&
    typeof collection.suno_playlist_url === "string" &&
    collection.suno_playlist_url.length > 0
  );
}

function assertRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be object`);
  }
  return value as Record<string, unknown>;
}

function nonEmptyString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${field} must be non-empty string`);
  }
  return value;
}

function boundedInteger(
  value: unknown,
  field: string,
  minimum: number,
  maximum: number
): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < minimum ||
    value > maximum
  ) {
    throw new Error(`${field} must be integer ${minimum}..${maximum}`);
  }
  return value;
}

function normalizeIndices(value: unknown): number[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("entryIndices must be non-empty integer array");
  }
  const seen = new Set<number>();
  return value.map((item, index) => {
    const normalized = boundedInteger(
      item,
      `entryIndices[${index}]`,
      0,
      Number.MAX_SAFE_INTEGER
    );
    if (seen.has(normalized)) {
      throw new Error(`entryIndices[${index}] must be unique`);
    }
    seen.add(normalized);
    return normalized;
  });
}

function assertLoopbackBaseUrl(value: unknown): string {
  const raw = nonEmptyString(value, "baseUrl");
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("baseUrl must be URL");
  }
  const hostname = url.hostname.toLowerCase();
  const isLoopback =
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname.endsWith(".localhost");
  if (url.protocol !== "http:" || !isLoopback || url.username || url.password) {
    throw new Error("baseUrl must be an unauthenticated loopback http URL");
  }
  url.pathname = url.pathname.replace(/\/+$/, "");
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const bytes = Uint8Array.from(atob(padded), (character) =>
    character.charCodeAt(0)
  );
  return new TextDecoder().decode(bytes);
}

export function parseUnattendedLaunchHash(
  hash: string
): UnattendedLaunchEnvelope | null {
  if (!hash.startsWith(LAUNCH_PREFIX)) return null;
  const encoded = hash.slice(LAUNCH_PREFIX.length);
  let value: unknown;
  try {
    value = JSON.parse(decodeBase64Url(encoded));
  } catch (error) {
    throw new Error("unattended launch payload must be base64url JSON", {
      cause: error,
    });
  }
  const record = assertRecord(value, "unattended launch envelope");
  if (record.version !== 1) {
    throw new Error("unattended launch envelope.version must be 1");
  }
  const nonce = nonEmptyString(record.nonce, "nonce");
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(nonce)) {
    throw new Error("nonce must be base64url token");
  }
  return { version: 1, baseUrl: assertLoopbackBaseUrl(record.baseUrl), nonce };
}

export function assertUnattendedRunRequest(
  value: unknown
): UnattendedRunRequest {
  const record = assertRecord(value, "unattended request");
  if (record.version !== 1) {
    throw new Error("unattended request.version must be 1");
  }
  const downloadFormat = nonEmptyString(
    record.downloadFormat,
    "downloadFormat"
  ) as DownloadFormat;
  if (!DOWNLOAD_FORMATS.has(downloadFormat)) {
    throw new Error("downloadFormat must be mp3, m4a, or wav");
  }
  const limits = assertRecord(record.limits, "limits");
  return {
    version: 1,
    requestId: nonEmptyString(record.requestId, "requestId"),
    baseUrl: assertLoopbackBaseUrl(record.baseUrl),
    collectionId: nonEmptyString(record.collectionId, "collectionId"),
    entryIndices: normalizeIndices(record.entryIndices),
    downloadFormat,
    limits: {
      maxEntries: boundedInteger(
        limits.maxEntries,
        "limits.maxEntries",
        1,
        100
      ),
      maxConcurrentGenerations: boundedInteger(
        limits.maxConcurrentGenerations,
        "limits.maxConcurrentGenerations",
        1,
        10
      ),
      maxRetries: boundedInteger(limits.maxRetries, "limits.maxRetries", 0, 5),
    },
  };
}

function requestedIndices(
  request: UnattendedRunRequest,
  entryCount: number
): number[] {
  const indices =
    request.entryIndices ??
    Array.from({ length: entryCount }, (_, index) => index);
  for (const index of indices) {
    if (index >= entryCount) {
      throw new Error(`entry index ${index} is outside collection entry range`);
    }
  }
  return indices;
}

// fallow-ignore-next-line complexity
export function planUnattendedRun(options: {
  request: UnattendedRunRequest;
  collection: CollectionSummary;
  entryCount: number;
  resumeState: ResumeState | null;
}): UnattendedRunPlan {
  const { request, collection, entryCount } = options;
  if (collection.id !== request.collectionId) {
    throw new Error("collection does not match unattended request");
  }
  const resume =
    options.resumeState?.collectionId === request.collectionId
      ? options.resumeState
      : null;
  const hasPendingResumeEntries =
    (resume?.failedIndices?.length ?? 0) > 0 ||
    (resume?.remainingIndices?.length ?? 0) > 0 ||
    (resume !== null && resume.failedIndex < entryCount);
  if (
    hasCompleteUnattendedArtifacts(
      collection,
      entryCount * CLIPS_PER_REQUEST
    ) &&
    !hasPendingResumeEntries
  ) {
    return { kind: "complete", reason: "already-downloaded" };
  }
  if (collection.status === "downloaded" && !hasPendingResumeEntries) {
    return {
      kind: "manual-intervention",
      reason: "run-error",
      requiredAction:
        "server の厳格完了条件（期待音源数・playlist URL・assets.music_downloaded）を満たしていません。成果物を確認してから再開してください。新規生成は開始していません。",
    };
  }

  const observed = [...(resume?.submittedClipIds ?? [])];
  if (
    resume?.failedIndex === entryCount &&
    (resume.failedIndices?.length ?? 0) === 0 &&
    observed.length > 0 &&
    resume.playlistExpectedClipCount !== undefined &&
    resume.playlistExpectedClipCount >= entryCount * CLIPS_PER_REQUEST
  ) {
    if (
      !collection.suno_playlist_url &&
      !Array.isArray(resume.playlistUrlsBeforeCreate)
    ) {
      return {
        kind: "manual-intervention",
        reason: "existing-playlist",
        requiredAction:
          "playlist 作成前 baseline のない旧 checkpoint のため自動再作成できません。同名 playlist の有無と clip を確認してください。",
      };
    }
    return {
      kind: collection.suno_playlist_url ? "retry-download" : "retry-playlist",
      submittedClipIds: observed,
      expectedClipCount: resume.playlistExpectedClipCount,
    };
  }
  if (collection.suno_playlist_url) {
    return {
      kind: "manual-intervention",
      reason: "existing-playlist",
      requiredAction:
        "既存 playlist の clip を選択して Download 再開を実行してください。新規生成は開始していません。",
    };
  }

  const requested = requestedIndices(request, entryCount);
  const requestedSet = new Set(requested);
  const failed = (resume?.failedIndices ?? []).filter((index) =>
    requestedSet.has(index)
  );
  const remaining = (resume?.remainingIndices ?? []).filter((index) =>
    requestedSet.has(index)
  );
  const candidates =
    failed.length > 0 || remaining.length > 0
      ? Array.from(new Set([...failed, ...remaining]))
      : resume && resume.failedIndex < entryCount
        ? requested.filter((index) => index >= resume.failedIndex)
        : resume?.failedIndex === entryCount
          ? []
          : requested;
  for (const index of candidates) {
    if (index < 0 || index >= entryCount) {
      throw new Error(
        `resume index ${index} is outside collection entry range`
      );
    }
  }
  if (candidates.length === 0) {
    return {
      kind: "manual-intervention",
      reason: "run-error",
      requiredAction:
        "再開に必要な clip ID がありません。Suno の生成履歴を確認して手動で再開してください。新規生成は開始していません。",
    };
  }
  return {
    kind: "run",
    indices: candidates.slice(0, request.limits.maxEntries),
    deferredIndices: candidates.slice(request.limits.maxEntries),
    previousSubmittedClipIds: observed,
    playlistExpectedClipCount: resume?.playlistExpectedClipCount,
  };
}

export function classifyUnattendedStop(message: string): UnattendedStopReason {
  const normalized = message.toLowerCase();
  if (/sign[ -]?in|log[ -]?in|ログイン/.test(normalized)) {
    return "login-required";
  }
  if (/captcha|bot check/.test(normalized)) {
    return "captcha-required";
  }
  if (
    /credit|token|payment|purchase|subscribe|upgrade|課金|料金|購入/.test(
      normalized
    )
  ) {
    return "cost-confirmation-required";
  }
  if (/見つかりません|selector|ui change|ui 変更|表示ビュー/.test(normalized)) {
    return "ui-incompatible";
  }
  return "run-error";
}

function requiredActionFor(reason: UnattendedStopReason): string {
  switch (reason) {
    case "login-required":
      return "Suno に手動でログインしてから再開してください。";
    case "captcha-required":
      return "Suno の CAPTCHA を手動で解決してから再開してください。";
    case "cost-confirmation-required":
      return "料金・credit 消費内容を確認し、許可する場合だけ手動で承認して再開してください。";
    case "ui-incompatible":
      return "Suno UI と拡張の互換性を確認し、拡張を更新してから再開してください。";
    case "existing-playlist":
      return "既存 playlist の clip を選択して Download 再開を実行してください。";
    case "run-error":
      return "エラー内容を確認し、原因を解消してから再開してください。";
    default: {
      const exhaustive: never = reason;
      throw new Error(`unknown unattended stop reason: ${exhaustive}`);
    }
  }
}

export function createUnattendedManualState(options: {
  request: UnattendedRunRequest;
  reason: UnattendedStopReason;
  message: string;
  checkpoint?: UnattendedRunState["checkpoint"];
  pendingEntryIndices?: number[];
  now: number;
}): UnattendedRunState {
  return {
    requestId: options.request.requestId,
    collectionId: options.request.collectionId,
    status: "manual-intervention",
    checkpoint: options.checkpoint ?? "entries",
    pendingEntryIndices: [...(options.pendingEntryIndices ?? [])],
    stopReason: options.reason,
    requiredAction: requiredActionFor(options.reason),
    message: options.message,
    updatedAt: options.now,
  };
}

function checkpointFor(
  progress: ProgressPayload
): UnattendedRunState["checkpoint"] {
  if (progress.phase === PHASE.ADDING_TO_PLAYLIST) return "playlist";
  if (progress.phase === PHASE.DOWNLOADING) return "download";
  if (progress.phase === PHASE.FINISHED) return "complete";
  return "entries";
}

export function nextUnattendedRunState(options: {
  request: UnattendedRunRequest;
  progress: ProgressPayload;
  deferredIndices: number[];
  now: number;
  verifiedComplete?: boolean;
}): UnattendedRunState {
  const { request, progress, deferredIndices, now } = options;
  const common = {
    requestId: request.requestId,
    collectionId: request.collectionId,
    checkpoint: checkpointFor(progress),
    pendingEntryIndices: [...deferredIndices],
    ...(progress.message ? { message: progress.message } : {}),
    updatedAt: now,
  };
  if (
    progress.phase === PHASE.FINISHED &&
    deferredIndices.length === 0 &&
    options.verifiedComplete === true
  ) {
    return { ...common, status: "completed", checkpoint: "complete" };
  }
  if (progress.phase === PHASE.FINISHED) {
    return {
      ...common,
      status: "checkpoint",
      checkpoint: deferredIndices.length > 0 ? "entries" : "download",
      requiredAction:
        "server 上の音源・playlist URL・downloaded 状態を確認して再開します。",
    };
  }
  if (progress.phase === PHASE.STOPPED) {
    return {
      ...common,
      status: "checkpoint",
      checkpoint: "entries",
      requiredAction: progress.message?.includes("entry 上限")
        ? "次回の定期実行で未完了 entry から再開します。"
        : "次回の定期実行で checkpoint から再開します。",
    };
  }
  if (progress.phase === PHASE.ERROR) {
    const stopReason = classifyUnattendedStop(progress.message ?? "run error");
    return {
      ...common,
      status: "manual-intervention",
      stopReason,
      requiredAction: requiredActionFor(stopReason),
    };
  }
  return { ...common, status: "running" };
}
