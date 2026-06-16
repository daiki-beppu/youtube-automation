# Remotion ベース動画レンダリング

## Context

動画生成パイプラインは `generate_videos.sh`（854行の bash）が ffmpeg を直接叩く構成で、5 つのレンダリング経路（静止画 / ループ動画 / エフェクトベイク / オーバーレイ / stream copy）と 4 種のエフェクト（particles / bokeh / gradient / audio_visualizer）を条件分岐で処理している。

この構成には 3 つの課題がある:

1. **エフェクト表現力の制約**: ffmpeg filter（`geq`, `noise`, `showfreqs` 等）で表現できるビジュアルエフェクトに限界がある。色・形状・軌道のカスタマイズが困難
2. **プレビュー不可**: ffmpeg を走らせないと仕上がりが確認できない。2 時間尺のレンダリングは 1-2 分かかり、試行錯誤のサイクルが遅い
3. **TS 統一の障壁**: tayk の TS(bun) 移行（ADR-0001, epic #727）後も、動画生成だけ bash/ffmpeg 依存が残る

## Decision

動画生成パイプラインの映像合成 + 最終レンダリングを **Remotion**（React ベースのプログラマティック動画生成フレームワーク）に移行する。音源結合（`generate-master`）は ffmpeg/TS wrapper のまま。

具体的な構成:

1. **`packages/remotion/`** を独立パッケージとして新設。React コンポーネントで映像を定義し、`renderMedia()` でレンダリングする
2. **`config/skills/videoup.json`** に `renderer: "remotion" | "ffmpeg"` 設定を追加。デフォルトは `"ffmpeg"`（移行期間中の安全側）。将来 `"auto"` に移行し、エフェクト/オーバーレイがあれば Remotion、なければ ffmpeg を自動選択する
3. **core からは dynamic import** (`await import("@youtube-automation/remotion/render")`) で疎結合にし、Remotion がインストールされていない環境でも core/cli は動作する
4. **エフェクトは Canvas 2D API / CSS** で実装。react-three-fiber (WebGL/3D) は全エフェクトが 2D で完結するため不採用
5. **Remotion Studio** (`remotionb studio`) でインタラクティブプレビューを提供

タイミングは **cutover 後の別 epic**。cutover スコープには含めない。

## Why

- **表現力**: React コンポーネント + Canvas API で書くエフェクトは、ffmpeg filter と比べて表現の自由度が桁違い。新エフェクトの追加もコンポーネント 1 ファイルで完結する
- **プレビュー**: Remotion Studio でブラウザ上からリアルタイムにパラメータを変えて確認できる。ffmpeg の全尺レンダリングなしに試行錯誤が可能
- **TS 統一**: `generate_videos.sh`（bash 854行）が React/TypeScript に置き換わり、tayk のアーキテクチャ（service/adapter, registry, zod schema）に統合される
- **bun サポート**: Remotion は bun を公式サポートしており（`remotionb` CLI）、tayk のランタイム選択と整合する
- **ライセンス**: 個人利用は無料。tayk は first-party のみ（第三者 consumer なし）なので無料範囲内

## Considered Options

- **ffmpeg TS wrapper のみ（Remotion なし）**: `generate_videos.sh` を TypeScript に移植し、`Bun.spawn("ffmpeg", ...)` で ffmpeg を呼ぶ。TS 統一は達成できるが、エフェクト表現力の改善とプレビュー体験は得られない
- **FFCreator / editly 等の軽量ライブラリ**: Remotion より軽量だが、エコシステムの成熟度・プレビュー機能・コミュニティサイズで Remotion に劣る
- **After Effects + Extendscript**: プロフェッショナルなモーショングラフィックスが可能だが、Adobe ライセンスが必要で CLI 自動化との親和性が低い

## Consequences

- `packages/remotion/` は React（`react`, `react-dom`）に依存する。この依存は `packages/core` には伝播しない（dynamic import で分離）
- Remotion のレンダリングは全フレームを Chromium でキャプチャするため、ffmpeg の stream copy（再エンコードなし）と比べてレンダリング時間が大幅に増加する。エフェクトなし + ループ動画のケースでは ffmpeg が数秒で完了するところ、Remotion では数十分かかる。この劣化は `renderer` 設定による ffmpeg フォールバックで回避可能
- ffmpeg ベイク化キャッシュ（`fx_baked.mp4` / `fx_baked.params`）は Remotion 経路では不要になる
- 段階的マイグレーション（Phase 1-5）で移行し、各フェーズで ffmpeg 経路との回帰テストを行う

## Related

- ADR-0001: Python → TypeScript(bun) big-bang 移行（前提）
- ADR-0002: Service-first architecture（`packages/remotion` の位置づけ）
- ADR-0003: Service-boundary contracts（videoup service の設計）
- ADR-0009: JSON-only config（`config/skills/videoup.json` の renderer 設定）
