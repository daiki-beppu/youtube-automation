// run 一式完了後のタブリロード (#1411)。
//
// Suno は playlist 追加後も multi-select 状態を内部 state で保持するため、dir mode の
// 同一タブ連続実行では前回 run の選択（stale selection）が次 run の Cmd+P に混入し、
// playlist が run ごとに累積汚染される。DOM 上での増分解除ではなく、run 一式完了時に
// ページごとリロードして Suno 内部 state を丸ごと破棄する方式を採る（単純・堅牢）。
//
// 呼び出し側の順序契約: resume state の消去を await してから呼ぶこと。逆順だと
// リロード後の ResumeBanner が「中断からの再開」と誤判定する（#1321 との衝突）。

/** FINISHED progress message が popup / background へ届くのを待つ猶予 (ms)。 */
const RUN_COMPLETE_RELOAD_DELAY_MS = 1_000;

let pendingReloadTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * 遅延後にタブをリロードする。即時 reload だと直前に送った FINISHED progress の
 * 配送前に message port が閉じうるため、短い猶予を挟む。
 */
export function scheduleRunCompleteReload(): void {
  cancelScheduledRunCompleteReload();
  pendingReloadTimer = setTimeout(() => {
    pendingReloadTimer = null;
    globalThis.location.reload();
  }, RUN_COMPLETE_RELOAD_DELAY_MS);
}

/**
 * 保留中の完了時リロードを取り消す。FINISHED 直後の猶予中に次の run / retry が
 * 受理された場合、リロードがその新 run を巻き添えに殺すのを防ぐ（STOPPED/ERROR も
 * resume state も残らない無痕跡死になるため）。取り消しで残る stale selection は
 * Cmd+P 前ガードが検知する。
 */
export function cancelScheduledRunCompleteReload(): void {
  if (pendingReloadTimer !== null) {
    clearTimeout(pendingReloadTimer);
    pendingReloadTimer = null;
  }
}
