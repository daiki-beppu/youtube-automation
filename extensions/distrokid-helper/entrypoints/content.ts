// distrokid.com/new で起動する content script。
//
// popup からの inject 指示を受け、静的プロファイル + 動的データのテキスト/SELECT を注入し、
// popup が fetch 済みの曲 / ジャケット（直列化済み）を File へ復元して <input type=file> にセットする。
// asset の fetch を popup 側で行う理由は asset-transfer.ts を参照（content からの fetch は CORS で遮断）。
// AI 開示モーダル（Suno 楽曲は通過必須）は MutationObserver で展開を待ってから checkbox を注入する。
// 「続ける」等の送信系操作は一切行わない（規約遵守・スコープ外）。

import { decodeAsset } from "@/lib/asset-transfer";
import {
  assertNewRelease,
  injectAiDisclosure,
  injectAlbumTitle,
  injectCover,
  injectProfile,
  injectReleaseDate,
  injectSongwriter,
  injectTrackFile,
  injectTrackTitle,
  resolveTrackUuids,
} from "@/lib/distrokid-injector";
import { onMessage, sendMessage, PHASES } from "@/lib/messaging";
import type { InjectRequest, Phase } from "@/lib/messaging";

export default defineContentScript({
  matches: ["*://*.distrokid.com/new*"],
  main() {
    // 停止フラグ。popup の stop で立て、注入の各境界で確認する。
    let stopped = false;

    const report = (phase: Phase, message: string) =>
      sendMessage("progress", { phase, message });

    onMessage("stop", () => {
      stopped = true;
    });

    onMessage("inject", async ({ data }) => {
      stopped = false;
      try {
        await runInjection(data, () => stopped, report);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        report(PHASES.ERROR, message);
      }
    });
  },
});

type Reporter = (phase: Phase, message: string) => void;

async function runInjection(
  request: InjectRequest,
  isStopped: () => boolean,
  report: Reporter,
): Promise<void> {
  const { payload, trackAssets, coverAsset } = request;
  const { profile, release } = payload;

  // 新規リリース前提を最初に assert（過去公開対応はスコープ外）。
  assertNewRelease(document);

  report(PHASES.INJECTING, "プロファイルを注入中");
  injectProfile(document, profile);
  injectAlbumTitle(document, release.album_title);
  injectReleaseDate(document, release.release_date);

  // track UUID を DOM order で解決し、全 track を index 順に注入する（先頭のみ撤廃）。
  const uuids = resolveTrackUuids(document);
  if (uuids.length !== release.tracks.length) {
    throw new Error(
      `track 数が DOM と一致しません: DOM=${uuids.length}, payload=${release.tracks.length}`,
    );
  }

  for (let i = 0; i < release.tracks.length; i += 1) {
    if (isStopped()) {
      report(PHASES.STOPPED, "停止しました");
      return;
    }
    const track = release.tracks[i];
    const index1 = i + 1;

    injectTrackTitle(document, uuids[i], track.title);
    if (profile.songwriter !== null) {
      injectSongwriter(document, index1, profile.songwriter);
    }

    const asset = trackAssets[i];
    report(PHASES.INJECTING, `曲ファイルを注入中: ${asset.filename}`);
    injectTrackFile(document, index1, decodeAsset(asset));
  }

  if (!isStopped() && coverAsset !== null) {
    report(PHASES.INJECTING, `ジャケットを注入中: ${coverAsset.filename}`);
    injectCover(document, decodeAsset(coverAsset));
  }

  if (!isStopped() && profile.ai_disclosure.enabled) {
    report(PHASES.INJECTING, "AI 開示モーダルを注入中");
    await injectAiDisclosure(document, profile.ai_disclosure);
  }

  if (isStopped()) {
    report(PHASES.STOPPED, "停止しました");
    return;
  }
  report(PHASES.DONE, "注入が完了しました。内容を確認して手動で続行してください");
}
