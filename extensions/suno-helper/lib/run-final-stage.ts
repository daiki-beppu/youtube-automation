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
