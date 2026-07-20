import type { CommunityPost } from "../../shared/api";
import {
  CommunitySubmissionUncertainError,
  type ExpectedCommunityPostState,
} from "../../shared/community-dom";
import { COMMUNITY_PHASE, type CommunityPhase } from "../../shared/constants";
import type { ProgressIndex } from "./messaging";

const REQUIRED_POST_COUNT = 3;

export interface CommunityRunnerProgress {
  index: ProgressIndex;
  message: string;
  phase: CommunityPhase;
  total: typeof REQUIRED_POST_COUNT;
}

export interface CommunityRunnerDependencies {
  attachImage(blob: Blob, filename: string): Promise<void>;
  cancelPostForm(): Promise<void>;
  clickPost(expected: ExpectedCommunityPostState): Promise<void>;
  fetchImage(baseUrl: string, index: ProgressIndex): Promise<Blob>;
  fetchPosts(baseUrl: string): Promise<CommunityPost[]>;
  openPostForm(): Promise<void>;
  openSchedulePicker(): Promise<void>;
  reportProgress(progress: CommunityRunnerProgress): Promise<void>;
  setCommunityText(text: string): Promise<void>;
  setScheduleDateTime(scheduledAt: string): Promise<void>;
}

interface PreparedPost {
  image: Blob | null;
  imageFilename: string | null;
  post: CommunityPost;
}

class CommunityRunError extends Error {
  readonly completedCount: number;
  readonly requiresReconciliation: boolean;

  constructor(
    message: string,
    completedCount: number,
    submissionUncertain: boolean,
    options?: ErrorOptions
  ) {
    const requiresReconciliation = completedCount > 0 || submissionUncertain;
    const suffix = requiresReconciliation
      ? `（${completedCount}/3 件完了。重複投稿を防ぐため、YouTube 上の予約投稿を照合してからページを再読み込みしてください）`
      : "";
    super(`${message}${suffix}`, options);
    this.name = "CommunityRunError";
    this.completedCount = completedCount;
    this.requiresReconciliation = requiresReconciliation;
  }
}

function assertNotCancelled(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw new Error("コミュニティ投稿処理を停止しました");
  }
}

function imageReference(post: CommunityPost): string | null {
  return post.image_path ?? post.image_url ?? null;
}

function imageFilename(
  reference: string,
  index: ProgressIndex,
  mimeType: string
): string {
  const withoutQuery = reference.split(/[?#]/u, 1)[0];
  const candidate = withoutQuery.split("/").at(-1)?.trim();
  if (candidate) {
    return candidate;
  }
  const extension = mimeType === "image/jpeg" ? "jpg" : "png";
  return `community-post-${index + 1}.${extension}`;
}

async function report(
  dependencies: CommunityRunnerDependencies,
  index: ProgressIndex,
  phase: CommunityPhase,
  message: string
): Promise<void> {
  await dependencies.reportProgress({
    index,
    message,
    phase,
    total: REQUIRED_POST_COUNT,
  });
}

async function processPost(
  prepared: PreparedPost,
  index: ProgressIndex,
  dependencies: CommunityRunnerDependencies,
  signal?: AbortSignal
): Promise<void> {
  const { imageFilename: attachedFilename, post } = prepared;
  let postCompleted = false;
  try {
    await prepareComposer(prepared, index, dependencies, signal);
    assertNotCancelled(signal);
    await report(
      dependencies,
      index,
      COMMUNITY_PHASE.POSTING,
      "予約投稿を確定中"
    );
    await dependencies.clickPost({
      imageFilename: attachedFilename,
      scheduledAt: post.scheduled_at,
      text: post.text,
    });
    postCompleted = true;
    await report(dependencies, index, COMMUNITY_PHASE.DONE, "完了");
  } catch (error) {
    await handleProcessFailure(error, index, dependencies, postCompleted);
  }
}

async function prepareComposer(
  prepared: PreparedPost,
  index: ProgressIndex,
  dependencies: CommunityRunnerDependencies,
  signal?: AbortSignal
): Promise<void> {
  assertNotCancelled(signal);
  await dependencies.openPostForm();
  await report(dependencies, index, COMMUNITY_PHASE.INJECTING, "本文を入力中");
  await dependencies.setCommunityText(prepared.post.text);
  assertNotCancelled(signal);
  if (prepared.image && prepared.imageFilename) {
    await report(
      dependencies,
      index,
      COMMUNITY_PHASE.UPLOADING_IMAGE,
      "画像を添付中"
    );
    await dependencies.attachImage(prepared.image, prepared.imageFilename);
  }
  assertNotCancelled(signal);
  await report(
    dependencies,
    index,
    COMMUNITY_PHASE.SCHEDULING,
    "予約日時を設定中"
  );
  await dependencies.openSchedulePicker();
  await dependencies.setScheduleDateTime(prepared.post.scheduled_at);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function handleProcessFailure(
  error: unknown,
  index: ProgressIndex,
  dependencies: CommunityRunnerDependencies,
  postCompleted: boolean
): Promise<never> {
  const submissionUncertain =
    error instanceof CommunitySubmissionUncertainError;
  if (!(submissionUncertain || postCompleted)) {
    try {
      await dependencies.cancelPostForm();
    } catch (cleanupError) {
      throw new CommunityRunError(
        `${errorMessage(error)} / composer cleanup failed: ${errorMessage(cleanupError)}`,
        index,
        true,
        { cause: cleanupError }
      );
    }
  }
  throw new CommunityRunError(
    errorMessage(error),
    index + (postCompleted ? 1 : 0),
    submissionUncertain,
    { cause: error }
  );
}

async function preparePosts(
  posts: CommunityPost[],
  baseUrl: string,
  dependencies: CommunityRunnerDependencies,
  signal?: AbortSignal
): Promise<PreparedPost[]> {
  const prepared: PreparedPost[] = [];
  for (const index of [0, 1, 2] as const) {
    assertNotCancelled(signal);
    const post = posts[index];
    const reference = imageReference(post);
    const image = reference
      ? await dependencies.fetchImage(baseUrl, index)
      : null;
    prepared.push({
      image,
      imageFilename:
        reference && image ? imageFilename(reference, index, image.type) : null,
      post,
    });
  }
  return prepared;
}

export async function runCommunityPosts(
  baseUrl: string,
  dependencies: CommunityRunnerDependencies,
  signal?: AbortSignal
): Promise<void> {
  assertNotCancelled(signal);
  const posts = await dependencies.fetchPosts(baseUrl);
  if (posts.length !== REQUIRED_POST_COUNT) {
    throw new Error(
      `community runner requires exactly 3 posts: actual=${posts.length}`
    );
  }
  const prepared = await preparePosts(posts, baseUrl, dependencies, signal);
  for (const index of [0, 1, 2] as const) {
    await processPost(prepared[index], index, dependencies, signal);
  }
}
