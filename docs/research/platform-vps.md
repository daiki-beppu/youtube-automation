# research: VPS（Vultr）の適性調査（料金・ディスク・転送・スケジュール・secret）

Issue: #3298（親: #3293）
調査日: 2026-08-07
一次情報: Vultr 公式ドキュメント（docs.vultr.com）・Vultr 公式 API（api.vultr.com/v2/plans、2026-08-07 取得）・Vultr 公式ブログ。比較対象（Hetzner）と周辺（Cloudflare R2 / 1Password）は各公式ドキュメントのみ。加えて「既存資産との整合」はリポジトリ内 `infra/terraform/streaming/`（README.md / main.tf / variables.tf）と `.claude/skills/streaming/SKILL.md` を根拠にする。

## 結論（要旨）

- **適性は高い。最大の根拠は既存資産**: Vultr provider・secret 規約（`TF_VAR_*` + `op read` + ephemeral 変数）・deploy パターン（`null_resource` + templates + triggers）・死活監視（cron + Discord webhook）が `infra/terraform/streaming/` で確立・実運用済みであり、制作ランナー VM は同じ規約のモジュール並置でほぼコピーで立つ。headless AI エージェント常駐（Codex CLI + systemd）も本リポジトリで唯一の実運用実績がある基盤。
- **料金の急所は「停止しても課金される」こと**（Vultr 公式）。オンデマンド節約は stop ではなく **destroy / 再 apply** が唯一の経路。週次〜日次ランなら時間課金で月 $0.4〜$2 程度に収まる試算だが、「apply を起動する外部装置」が別途必要になり、無人要件はその装置の可用性に依存する。常駐なら $10〜$24/月 固定で cron + flock により多重起動防止まで単一マシン内で完結する。
- ディスク（最小プランでも 55GB ローカル SSD）・転送（アカウントプール 2TB〜 + R2 は egress 無料）・実行時間（無制限）は本プロジェクトの想定負荷（9.7GB 級中間物、2 時間尺の ffmpeg ラン）に対して十分。
- ロックインは低い: cloud-init + Terraform 構成は Hetzner 等でも同型（Hetzner も時間課金 + 月額上限 + 停止課金の同じモデル）。ただし Hetzner は日本リージョンが無い。

---

## 共通評価軸

### 1. 料金体系

**事実**

- プラン実勢（Vultr 公式 API `GET /v2/plans`、2026-08-07 取得。東京 `nrt` で提供あり・地域追加料金なし — `location_cost` の割増は `sao`（サンパウロ）のみ）:

  | プラン ID | vCPU | RAM | ディスク | 帯域/月 | 月額 | 時間額 |
  |---|---|---|---|---|---|---|
  | vc2-1c-2gb | 1（共有） | 2GB | 55GB SSD | 2TB | $10 | $0.014 |
  | vc2-2c-4gb | 2（共有） | 4GB | 80GB SSD | 3TB | $20 | $0.027 |
  | vhf-2c-4gb | 2（共有） | 4GB | 128GB NVMe | 3TB | $24 | $0.033 |
  | vhp-2c-4gb-amd | 2（共有） | 4GB | 100GB NVMe | 5TB | $24 | $0.033 |
  | vhp-4c-8gb-amd | 4（共有） | 8GB | 180GB NVMe | 6TB | $48 | $0.066 |
  | voc-c-2c-4gb-50s-amd | 2（専有） | 4GB | 50GB NVMe | 5TB | $40 | — |
  | voc-c-4c-8gb-150s-amd | 4（専有） | 8GB | 150GB NVMe | 6TB | $90 | — |

  出典: https://api.vultr.com/v2/plans （公開エンドポイント。`vcpu_type: "thread"` = 共有 vCPU はハイパースレッド 1 本）
