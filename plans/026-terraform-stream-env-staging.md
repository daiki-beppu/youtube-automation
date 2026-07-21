# Plan 026: streaming VPS provisioning の stream key / webhook を素の /tmp 経由から 0700 ディレクトリ staging に変更する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 37b362ce..HEAD -- infra/terraform/streaming/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Status**: DONE
- **Priority**: P3
- **Effort**: S
- **Risk**: LOW（provisioner の staging パス変更のみ。サービス定義・鍵管理は不変）
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `37b362ce`, 2026-07-21
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/2395

## Why this matters

streaming VPS の Terraform provisioning で、YouTube stream key を含む env ファイルと Discord webhook URL を含む env ファイルを、SSH の `file` provisioner がまず `/tmp/*.tmp` に書き、その後の `remote-exec` が `install -m 0600` で本配置して削除している。`file` provisioner はデフォルト権限（通常 0644）で書くため、`install` が走るまでの数秒間、stream key / webhook URL が world-readable になる窓がある。単一テナント VPS なので悪用可能性は極めて低いが、同じ main.tf 内の live-chat-reply 経路は既に `install -d -m 0700` で作った専用ディレクトリに staging する正しいパターンを実装済みであり、揃えるだけで窓が消える。第 5 回セキュリティ監査（2026-07-21）の finding #2。

## Current state

関係ファイル:

- `infra/terraform/streaming/main.tf` — VPS provisioning 本体。問題箇所は `youtube-stream` 側の file provisioner 2 つ（L118-131）と remote-exec（L171-177）。**手本となる live-chat-reply 側の正しいパターンは L235-286**
- `infra/terraform/streaming/variables.tf` — `stream_key` / `discord_webhook_url` は `sensitive = true` 済み（変更不要）
- `tests/test_terraform_bootstrap.py` / `tests/streaming/` — Terraform まわりの既存テスト（内容確認の上、staging パスをアサートしていれば追従）

`main.tf:118-131`（現状・問題箇所）:

```hcl
  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream.env.tftpl", {
      video    = "${var.install_root}/videos/current.mp4"
      rtmp_url = "rtmp://a.rtmp.youtube.com/live2/${var.stream_key}"
    })
    destination = "/tmp/youtube-stream.env.tmp"
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/youtube-stream-healthcheck.env.tftpl", {
      webhook = var.discord_webhook_url
    })
    destination = "/tmp/youtube-stream-healthcheck.env.tmp"
  }
```

`main.tf:171-177`（現状・本配置部）:

```hcl
  provisioner "remote-exec" {
    inline = [
      "umask 0077",
      "install -m 0600 -o root -g root /tmp/youtube-stream.env.tmp /etc/youtube-stream.env",
      "rm -f /tmp/youtube-stream.env.tmp",
      "install -m 0600 -o root -g root /tmp/youtube-stream-healthcheck.env.tmp /etc/youtube-stream-healthcheck.env",
      "rm -f /tmp/youtube-stream-healthcheck.env.tmp",
```

手本（live-chat-reply 側、`main.tf:235-241` 付近）: file provisioner の **前に** remote-exec で `install -d -m 0700 -o root -g root /run/live-chat-reply` を実行し、file provisioner の destination を `/run/live-chat-reply/...` にしている。provisioner はブロック記述順に直列実行されるので、「先に 0700 ディレクトリを作る remote-exec → そこへ file provisioner」で権限窓が消える。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| フォーマット検査 | `terraform -chdir=infra/terraform/streaming fmt -check` | exit 0 |
| 構文検証（初回） | `terraform -chdir=infra/terraform/streaming init -backend=false` | 成功（provider download のみ） |
| 構文検証 | `terraform -chdir=infra/terraform/streaming validate` | `Success! The configuration is valid.` |
| 関連テスト | `uv run pytest tests/test_terraform_bootstrap.py tests/streaming -q` | all pass |

（Terraform v1.15.8 がローカルにあることは確認済み。`init -backend=false` は state に触れない読み取り系操作）

## Scope

**In scope**:
- `infra/terraform/streaming/main.tf`
- `tests/streaming/` / `tests/test_terraform_bootstrap.py`（staging パスをアサートしているテストがあれば追従のみ）
- `plans/README.md`（status 更新）
- `CHANGELOG.md` — infra はゲート対象外だが、セキュリティ改善として `[Unreleased]` 追記を推奨（任意）

