# Terraform を GCP の唯一の変更経路とする

## Status

accepted (2026-09-05)。Wayfinder map [#4714](https://github.com/daiki-beppu/youtube-automation/issues/4714)、起草 [#4929](https://github.com/daiki-beppu/youtube-automation/issues/4929)。決定の正本は #4719（ADR 番号の訂正を含む）、#4720 §12、#4721 §11。

## Context

ADR-0010 の単一共有プロジェクトには既存リソースがあるが、Terraform の定義と doctor / bootstrap の変更経路が併存していた。存在確認だけの data source ではプロジェクトの billing 紐付けを drift として検出できず、複数の変更経路は構成の正本を曖昧にする。

## Decision

1. 既存リソースの取り込み完了後、GCP プロジェクト `yt-channels-automation` への変更は `infra/terraform/gcp/` からのみ行う。project と billing を managed にし、`deletion_policy = "PREVENT"` と `prevent_destroy = true` の二重ガードで共有プロジェクトを保護する。
2. doctor `--apply` と `gcp-bootstrap.sh` は GCP を変更しない。GCP 層の `gcp_project` / `billing_linked` / `apis_enabled` / `iam_aiplatform_user` は読み取り専用にする（実装 #4933）。doctor は不足の観測と Terraform への案内を担う。
3. CI は静的ゲートと読み取り専用 drift 検知に限定し、apply は CI から実行しない。WIF は読み取り専用サービスアカウント 1 本とする（実装 #4930 / #4931 / #4932）。apply は ADC を持つ運用者がローカルで plan を確認して行う。
4. project 1 + API 6 + IAM 1 の 8 件を宣言的 import ブロックで取り込む。ブロックは apply 後も保持し、取り込み済みには no-op、state 喪失時には復旧の対象宣言として利用する。
5. 定義外で有効な 26 API、`roles/owner`、aiplatform サービスエージェントは管理外のままとする。API / IAM は additive に共存させ、owner は Terraform が使えないときの人間の break-glass として残す。

## Considered Options

- doctor と bootstrap からの変更を維持する: セットアップ時の便利さはあるが、Terraform 外の更新と宣言との不一致が生まれる。
- CLI import 後に取り込み宣言を残さない: 実施は容易だが、PR での範囲レビューと state 喪失時の再現性を失う。
- CI から apply する: 自動化できるが、変更頻度と運用者数に対して書き込み権限と承認経路の維持が重い。必要性が変われば再評価する。

## Consequences

Terraform を構成の正本とし、drift はローカル apply で実体を宣言に戻して解消する。意図した変更であれば先に Terraform 定義を PR で変更する。初回の合格条件は **8 to import, 0 to add, 0 to change, 0 to destroy** とし、異なる差分があれば apply を止めて #4929 で議論する。

doctor / setup と CI の帰結は実装 epic [#4939](https://github.com/daiki-beppu/youtube-automation/issues/4939) の各段で反映する。この ADR の accepted は決定の採用を表し、HUMAN STEP の import 完了証拠は #4929 の plan / apply / No changes コメントで確認する。Google Auth Platform の provider 未対応設定は引き続き手動設定の境界にあり、この import の管理対象へ追加しない。