- 課金は時間単位（最小 1 時間）、GPU 以外は月 672 時間で頭打ち（= 月額表示価格が上限）。**課金はデプロイ時点から電源状態に関係なく発生する**。出典: https://docs.vultr.com/support/platform/billing/how-am-i-billed-for-my-servers
- **停止（stop）では課金は止まらない**。「Stopping an instance does not halt billing because the instance continues to reserve critical resources such as CPU, RAM, SSD storage, and IP addresses.」課金停止には destroy が必須。出典: https://docs.vultr.com/support/platform/billing/are-stopped-instances-still-billed-on-vultr
- スナップショットは $0.05/GB/月。出典: https://docs.vultr.com/support/platform/billing/does-vultr-charge-for-stored-snapshots

**含意**

- オンデマンド運用の設計は「stop/start」ではなく「**terraform destroy / 再 apply**」を前提に組む（streaming README §5 も「長期休止する場合は必ず destroy」と同じ運用）。時間課金の試算: 週次 1 ラン 3h ≒ 13h/月 → vhp-2c-4gb で約 $0.43/月。日次 2h ≒ 60h/月 → vc2-1c-2gb $0.84 / vhp-2c-4gb $1.98/月（API の時間額から単純算出）。常駐でも $10〜$24/月で、想定負荷に対する絶対額は小さい。
- 東京リージョンで価格割増が無いため、レイテンシ最適地（既存 streaming VPS と同じ `nrt`）をコスト無差別で選べる。

### 2. 実行時間上限

**事実**

- VM に実行時間の上限という概念はなく、destroy するまで稼働し課金が続く（前掲 billing ドキュメント）。streaming モジュールは同じ性質を利用して 24/7 連続配信を実運用している（`infra/terraform/streaming/README.md`）。

**含意**

- 重量レジーム（エフェクト・オーディオスペクトラムで 2 時間尺のレンダが大幅に伸びるケース）でもタイムアウト起因の分割設計が不要。serverless 系（実行時間上限あり）に対する VPS の最大の構造的優位。対価は常駐コストまたは destroy/apply の運用手間で、それが評価軸 1・6 の論点になる。

### 3. ディスク容量と IO

**事実**

- ローカルディスクはプラン内蔵: 最小 vc2-1c-2gb で 55GB SSD、vhf-2c-4gb で 128GB NVMe、vhp-2c-4gb で 100GB NVMe（前掲 plans API）。vc2 系は「regular SSD」、vhf/vhp 系は「ultra fast NVMe storage」と公式に区別される。出典: https://docs.vultr.com/products/compute/instances/cloud-compute/provisioning
- 拡張はブロックストレージ: NVMe $100/TB/月（$0.10/GB/月）、HDD $25/TB/月。出典: https://discover.vultr.com/block-storage-datasheet
- ブロックストレージの性能目標: NVMe は 10,000 IOPS / 400 MiB/s、HDD は 500 IOPS / 100 MiB/s（バースト +50% 約 1 分。上限目標であり最低保証ではない）。出典: https://docs.vultr.com/support/products/storage/what-are-the-performance-expectations-for-block-storage
- ブロックストレージは同一リージョンのインスタンスにのみ attach 可、1 インスタンス最大 16 ボリューム。出典: https://docs.vultr.com/products/cloud-storage/block-storage
- ローカルディスク（プラン内蔵分）の IOPS 公称値は公式ドキュメントに見当たらない（ブロックストレージのみ数値公開）。

**含意**

- 9.7GB 級の中間物 + 作業領域は最小プランの 55GB でも収まり、重量レジームで一時ファイルの膨張が読めない場合も vhf/vhp の 100〜128GB NVMe で吸収できる。恒常的な大容量が必要になったら NVMe ブロックストレージを $0.10/GB/月で足せる（リージョンを streaming VPS と揃えておけば使い回しも可能）。IO がボトルネック化した場合の一次切り分けは実測になる（ローカルディスクの公称値が無いため）。

### 4. R2 との転送

**事実**

