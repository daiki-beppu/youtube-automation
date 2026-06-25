# community-helper: コミュニティ投稿スケジュールの DOM 自動化拡張

## Context

YouTube コミュニティ投稿のスケジュール投稿は、`/community-draft` スキルでテキスト生成 → `pbcopy` → YouTube Studio を手動で開いてペースト → 日時設定という手作業フローだった。1 コレクションあたり 3 件の投稿を繰り返すため、テキスト入力・画像添付・スケジュール日時設定を自動化する Chrome 拡張 `community-helper` を新設する。

## Decision

1. **suno-helper のアーキテクチャを踏襲するが、大幅に簡素化する。** `yt-collection-serve` がデータ配信、拡張が DOM 注入に徹する 3 層分離 (skill → server → extension) は同じだが、3 件の逐次処理のため resume state / fetch bridge / speed presets / in-flight tracking は持ち込まない
2. **持ち込む機構は type-safe messaging (`@webext-core/messaging`) と `/version` 互換チェックのみ。** 拡張ファミリ共通の品質ベースラインとして維持する
3. **UI は Popup のみ (オーバーレイなし)。** 3 件の処理に React Shadow DOM オーバーレイは過剰。WXT 標準の Popup でサーバー URL 入力 + Start + 進捗表示を収める
4. **サーバールートは `GET /community/posts.json` + `GET /community/posts/{index}/image`。** dir モード (コレクション一覧選択) は初期スコープ外
5. **投稿データは `/community-draft` スキルが `<collection>/30-promo/community-posts.json` に生成する。** 既存の markdown 出力は廃止し JSON 一本化。LLM 生成もやめ、チャンネル config のテンプレート + 変数展開で決定的な出力を得る
6. **投稿テンプレートと schedule offset はチャンネル config (`config/channel/community-draft.json`) で宣言する。** `schedule_offset_days` の基準は `workflow-state.json` の `publish_target_at`。チャンネルごとに投稿タイプ・件数・内容を自由に設定できる
7. **DOM セレクタは `extensions/shared/community-dom.ts` に集約する。** YouTube Studio の Polymer/Shadow DOM 構造は実装時に Chrome DevTools で調査し、locale-independent なクエリで変更耐性を持たせる
8. **対象ページは YouTube Studio Web (`studio.youtube.com`) のみ。** `youtube.com` 本体のコミュニティタブは対象外

## Considered Options

- **Popup vs オーバーレイ**: suno-helper と同じ React オーバーレイは UX の一貫性を保てるが、3 件の処理に React + Shadow DOM + position persistence は開発・保守コストが見合わない
- **LLM テキスト生成 vs テンプレート展開**: `/community-draft` の既存 LLM 生成は柔軟だが、出力が非決定的で毎回確認が必要。テンプレート方式は再現可能で、チャンネルオーナーが config だけで投稿内容を完全にコントロールできる
- **markdown + pbcopy 併存 vs JSON 一本化**: 併存は移行期に有用だが、2 つの出力形式を保守する負担がある。拡張機能の導入で手動ペーストフローは不要になるため一本化

## Consequences

- `extensions/community-helper/` を WXT + React + TypeScript で新設する
- `extensions/shared/` に `community-dom.ts` (DOM セレクタ) と API 型 (`CommunityPost`) を追加する
- `yt-collection-serve` に `/community/posts.json` と `/community/posts/{index}/image` を追加する
- `/community-draft` スキルを改修: markdown 廃止、JSON バッチ出力、テンプレート + 変数方式への移行
- `release-extensions.yml` に community-helper の zip 化ステップを追加する (ADR-0011 の統一タグ `ext-v*` に従う)
- YouTube Studio の DOM 構造変更に追従するコストが発生する (suno-helper の Suno DOM 追従と同種のリスク)
