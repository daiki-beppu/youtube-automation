import { decodeAsset } from "../../shared/asset-transfer";
import {
  attachImage,
  cancelCommunityPostForm,
  clickPost,
  openCommunityPostForm,
  openSchedulePicker,
  setCommunityText,
  setScheduleDateTime,
} from "../../shared/community-dom";
import { MANIFEST_CONTENT_SCRIPT_MATCHES } from "../lib/manifest";
import { onMessage, sendMessage } from "../lib/messaging";
import { runCommunityPosts } from "../lib/runner";

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function needsReconciliation(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "requiresReconciliation" in error &&
    error.requiresReconciliation === true
  );
}

export default defineContentScript({
  matches: [...MANIFEST_CONTENT_SCRIPT_MATCHES],
  main() {
    let controller: AbortController | null = null;
    let restartBlockedReason: string | null = null;
    onMessage("run", async ({ data }) => {
      if (restartBlockedReason) {
        throw new Error(restartBlockedReason);
      }
      if (controller) {
        throw new Error("コミュニティ投稿処理はすでに実行中です");
      }
      controller = new AbortController();
      try {
        await runCommunityPosts(
          data.baseUrl,
          {
            attachImage: (blob, filename) => attachImage(blob, filename),
            cancelPostForm: () => cancelCommunityPostForm(),
            clickPost: (expected) => clickPost(expected),
            fetchImage: async (baseUrl, index) =>
              decodeAsset(
                await sendMessage("fetchCommunityImage", { baseUrl, index })
              ),
            fetchPosts: (baseUrl) =>
              sendMessage("fetchCommunityPosts", { baseUrl }),
            openPostForm: () => openCommunityPostForm(),
            openSchedulePicker: () => openSchedulePicker(),
            reportProgress: (progress) =>
              sendMessage("contentProgress", progress),
            setCommunityText: (text) => setCommunityText(text),
            setScheduleDateTime: (scheduledAt) =>
              setScheduleDateTime(scheduledAt),
          },
          controller.signal
        );
        restartBlockedReason =
          "このページでは3件の予約投稿が完了済みです。重複投稿を防ぐため、次の batch はページを再読み込みしてから実行してください";
      } catch (error) {
        if (needsReconciliation(error)) {
          restartBlockedReason =
            "途中まで確定した予約投稿があります。YouTube 上で照合してからページを再読み込みしてください";
        }
        await sendMessage("contentError", { message: messageFromError(error) });
        throw error;
      } finally {
        controller = null;
      }
    });
    onMessage("stop", () => controller?.abort());
  },
});