- Vultr は全顧客に月 2TB の無料 egress、**ingress は無料**、そして転送枠は**アカウント単位で全インスタンス・全リージョンをプール**（枠は月内に時間割で積み上がる）。出典: https://blogs.vultr.com/Vultr-Announces-Reduced-Bandwidth-Pricing-2-Tb-Of-Free-Monthly-Egress-Free-Ingress-And-Global-Pooling
- 超過は outbound $0.01/GB。出典: https://docs.vultr.com/support/platform/billing/what-is-the-bandwidth-overage-rate
- Cloudflare R2 は egress 無料（「There are no charges for egress bandwidth for any storage class」）。ストレージは Standard $0.015/GB-月。出典: https://developers.cloudflare.com/r2/pricing/

**含意**

- VPS→R2（中間物アップロード）は Vultr の egress としてプール枠を消費、R2→VPS（ダウンロード）は両側無料。9.7GB/ラン × 日次 30 ラン ≒ 291GB/月で、プラン付帯枠（2〜5TB）に対して余裕がある。
- プール制のため、ランナーを別インスタンスとして追加すると**そのプラン付帯分だけアカウントの転送枠が増える**。streaming VPS は 24/7 配信で月約 1.52TB を消費し 2TB 上限を監視している（`infra/terraform/streaming/README.md` §帯域モニタリング）が、ランナー追加はこの制約をむしろ緩和する方向に働く。既存の `yt-stream-bandwidth` の 80% 閾値監視はアカウント合算ではなくインスタンス単位 API を見るため、合算監視に広げるかは実装時の論点。

### 5. CPU 性能と ffmpeg 適性

**事実**

- プランファミリの公式説明: vc2 =「previous generation Intel CPUs and regular SSD」の共有 vCPU、vhf =「higher clock speed (>3Ghz)」+ NVMe、vhp =「latest generation Intel Xeon CPUs or AMD EPYC CPUs」+ NVMe。出典: https://docs.vultr.com/products/compute/instances/cloud-compute/provisioning
- 共有プランの vCPU は `vcpu_type: "thread"`（ハイパースレッド 1 本）。専有が必要なら voc（Optimized Cloud Compute、CPU Optimized は voc-c 系）で、2 vCPU 4GB が $40/月、4 vCPU 8GB が $90/月（前掲 plans API）。
- ffmpeg 実効性能の公式ベンチマークは存在しない。参考となる社内実績は、vc2-1c-2gb 上で ffmpeg ストリームコピー（`-c:v copy`）の 24/7 配信が安定稼働していること（`infra/terraform/streaming/README.md`）。

**含意**

- 軽量レジーム（静止画ループ、実質ストリームコピー〜低負荷エンコードで 2 時間尺 1〜2 分）は vc2-1c-2gb（$10/月）で足りる公算が高い。重量レジーム（フィルタ・スペクトラム描画で CPU バウンド）は vhp-2c-4gb（$24/月、最新世代 + NVMe）を第一候補、足りなければ vhp-4c-8gb（$48/月）へ。専有 voc-c は常駐だと割高で、時間課金のオンデマンド運用（4 vCPU 専有でも $90/672h ≒ $0.13/h）でのみ費用対効果が出る。
- 共有スレッドの性能ゆらぎは原理的に避けられないため、レジーム別の実測 → `var.plan` 差し替え（streaming と同じく Terraform 変数 1 つ）で調整するのが低リスク。時間課金なので実測コストも小さい。

### 6. スケジュール実行

**事実**

- Vultr にマネージドなジョブスケジューラは無い。スケジュールは VM 内の cron / systemd timer で自前実装になる。本リポジトリには `/etc/cron.d` 配置を Terraform で配布する実績がすでにある（streaming の healthcheck: `/etc/cron.d/youtube-stream-healthcheck` を 5 分間隔で配布。`infra/terraform/streaming/README.md` §死活監視、`main.tf` の `cron_d` trigger）。
- 多重起動防止は単一マシン内で `flock` により完結する（分散ロック不要）。

**含意**

