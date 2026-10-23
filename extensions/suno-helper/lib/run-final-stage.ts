/** 連続実行がどの phase まで進んで FINISHED になるか。download は playlist の clip ID を前提にする。 */
export type RunFinalStage = "generation" | "playlist" | "download";

export function resolveRunFinalStage(settings: {
  playlistEnabled: boolean;
  downloadEnabled: boolean;
}): RunFinalStage {
  if (!settings.playlistEnabled) {
    return "generation";
  }
  return settings.downloadEnabled ? "download" : "playlist";
}

const FINAL_STAGE_COMPLETION_MESSAGES: Record<
  RunFinalStage,
  string | undefined
> = {
  generation:
    "playlist 追加とダウンロードは未実行。Suno から手動で取得して 02-Individual-music/ へ配置してください。",
  playlist:
    "ダウンロード未実行。Suno から手動で取得して 02-Individual-music/ へ配置してください。",
  download: undefined,
};

export function finalStageCompletionMessage(finalStage: RunFinalStage): {
  message?: string;
} {
  const message = FINAL_STAGE_COMPLETION_MESSAGES[finalStage];
  return message === undefined ? {} : { message };
}
