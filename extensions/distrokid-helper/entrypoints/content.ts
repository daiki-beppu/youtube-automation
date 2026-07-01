// distrokid.com/new で起動する content script。
//
// popup からの per-track 分割メッセージ（injectStart → injectTrack* → injectCover? →
// injectFinish）を受け、静的プロファイル + 動的データのテキスト/SELECT を注入し、
// popup が fetch 済みの曲 / ジャケット（直列化済み）を File へ復元して <input type=file> にセットする。
// asset の fetch を popup 側で行う理由は asset-transfer.ts を参照（content からの fetch は CORS で遮断）。
// セッションのロジック（順序保証・範囲検査）は lib/inject-session.ts が担い、ここは DOM 束縛の
// 注入 primitive とメッセージ配線のみを持つ。
// 「続ける」等の送信系操作は一切行わない（規約遵守・スコープ外）。

import { createDocumentInjector } from "@/lib/content-injector";
import { InjectSession } from "@/lib/inject-session";
import { onMessage, sendMessage } from "@/lib/messaging";

// document 束縛の注入 primitive。AI 開示モーダル（Suno 楽曲は通過必須）も含め
// 実 DOM 操作はすべて lib/distrokid-injector.ts へ委譲する。
const documentInjector = createDocumentInjector(document);

export default defineContentScript({
  matches: ["*://*.distrokid.com/new*"],
  main() {
    const session = new InjectSession(documentInjector, (phase, message) =>
      sendMessage("progress", { phase, message }),
    );

    // 各メッセージ handler は例外を握りつぶさず伝播させる。@webext-core/messaging が
    // popup 側 sendMessage を reject し、popup が ERROR フェーズへ一元変換する（fail-loud）。
    onMessage("injectStart", ({ data }) => session.start(data.payload));
    onMessage("injectTrack", ({ data }) => session.track(data.trackIndex, data.asset));
    onMessage("injectCover", ({ data }) => session.cover(data.asset));
    onMessage("injectFinish", () => session.finish());
    onMessage("stop", () => session.stop());
  },
});