- **常駐運用ならこの軸は VPS の強み**: cron + flock + systemd（`Restart=` / `RuntimeMaxSec`）だけで「定時起動・多重起動防止・異常時のみ Discord 通知」が streaming の既存パターン（healthcheck 4-way 分類 → anomaly のみ通知）の流用で組める。
- **オンデマンド運用ではこの軸が弱点に変わる**: destroy 済みの VM は自分を起こせないため、「terraform apply を定時に叩く外部装置」（ローカル Mac の launchd / CI / 別の常駐点）が必須になり、無人要件（異常時だけ人間へ通知）はその装置の可用性に依存する。常駐 $10〜24/月と、外部装置の運用複雑性のどちらを取るかが ADR の主要な分岐点。

### 7. secret 管理

**事実**

- 1Password Service Accounts は desktop アプリ非依存で、`OP_SERVICE_ACCOUNT_TOKEN` により headless サーバー上の `op` CLI 認証ができる。アクセス可能な vault と操作は service account 単位でスコープでき、利用は usage report で監査できる。出典: https://developer.1password.com/docs/service-accounts/ （https://www.1password.dev/service-accounts/ へリダイレクト）
- 既存規約（`infra/terraform/streaming/`）: secret は `terraform.tfvars` に書かず `TF_VAR_*` 環境変数へ `op read` で注入。実行時 secret は provisioner の `file` で mode 0600 root 所有に配置（`EnvironmentFile`）。OAuth / Codex の認証 JSON は Terraform 1.10+ の `ephemeral = true` + `sensitive = true` で plan / state に残さない。cloud-init の user_data に載せるのは SSH host key のみで、アプリ secret は cloud-init に置かない（`README.md`、`variables.tf`、`main.tf`）。
- 本体側の secret 解決順は env → `op read` → `ConfigError`（`CLAUDE.md` セキュリティ節、`infrastructure/secrets.py::_SECRET_REFS`）。

**含意**

- streaming の `op read` → `TF_VAR_*` 規約はそのまま流用できる。制作ランナーが実行時に多数の secret（YouTube / R2 / AI）を必要とする点だけが streaming と異なるが、これは (a) 各値を ephemeral 変数 + provisioner 0600 配置で個別配布するか、(b) **service account token 1 個だけを 0600 で配置し、VM 上の `op read` に解決させる**（`infrastructure/secrets.py` の解決順が VPS 上で無改修で機能する）かの二択で、(b) が既存コードとの整合が最も良い。いずれの場合も cloud-init user_data への secret 直書きは既存規約どおり避ける（user_data はインスタンスメタデータとして参照可能なため）。

### 8. 環境の可搬性

**事実**

- Vultr は cloud-init の user_data によるプロビジョニングを公式サポートし（出典: https://docs.vultr.com/how-to-deploy-a-vultr-server-with-cloudinit-userdata ）、公式の `vultr/vultr` Terraform provider で `user_data` に cloud-init を渡す手順の公式ガイドがある（出典: https://docs.vultr.com/provision-a-vultr-cloud-server-with-terraform-and-cloud-init ）。
- 既存の streaming 規約のうち、`tls_private_key.ssh_host` による host key 固定（TOFU 排除）と `null_resource` + `connection { host_key = ... }` は provider 非依存の Terraform 標準機能。Vultr 固有なのは `vultr_instance` / `vultr_ssh_key` / `vultr_firewall_group` / `vultr_firewall_rule`（/32 制限）とプラン・リージョン ID のみ（`infra/terraform/streaming/main.tf`）。

**含意**

- 「cloud-init で OS 準備 + Terraform で配線 + null_resource で配布」という streaming の構成はそのまま制作ランナーに流用でき、かつ他 VPS への移植時に書き換えるのはリソース型とプラン ID に限られる。firewall の /32 制限も他社の同等リソース（例: Hetzner の firewall）で表現できる一般的な構造。

### 9. AI エージェント実行適性

**事実**

- 本リポジトリは Vultr VPS 上での headless AI エージェント常駐を既に実運用している: `null_resource.live_chat_reply` が Codex CLI を OpenAI 公式 installer で version 固定（`live_chat_codex_version`、既定 0.144.1）インストールし、`auth.json` を ephemeral 変数で専用 user の 0600 に配置、systemd unit（`Restart=on-failure`）で常駐させる（`infra/terraform/streaming/main.tf`、`README.md` §ライブチャット自動返信）。
- VM には実行時間上限が無く（評価軸 2）、リソースはインスタンスに専属（停止中も予約され続けることが課金根拠。前掲 billing ドキュメント）。

