// distrokid.com/new で起動する content script。
//
// popup からの inject 指示を受け、静的プロファイル + 動的データのテキストを注入し、
// popup が fetch 済みの曲 / ジャケット（直列化済み）を File へ復元して <input type=file> にセットする。
// asset の fetch を popup 側で行う理由は asset-transfer.ts を参照（content からの fetch は CORS で遮断）。
// 「続ける」等の送信系操作は一切行わない（規約遵守・要件 #7）。

import { decodeAsset, type SerializedAsset } from "@/lib/asset-transfer";
import {
  FieldNotFoundError,
  FILE_SELECTORS,
  injectAll,
  injectFile,
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
  const { payload, trackAsset, coverAsset } = request;

  report(PHASES.INJECTING, "テキストフィールドを注入中");
  injectAll(document, payload);

  if (!isStopped() && trackAsset !== null) {
    const trackCount = payload.release.tracks.length;
    if (trackCount > 1) {
      report(
        PHASES.INJECTING,
        `複数トラック (${trackCount} 件) のうち先頭のみ注入します`,
      );
    }
    injectAssetFile(FILE_SELECTORS.song_file, trackAsset, "曲ファイル", report);
  }

  if (!isStopped() && coverAsset !== null) {
    injectAssetFile(FILE_SELECTORS.cover_file, coverAsset, "ジャケット", report);
  }

  if (isStopped()) {
    report(PHASES.STOPPED, "停止しました");
    return;
  }
  report(PHASES.DONE, "注入が完了しました。内容を確認して手動で続行してください");
}

// セレクタで <input type=file> を解決し、直列化 asset を File へ復元して注入する。
// 未検出は silent skip せず fail-loud（FieldNotFoundError）。
function injectAssetFile(
  selector: string,
  asset: SerializedAsset,
  label: string,
  report: Reporter,
): void {
  const input = document.querySelector<HTMLInputElement>(selector);
  if (input === null) {
    throw new FieldNotFoundError(selector);
  }
  report(PHASES.INJECTING, `${label}を注入中: ${asset.filename}`);
  injectFile(input, decodeAsset(asset));
}