**Out of scope**:
- live-chat-reply 側の provisioner（L235 以降）— 既に正しいパターン。触らない
- SSH host key の pre-seed 方式（`tls_private_key.ssh_host` / cloud-init）— 第 5 回監査で「host-key pinning のための意図的トレードオフ」として受容済み。変更しない
- `variables.tf` / templates / systemd unit — 変更不要
- **`terraform apply` / `plan` の実行** — 実 VPS に触れる操作は行わない（検証は fmt / validate / pytest まで）

## Git workflow

- 作業は worktree（`$REPO_ROOT/.worktrees/<slug>/`）上で行う
- Branch 例: `advisor/026-terraform-stream-env-staging`
- Commit 例: `fix(streaming): stream env の staging を 0700 ディレクトリに変更する`
- push / PR はオペレーターの指示があるまで行わない

## Steps

### Step 1: staging ディレクトリ作成の remote-exec を file provisioner の前に挿入

`main.tf` の `youtube-stream` 側 file provisioner 群（L113 の `var.video_path` 転送より後、L118 の env 転送より前）に挿入:

```hcl
  provisioner "remote-exec" {
    inline = [
      "install -d -m 0700 -o root -g root /run/youtube-stream-provision",
    ]
  }
```

（`/run` は tmpfs なので再起動で自動消滅する — live-chat 側と同じ選定理由）

### Step 2: env 2 ファイルの destination と install 元を差し替え

- L123: `destination = "/tmp/youtube-stream.env.tmp"` → `"/run/youtube-stream-provision/youtube-stream.env.tmp"`
- L130: `destination = "/tmp/youtube-stream-healthcheck.env.tmp"` → `"/run/youtube-stream-provision/youtube-stream-healthcheck.env.tmp"`
- remote-exec（L171-177）の `install` / `rm -f` の元パス 4 箇所を同様に差し替え、最後の `rm -f` の後に `"rm -rf /run/youtube-stream-provision"` を追加（live-chat 側の後始末パターンに合わせる）

**Verify**: `rg -n '/tmp/youtube-stream' infra/terraform/streaming/` → 0 件

### Step 3: fmt / validate / テスト

**Verify**:
1. `terraform -chdir=infra/terraform/streaming fmt -check` → exit 0
2. `terraform -chdir=infra/terraform/streaming init -backend=false` → 成功（既に init 済みならスキップ可）
3. `terraform -chdir=infra/terraform/streaming validate` → `Success!`
4. `uv run pytest tests/test_terraform_bootstrap.py tests/streaming -q` → all pass（`/tmp/youtube-stream` をアサートしているテストがあれば新パスに更新）

## Test plan

既存の `tests/test_terraform_bootstrap.py` / `tests/streaming/` が main.tf の内容を静的にアサートしている場合のみ追従修正。新規テストを書くなら「`main.tf` に `/tmp/youtube-stream` という文字列が現れない」ことの回帰テスト 1 本（既存の repo_contract 系テストの書き方に倣う）で十分。

## Done criteria

- [ ] `rg -n '/tmp/youtube-stream' infra/terraform/streaming/` → 0 件
- [ ] `terraform -chdir=infra/terraform/streaming fmt -check` → exit 0
- [ ] `terraform -chdir=infra/terraform/streaming validate` → Success
- [ ] `uv run pytest tests/test_terraform_bootstrap.py tests/streaming -q` → all pass
- [ ] in-scope 外のファイルに変更なし（`git status`）
- [ ] `plans/README.md` の status 更新

## STOP conditions

- "Current state" の抜粋と実コードが一致しない（drift）
- `youtube-stream` 側の provisioner 実行順が想定（video → env → service → remote-exec）と異なる構造になっていた
- validate が provisioner 順序起因で fail し、1 回の修正で解消しない
- 修正が templates / variables / live-chat 側に波及しそうになった（out of scope）

## Maintenance notes

- 次回 `terraform apply` 時にこの provisioner 差分で `null_resource` / instance の再 provisioning が走る可能性がある。**apply はオペレーターが実施**し、配信停止ウィンドウを許容できるタイミングで行うこと
- 今後 provisioner でシークレットを VPS に渡すときは必ずこの `/run/<name>-provision`（0700）パターンを使う
- レビュー観点: remote-exec の挿入位置（file provisioner より前）と、後始末 `rm -rf` の追加