**含意**

- Claude Code / Codex CLI の headless 常駐は「本リポジトリで唯一、実運用実績のある構成」で、API キー管理（ephemeral 変数 or op service account）・version 固定・systemd 化・通知まで一式の型が既にある。エージェントを制作ランナーに載せる場合の増分は、既存パターンの unit を 1 本増やす程度。

### 10. ベンダーロックイン度

**事実**

- cloud-init は特定ベンダーに紐付かない業界標準の初期化機構で、Vultr は user_data として受け付ける（評価軸 8 の出典）。Terraform provider を差し替えれば同じ user_data / 配布スクリプトが他 VPS でも動く。
- 比較対象 Hetzner Cloud（概要のみ）: 時間課金 + 月額上限、**停止中も削除まで課金**（「you pay for a server ... regardless of whether it is turned on or not」）、outbound のみ課金・inbound 無料という Vultr と同型の課金モデル。出典: https://docs.hetzner.com/cloud/billing/faq/ 。ロケーションは DE×2 / FI / US×2 / SG の 6 拠点で**日本リージョンは無い**。出典: https://docs.hetzner.com/cloud/general/locations/ 。cloud-init / Terraform provider（hcloud）も公式提供。

**含意**

- ロックインは低い。移行時に書き換わるのは provider ブロック・リソース型・プラン/リージョン ID で、cloud-init・配布スクリプト・systemd unit・op 連携は無改修で持ち出せる。「停止でも課金・destroy で停止」という運用モデル自体も Hetzner と共通のため、運用設計ごと可搬。ただし東京リージョンを持つのは Vultr 側で、streaming VPS との同一リージョン運用（ブロックストレージ共用可否、R2 への RTT）を重視する限り Vultr 継続に合理性がある。

---

## この基盤に固有の論点

### 既存資産との整合 — 制作ランナー VM の設計スケッチ

`infra/terraform/streaming/` の規約をそのまま踏襲し、**別モジュール並置**で追加する:

```text
infra/terraform/render-runner/     # streaming と並置（同居させない）
├── versions.tf      # 同じ vultr/vultr provider + backend "gcs"（bootstrap の bucket、prefix だけ別）
├── variables.tf     # vultr_api_key (TF_VAR)・plan (既定 vhp-2c-4gb)・region (nrt)・allowed_ssh_cidr (/32 必須 validation)
├── cloud-init.yaml  # ssh_keys で host key 固定（tls_private_key 流用）+ ffmpeg / uv / op CLI インストール
├── main.tf          # tls_private_key + vultr_ssh_key + vultr_firewall_group/rule + vultr_instance
│                    # + null_resource.deploy（triggers: instance_id / スクリプト filemd5 / config hash）
└── templates/       # render-runner.service(.timer) / healthcheck env 等の tftpl
```

- secret: `TF_VAR_vultr_api_key=$(op read ...)` は streaming と同一。実行時 secret は op service account token 1 個を provisioner で 0600 配置し、`infrastructure/secrets.py` の env → `op read` 解決に委ねる（評価軸 7）。
- 監視: streaming の healthcheck.sh / notify.sh（anomaly のみ Discord 通知）の型を流用。「異常時だけ人間へ通知し通常時は無人」の要件はこのパターンが既に満たしている。
- state: bootstrap 済み GCS bucket に prefix 別で保存（streaming README の remote state 手順と同一）。

### 常駐 24/7 vs オンデマンド（apply / destroy）

