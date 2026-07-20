// overlay 側の per-track 分割注入オーケストレーション（#871）。
//
// injectStart → injectTrack*（track 数分）→ injectCover?（任意）→ injectFinish を逐次送る
// 制御フローと停止境界（停止 race 修正の本体）を、transport（@webext-core/messaging /
// fetchAsset）と React state から切り離して単体検証可能にする。content 側 InjectSession の
// Injector と対称に、送信・取得・停止判定を InjectChannel として外から渡す（content は実
// transport を、テストは fake を渡す）。
//
// asset は 1 track ずつ fetch → 送信 → 解放を逐次実行し、overlay memory を track 数に対し
// O(1) に保つ。全 track を 1 メッセージで送ると Base64 化後に 64MiB 上限を超えるため分割する。

import type { SerializedAsset } from "./asset-transfer";
import type { ReleasePayload } from "./types";

// 注入オーケストレーションの境界（transport / 停止判定 / 進捗表示）。
export interface InjectChannel {
  // serverUrl 上の 1 asset を overlay から取得して直列化する。
  fetchAsset(assetPath: string, filename: string): Promise<SerializedAsset>;
  // content へ注入セッションを開始する（テキスト / SELECT 系のみ、asset なし）。
  start(payload: ReleasePayload): Promise<void>;
  // content へ 1 track の曲ファイルを注入する。
  track(trackIndex: number, asset: SerializedAsset): Promise<void>;
  // content へジャケットを注入する。
  cover(asset: SerializedAsset): Promise<void>;
  // content の注入セッションを完了する（AI 開示注入 + DONE）。
  finish(): Promise<void>;
  // 進捗メッセージを UI へ反映する。
  setMessage(message: string): void;
  // 停止要求の確認（ループ境界・send 直前で参照する）。
  isStopped(): boolean;
}

// 注入を逐次実行する。停止要求はループ境界と各 send 直前で確認し、確認後は以降の送信を
// 打ち切る（return）。fetch 中の停止に備えて send 直前で再チェックするのが停止 race 修正の核。
export async function runInjection(
  payload: ReleasePayload,
  channel: InjectChannel
): Promise<void> {
  const { release } = payload;
  await channel.start(payload);

  for (let i = 0; i < release.tracks.length; i += 1) {
    if (channel.isStopped()) {
      return;
    }
    const track = release.tracks[i];
    channel.setMessage(`アセットを取得中: ${track.filename}`);
    const asset = await channel.fetchAsset(track.asset_path, track.filename);
    // fetch 中に停止された場合、content は既に session を破棄している。ここで送ると
    // injectTrack が null セッションへ届き fail-loud で throw し、STOPPED を ERROR で
    // 上書きしてしまうため send 直前に再チェックする。
    if (channel.isStopped()) {
      return;
    }
    await channel.track(i, asset);
  }

  if (channel.isStopped()) {
    return;
  }
  if (release.cover !== null) {
    channel.setMessage(`アセットを取得中: ${release.cover.filename}`);
    const asset = await channel.fetchAsset(
      release.cover.asset_path,
      release.cover.filename
    );
    // track ループと同様、fetch 中の停止に備えて send 直前に再チェックする。
    if (channel.isStopped()) {
      return;
    }
    await channel.cover(asset);
  }

  if (channel.isStopped()) {
    return;
  }
  await channel.finish();
}
