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
export const RUN_COMPLETE_RELOAD_DELAY_MS = 1_000;

/**
 * 遅延後にタブをリロードする。即時 reload だと直前に送った FINISHED progress の
 * 配送前に message port が閉じうるため、短い猶予を挟む。
 */
export function scheduleRunCompleteReload(delayMs: number = RUN_COMPLETE_RELOAD_DELAY_MS): void {
  setTimeout(() => {
    globalThis.location.reload();
  }, delayMs);
}