| 観点 | 常駐 | オンデマンド |
|---|---|---|
| 月額（vhp-2c-4gb） | $24 固定 | 日次 2h で ≒ $2、週次 3h で ≒ $0.43（時間課金試算） |
| スケジュール | VM 内 cron / systemd timer で完結。flock で多重起動防止 | **外部起動装置が必須**（destroy 済み VM は自分を起こせない） |
| 無人要件 | healthcheck + Discord 通知の既存型で充足 | 起動装置側の死活も監視対象になり、監視が二段になる |
| プロビジョニング | 初回のみ | 毎回。streaming 実績では apply 完了まで 5〜10 分（README §5） |
| OS 運用 | パッチ・再起動運用が発生し続ける | 毎回まっさらな OS（cloud-init 再現）で運用負債が積まれない |
| 中間状態 | ローカルディスクに残せる | destroy で消える → R2 を正とする設計が強制される（むしろ健全） |

注意: 「インスタンス停止」による中間形態は**節約にならない**（停止中も課金。評価軸 1）。取るなら destroy を伴う完全オンデマンドか、常駐かの二択。スナップショット保持（$0.05/GB/月）で再構築を速める折衷はあるが、cloud-init 再現が既に確立しているため必要性は薄い。

### ライブ配信 VPS と同居しない前提の追加コスト

- 別インスタンスの増分は常駐で $10（vc2-1c-2gb）〜 $24（vhp-2c-4gb）/月、オンデマンドなら月 $2 前後（前掲試算）。
- 別インスタンス化により配信側と CPU / ディスク IO / メモリを一切共有しないため、「配信の安定性を害さない」要件はインスタンス分離で構造的に満たされる（配信は `vc2-1c-2gb` 上で ffmpeg ストリームコピーが 24/7 稼働中 — 重量レンダを同居させる選択肢はそもそも取らない）。
- 転送枠はアカウントプールのため、ランナー追加は配信側の 2TB 制約を圧迫せず、逆にプラン付帯分だけ全体枠を増やす（評価軸 4）。

---

## 出典一覧

- Vultr plans API（公開・料金/スペック実勢値）: https://api.vultr.com/v2/plans
- 課金単位・672h 上限・デプロイ時点課金: https://docs.vultr.com/support/platform/billing/how-am-i-billed-for-my-servers
- 停止中も課金・destroy で停止: https://docs.vultr.com/support/platform/billing/are-stopped-instances-still-billed-on-vultr
- 帯域超過 $0.01/GB（outbound）: https://docs.vultr.com/support/platform/billing/what-is-the-bandwidth-overage-rate
- 2TB 無料 egress・ingress 無料・アカウントプール: https://blogs.vultr.com/Vultr-Announces-Reduced-Bandwidth-Pricing-2-Tb-Of-Free-Monthly-Egress-Free-Ingress-And-Global-Pooling
- スナップショット $0.05/GB/月: https://docs.vultr.com/support/platform/billing/does-vultr-charge-for-stored-snapshots
- プランファミリ定義（vc2 / vhf / vhp）: https://docs.vultr.com/products/compute/instances/cloud-compute/provisioning
- ブロックストレージ価格: https://discover.vultr.com/block-storage-datasheet
- ブロックストレージ性能目標: https://docs.vultr.com/support/products/storage/what-are-the-performance-expectations-for-block-storage
- ブロックストレージ制約（同一リージョン・16 volume）: https://docs.vultr.com/products/cloud-storage/block-storage
- cloud-init user_data デプロイ: https://docs.vultr.com/how-to-deploy-a-vultr-server-with-cloudinit-userdata
- Terraform（vultr/vultr）+ cloud-init 公式ガイド: https://docs.vultr.com/provision-a-vultr-cloud-server-with-terraform-and-cloud-init
- 1Password Service Accounts（headless op CLI）: https://developer.1password.com/docs/service-accounts/
- Cloudflare R2 料金（egress 無料）: https://developers.cloudflare.com/r2/pricing/
- Hetzner 課金モデル（概要）: https://docs.hetzner.com/cloud/billing/faq/
- Hetzner ロケーション（日本なし）: https://docs.hetzner.com/cloud/general/locations/
- 既存資産: `infra/terraform/streaming/README.md` / `main.tf` / `variables.tf`、`.claude/skills/streaming/SKILL.md`
