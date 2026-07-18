// content 側の per-track 分割注入 state machine（#871）。
//
// popup が injectStart → injectTrack*（track 数分）→ injectCover?（任意）→ injectFinish を
// 逐次送るのを受け、1 セッション分の payload を保持して各メッセージを順に処理する。
// DOM 操作（注入 primitive）は Injector として外から渡す（content は DOM 束縛実装を、
// テストは fake を渡す）。これにより順序保証・範囲検査というセッションのロジックを
// jsdom 非対応のファイル注入から切り離して単体検証できる。
//
// エラーは握りつぶさず throw する。content は onMessage handler でそのまま伝播させ、
// @webext-core/messaging が popup 側の sendMessage を reject する（fail-loud）。

import { decodeAsset, type SerializedAsset } from "./asset-transfer";
import { PHASES, type Phase } from "./messaging";
import type { ReleasePayload } from "./types";

export type Reporter = (phase: Phase, message: string) => void;

// 注入 primitive（DOM 操作）。content が document 束縛の実装を渡す。
export interface Injector {
  // トラック数 set + 行生成待機 + プロファイル + アルバム名 + リリース日 +
  // 全 track のタイトル / songwriter + Apple Music クレジット（asset なし）。
  // track 行の生成を MutationObserver で待つため async（#888）。
  injectStaticFields(payload: ReleasePayload): Promise<void>;
  // 1 track（0-indexed）の曲ファイル。
  injectTrackFile(trackIndex: number, file: File): void;
  // ジャケット。
  injectCover(file: File): void;
  // AI 開示 modal フロー（mount/unmount を待つため async）。
  injectAiDisclosure(payload: ReleasePayload): Promise<void>;
}

export class InjectSession {
  // 進行中セッションの payload。injectStart で確定し injectFinish / stop で破棄する。
  private payload: ReleasePayload | null = null;

  constructor(
    private readonly injector: Injector,
    private readonly report: Reporter
  ) {}

  async start(payload: ReleasePayload): Promise<void> {
    this.report(PHASES.INJECTING, "プロファイルを注入中");
    await this.injector.injectStaticFields(payload);
    this.payload = payload;
  }

  track(trackIndex: number, asset: SerializedAsset): void {
    const { tracks } = this.requirePayload().release;
    if (trackIndex < 0 || trackIndex >= tracks.length) {
      throw new Error(
        `trackIndex が範囲外です: ${trackIndex}（tracks=${tracks.length}）`
      );
    }
    this.report(PHASES.INJECTING, `曲ファイルを注入中: ${asset.filename}`);
    this.injector.injectTrackFile(trackIndex, decodeAsset(asset));
  }

  cover(asset: SerializedAsset): void {
    this.requirePayload();
    this.report(PHASES.INJECTING, `ジャケットを注入中: ${asset.filename}`);
    this.injector.injectCover(decodeAsset(asset));
  }

  async finish(): Promise<void> {
    const payload = this.requirePayload();
    this.report(PHASES.INJECTING, "AI 開示を注入中");
    await this.injector.injectAiDisclosure(payload);
    this.payload = null;
    this.report(
      PHASES.DONE,
      "注入が完了しました。内容を確認して手動で続行してください"
    );
  }

  stop(): void {
    this.payload = null;
    this.report(PHASES.STOPPED, "停止しました");
  }

  // injectStart が先行していない asset 注入は順序違反として fail-loud にする。
  private requirePayload(): ReleasePayload {
    if (this.payload === null) {
      throw new Error("injectStart より前に asset 注入が呼ばれました");
    }
    return this.payload;
  }
}
