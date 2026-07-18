# community-helper: コミュニティ投稿スケジュールの DOM 自動化拡張

## Status

accepted (2026-06-25)。#1712 で拡張の scaffold / messaging 基盤まで実装済み。#1708 の実 DOM
調査で判明した origin と fetch 境界への移行は #1713 / #1714 で行う。

2026-07-02 の ADR 監査で 0013 から番号振り直し（並行 PR による番号レースの解消、先着優先ルール）。旧文書中の「ADR-0013」は文脈により本 ADR を指す。

2026-07-18 の実 DOM 調査 (#1708) で対象 origin と fetch 境界を改訂。調査根拠とセレクタは
`docs/research/community-helper-dom-map.md` を正とする。

## Context

YouTube コミュニティ投稿のスケジュール投稿は、`/community-draft` スキルでテキスト生成 → `pbcopy` → YouTube Studio を手動で開いてペースト → 日時設定という手作業フローだった。1 コレクションあたり 3 件の投稿を繰り返すため、テキスト入力・画像添付・スケジュール日時設定を自動化する Chrome 拡張 `community-helper` を新設する。

## Decision

1. **suno-helper のアーキテクチャを踏襲するが、大幅に簡素化する。** `yt-collection-serve` がデータ配信、拡張が DOM 注入に徹する 3 層分離 (skill → server → extension) は同じだが、3 件の逐次処理のため resume state / speed presets / in-flight tracking は持ち込まない。page-origin fetch は使わず、community 専用の extension-context fetch relay を持つ
2. **type-safe messaging (`@webext-core/messaging`) と `/version` 互換チェックを品質ベースラインとして維持する。** messaging は Popup → background → content の制御・進捗に加え、background が取得した投稿 JSON・画像を content へ渡す境界にも使う
3. **UI は Popup のみ (オーバーレイなし)。** 3 件の処理に React Shadow DOM オーバーレイは過剰。WXT 標準の Popup でサーバー URL 入力 + Start + 進捗表示を収める
4. **サーバールートは `GET /community/posts.json` + `GET /community/posts/{index}/image`。** dir モード (コレクション一覧選択) は初期スコープ外
5. **投稿データは `/community-draft` スキルが `<collection>/30-promo/community-posts.json` に生成する。** 既存の markdown 出力は廃止し JSON 一本化。LLM 生成もやめ、チャンネル config のテンプレート + 変数展開で決定的な出力を得る
6. **投稿テンプレートと schedule offset はチャンネル config (`config/channel/community-draft.json`) で宣言する。** `schedule_offset_days` の基準は `workflow-state.json` の `publish_target_at`。チャンネルごとに投稿タイプ・件数・内容を自由に設定できる
7. **DOM セレクタは `extensions/shared/community-dom.ts` に集約する。** YouTube の Polymer/ShadyDOM 構造は Chrome DevTools で実地調査し、locale-independent なクエリで変更耐性を持たせる
8. **対象 UI は YouTube 本体のチャンネル投稿ページ (`https://www.youtube.com/channel/*/posts*`) のみ。** Studio の投稿導線はこのページへ遷移し、`studio.youtube.com/channel/*/posts` には作成 UI が存在しないことを #1708 で確認した。content script の match は投稿ページに限定する
9. **localhost の投稿 JSON・画像は extension origin の background/popup が取得し、typed messaging で content script へ relay する。** `www.youtube.com` をサーバー CORS allowlist に加えると任意の YouTube ページから下書きを読めるため、page-origin fetch は採用しない。ページ権限は activeTab + 動的注入を優先し、静的注入が必要な場合も対象 URL を投稿ページへ限定する

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
- YouTube 本体の投稿 UI の DOM 構造変更に追従するコストが発生する (suno-helper の Suno DOM 追従と同種のリスク)
- localhost の community route は YouTube page origin へ CORS 公開せず、extension context からのみ取得する
- #1710/#1712 時点の Studio page-origin `/version` / community route CORS と Studio-only manifest/content routing は移行前の暫定実装であり、#1713/#1714 で撤去・置換する

## `community-draft.json` schema contract

`config/channel/community-draft.json` is optional for channels that do not use the
community batch workflow. When `/community-draft --batch` is explicitly requested,
however, a missing file is an error: the command must stop before producing
`community-posts.json` and identify the missing config path. It must not silently
fall back to the legacy markdown templates.

The canonical example is
`examples/channel_config.example/community-draft.example.json`. Its top-level
contract is:

- `community_draft.posts`: a non-empty array. Every item has a non-empty `label` and `template`, an
  integer `schedule_offset_days`, a zero-padded 24-hour `schedule_time` (`HH:MM`),
  and an `image` path relative to the collection directory. Absolute paths and
  paths containing `..` are invalid.
- `community_draft.variables`: channel-owned literal values used by templates. The initial schema
  defines `custom_message` here so batch generation remains deterministic.

The initial template vocabulary is deliberately closed:

| Variable | Single source | Rendering |
|---|---|---|
| `{title}` | `<collection>/workflow-state.json::planning.final_title` | string as stored |
| `{date}` | `<collection>/workflow-state.json::planning.publish_target_at` | calendar date after conversion to `config/channel/youtube.json::youtube.default_publish_timezone` |
| `{custom_message}` | `config/channel/community-draft.json::community_draft.variables.custom_message` | string as stored |

Unknown variables or missing source values are errors. User input must be persisted
to `community_draft.variables.custom_message` before batch generation; the batch command does not
prompt for an ephemeral replacement.

For each post, `scheduled_at` is calculated deterministically as follows:

1. Parse `planning.publish_target_at` as ISO 8601. A date-only value is interpreted
   in `config/channel/youtube.json::youtube.default_publish_timezone`; an instant with an offset
   is first converted to that timezone.
2. Take that local calendar date and add `schedule_offset_days` calendar days.
3. Combine the resulting date with `schedule_time` in the same IANA timezone and
   serialize it as an ISO 8601 datetime including its UTC offset.

Missing or invalid `publish_target_at`, timezone, or schedule values stop generation
with an error naming the invalid field. These rules are the input contract for
#1709; JSON output and the removal of the markdown flow remain that issue's scope.
