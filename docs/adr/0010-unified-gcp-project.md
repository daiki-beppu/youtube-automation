# 全チャンネルを単一 GCP プロジェクトに統合

## Context

チャンネルごとに個別の GCP プロジェクトを作成する運用で、Billing アカウントあたりのプロジェクト上限（5）に到達した。加えて、プロジェクトごとに OAuth 同意画面・API 有効化・ADC quota project 切り替えが必要で、チャンネル追加・日常管理の両面でオペレーションコストが高かった。Console 上で OAuth クライアント ID にラベルが付いておらず「どのプロジェクトがどのチャンネル用か」が把握困難だった。

## Decision

全チャンネルを **1 つの GCP プロジェクト (`yt-channels-automation`)** に統合する。チャンネルごとの分離は **同一プロジェクト内の OAuth クライアント ID**（チャンネル名で命名）で行う。project_id の解決は ADC quota project に一本化し、`.env` への `GOOGLE_CLOUD_PROJECT` 記載は不要とする。

## Why

- **Billing 枠の解放**: 5/5 → 2/5 に削減。新チャンネル追加が再びブロックされない
- **セットアップの簡素化**: チャンネル追加 = Console で OAuth クライアント ID を 1 つ作成するだけ（プロジェクト作成・API 有効化・同意画面設定が不要に）
- **日常管理の簡素化**: ADC quota project が固定。チャンネル間の切り替え操作が消滅
- **可視性**: OAuth クライアント ID をチャンネル名で命名する規約により、Console 上で対応関係が一目でわかる

## Considered Options

- **チャンネルごとに GCP プロジェクトを維持**: quota（10,000 units/日）が独立する利点があるが、Billing 上限 5 に既に到達しており、Billing アカウント追加は Google 審査が必要で根本解決にならない
- **既存プロジェクト (bobble-youtube-automation) に統合**: 移行コストは最小だが、プロジェクト名が特定チャンネルに引っ張られ中立性に欠ける
- **新規プロジェクトを作成して統合** (採用): クリーンな名前で始められる。移行中に Billing 枠を一時的に消費するが、旧プロジェクトの unlink で回復

## Consequences

- YouTube Data API quota (10,000 units/日) が全チャンネルで共有される。17 本バッチアップロードが通った実績から現状は十分だが、チャンネル数増加時に quota 引き上げ申請が必要になる可能性がある
- `yt-doctor accounts` サブコマンドで全チャンネルの OAuth クライアント対応表を一覧できるようにする
- 旧プロジェクト (bobble-youtube-automation, rjn-automation, bah-youtube-automation) は Billing unlink 済み。不要と判断した時点で `gcloud projects delete` で完全削除可能
