# Chrome 拡張の配布形態: GitHub Release zip + バージョン互換チェック

## Context

Chrome 拡張 (suno-helper / distrokid-helper) を当初は運営者 1 人で使っていたが、tayk ユーザー 10 人程度への限定配布に拡大する。配布形態・バージョニング・互換性担保の方針を決める必要があった。

リポジトリは PUBLIC であり、拡張は `yt-collection-serve`（localhost）前提で単体では動作しない。消費者は全員 tayk の自動化環境を持つ技術者。

## Decision

1. **配布形態は GitHub Release の zip 添付を維持する。** Chrome Web Store は使わない — レビュー遅延が Suno/DistroKid の DOM 変更への即時追従と相性が悪く、10 人の技術者に対して Web Store のコンプライアンス維持コストが見合わない
2. **suno-helper と distrokid-helper を両方 zip 化する。** 現行の `release-extensions.yml` は suno-helper のみだったため、distrokid-helper を追加する
3. **統一タグ `ext-v*` で同時リリースする。** 拡張ごとの独立タグ (`suno-helper-v*` 等) は設けない — 10 人規模で workflow を 2 本管理する実益がない
4. **拡張バージョンと tayk 本体バージョンは完全独立とする。** 拡張は Suno/DistroKid の DOM 変更で tayk とは無関係に更新が必要になるため、バージョンを連動させると不自然な bump が発生する
5. **`yt-collection-serve` に `/version` エンドポイントを追加し、拡張が起動時に互換性をチェックする。** 10 人いると「サーバーは最新だが拡張が古い」が現実的に起き、原因切り分けが面倒になるため
6. **アップデート通知は既存チャットチャネルでの手動告知とする。** 拡張やサーバーへの自動チェック機能は作らない — 保守コスト (API rate limit、ネットワークエラー処理) が 10 人規模に見合わない
7. **インストール・更新手順は GitHub Release のリリースノート本文にテンプレとして埋め込む。** 限定メンバーにはリリース URL をチャットで共有するだけで済む
8. **GitHub Release は PUBLIC のまま。** 告知先を特定メンバーに絞る運用で限定する — リポが PUBLIC な時点でソースは見えており、zip を限定配布する実益がない

## Considered Options

- **Chrome Web Store (unlisted)**: 自動アップデートが得られるが、レビュー遅延 (数日)、コンプライアンス維持コスト、DOM 追従の即時性喪失が 10 人規模に見合わない
- **拡張ごとの独立タグ**: リリース頻度の独立性が得られるが、workflow 2 本 + タグ管理 2 系統の管理コストが 10 人規模では過剰
- **バージョン連動 (tayk と拡張を同一番号)**: 「同じ番号なら動く」と説明しやすいが、拡張だけの DOM 追従 hotfix で tayk の番号も上がるのが不自然。`/version` 互換チェックで代替可能
- **拡張内で GitHub Releases API を定期チェックして自動通知**: 保守コスト (rate limit、エラー処理、API スキーマ変更) が 10 人規模に見合わない

## Consequences

- `release-extensions.yml` に distrokid-helper の zip 化ステップを追加する
- `yt-collection-serve` に `/version` エンドポイントを実装し、拡張の popup で互換性チェック + 警告表示を実装する
- リリースノートテンプレを `release-extensions.yml` に組み込む
- 人数が 50+ に増えた場合、自動アップデート通知や Chrome Web Store 移行を再検討する
