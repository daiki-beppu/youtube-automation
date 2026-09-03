# 1 チャンネル = 1 リポジトリへの回帰: マルチチャンネル workspace（ADR-0022）を supersede する

## Status

accepted (2026-09-03, wayfinder map #4871 / 起草 #4879)。**ADR-0022（マルチチャンネル workspace）を supersede** する。

- 削除リリースは **first-party 7 チャンネルの export 完了 + workspace リポジトリの archive** をゲートにし、版数では切らない（§移行計画）
- 逆移行 runbook の残論点（dogfood 対象の選定 #4878 / 独立リポの GitHub 新設手順 #4880 / channel registry からの workspace エントリ登録解除 #4889）は本 ADR の決定に影響しない
- 実装 issue は起票後にここへ追記する

## Context

ADR-0022 は運営者の 6 チャンネルを `channels/<slug>/` として 1 リポジトリに同居させる workspace 構造を導入した。動機は「`yt-skills sync` / automation-update / git 管理がチャンネル数分だけ重複する」ことで、cutover までの運用負荷を下げる **メンテナンスモードの意図的な例外投資** と位置づけていた。導入から約 2 ヶ月で次の 5 点が明らかになり、前提と結論の両方が崩れた。

1. **AI エージェントが複数チャンネルの同居で混乱・誤操作する（主因）。** skills / CLAUDE.md は cwd = 1 チャンネルを暗黙の前提に書かれており、workspace ルートや別 slug の文脈が混ざると、対象チャンネルの取り違えや別チャンネルの資産への書き込みが起きる。`yt-workspace-guard` の PreToolUse check は事後の越境検出であり、混乱そのものは消えない。
2. **cwd 前提の基盤が workspace 非対応で壊れ続ける。** cloud sandwich runner の `--channel-dir .` 決め打ち（#4808）、cloud planning の postmortem allowlist の `collections/live/` 前置決め打ち（#4809）のように、hook / cloud runner / allowlist が「リポルート = チャンネル」を前提に書かれ、workspace だけで壊れる不具合が再発する。全経路を 2 構造対応にし続けるコストは、ADR-0022 が「併存構造は最悪」と退けたものと同質である。
3. **Claude Code の skills 探索制約が配布方式の選択肢を縛る**（2026-09-03 公式 docs 確認）。親ディレクトリの `.claude/skills` 探索はリポジトリルートで止まり、`permissions.additionalDirectories` では skills は読まれず（読むのは `--add-dir` / `/add-dir` のみで Desktop アプリではフラグを渡せない）、cloud session はリポジトリに commit 済みの `.claude/skills/` しか読まない。したがって「独立リポ群の上位に skills の hub を 1 つ置く」系の解は成立せず、各チャンネルリポに実体コピーを commit する現行方式を維持するしかない。
4. **「cutover までのつなぎ」という前提が撤回された。** ADR-0021 の Amendment（2026-09-01, #4779）で Python 版のメンテナンスモード純化と cutover は撤回され、本リポジトリはアクティブ開発を継続する。workspace は一時的な例外投資ではなく恒久構造になってしまい、上記 1・2 のコストを恒久に払うことになる。
5. **重複コストには別解が立つ。** ADR-0022 の動機である sync / update の重複は、構造を同居させなくても「channel registry を回って各リポで同じ更新を 1 操作で実行する」fan-out で解消できる。「一元管理」を *置き場を 1 つにする* 意味から *操作を 1 回にする* 意味へ再定義する。

workspace が達成したものは記録しておく。`yt-skills sync` / automation-update をチャンネル数分でなく 1 回にしたこと、git 管理対象をデータ 4 分類に忠実化して旧 6 リポジトリで約 4.7GB あった git 管理ファイルを管理外にしたこと、`--channel` を自チャンネルに予約して benchmark 系を `--competitor` に分けたことは、いずれも実現した。本 ADR はこのうち後ろ 2 つを維持し（§Decision 10）、前者だけを fan-out で置き換える。

## Decision

1. **構造: 1 チャンネル = 1 リポジトリ = 1 cwd を正規形に戻す。** workspace 経路（`channels/<slug>/` の規約検出、`--channel` / `CHANNEL` によるチャンネル選択、`yt-channel-import`、`yt-workspace-guard`、`yt-workspace-status`）は deprecated とし、削除リリースで物理削除する。
2. **skills / package の配布は各チャンネルリポジトリに commit された実体コピーを維持する。** 更新の経路は **channel registry fan-out（主）+ SessionStart 自動追従（補助）** の 2 本。fan-out は「全チャンネルを今すぐ」、SessionStart は「開いたチャンネルを遅延実行」で、1 チャンネル分の処理単位は完全に同一とする。
3. **CLI ランタイムは per-channel `pyproject` + `.venv` を維持する**（`uv tool install` による global 化はしない）。skills 内の `uv run yt-*` 呼び出し 552 箇所と hook・cloud runner を無傷に保つ。
4. **追従の単位は `yt-automation-update apply`（lock → sync → commit）に一元化する。** commit は `apply --commit` が担い、fan-out（`yt-channels update`）は registry の適格チャンネルを宣言順に直列で回って各チャンネルでこれをサブプロセス起動し、SessionStart（`yt-session-start`）は同じ処理を発火条件成立時に 1 回だけ実行する。更新の中身を orchestrator 側で再実装しない。仕様は #4874（fan-out）/ #4875（SessionStart）。
5. **自動化の安全弁を規約に依存させない。** local fix（同梱版と異なる下流側の同期資産）を検出したら止めて警告し、`--force-sync` を自動では渡さない。作業ツリーが clean（追跡ファイルに変更なし）でなければ skip、commit 失敗は巻き戻さない、`CI` / `GITHUB_ACTIONS` 下では SessionStart を即 no-op にする。
6. **SessionStart 自動追従は template hook として全下流リポジトリに既定 ON で配布する。** opt-out は環境変数 `YOUTUBE_AUTOMATION_DISABLE_SESSION_UPDATE=1` の 1 本で、config キーは持たない。
7. **fan-out の台帳は dashboard の channel registry（`~/.config/tayk/channels.json`）を流用する。** schema（絶対パス文字列の JSON 配列）は変えず、registry は「dashboard の表示対象」と「fan-out の適格チャンネル」の両方を列挙する台帳になる。channel export が registry 初の writer となり、移行期間中の workspace 内エントリは fan-out が skip する。
8. **逆移行は `yt-channel-export <slug> <dest>`（copy + 検証のみ）で行い、workspace 側は変更しない。** ADR-0022 の `yt-channel-import` と対称。git 履歴は捨て、archive 済みの旧リポジトリは復活させず新設する。仕様は #4876。
9. **deprecation は警告リリース → 削除リリースの 2 段で、版数は semver 規則に任せる。** 警告は `configuration/loader.py::find_workspace_root` の 1 点 + `yt-doctor` の warn check、削除は CLI 削除を含むため規則上 major。廃止 hook の prune を `yt-skills sync --asset settings` に追加し、旧 guard hook を下流から除去する。計画は #4877。
10. **ADR-0022 のうち次の 3 点は維持する。** benchmark 系の `--competitor` リネーム（`--channel` の予約は解けるが 2 度目の breaking を避ける）、プロセス内 singleton 切替による横断実行の恒久禁止、生成成果物を git 管理外にするデータ 4 分類への忠実化。

## 移行計画

- **逆移行の順序**: 1 チャンネルを export → 独立リポジトリでフルライフサイクル 1 周を実走 → 残り 6 チャンネル。dogfood 対象は #4878 で選定する。ADR-0022 の段階移行と同じ形で、越境事故の防止は guard ではなくこの順序で吸収する
- **警告リリース**（互いに独立、stack 不要。`### Deprecated` fragment を含むため規則上 minor）
  - A1 `find_workspace_root` に stderr 1 行 + `DeprecationWarning`、loader test を警告検証へ置換、`deprecated` fragment
  - A2 `yt-doctor` に `workspace_deprecated` check（status=warn、`yt-channel-export` を案内）
  - A3 `skills_sync/_settings.py` に廃止 hook の prune、template から guard hook 2 件（PreToolUse `check` / SessionStart `context`）を除去、settings test 差し替え
  - A4 旧移行ページ冒頭に deprecation 告知、逆移行ガイド `docs/migration/workspace-to-single-repo.md` を新規作成し公開 map（#4802）・`site.yml` paths・Cloudflare watch path へ登録
- **削除リリース**（依存順の stack。**7 チャンネルの export 完了 + workspace archive がゲート**。`### Removed` を含むため規則上 major）
  - B1 console script 4 件（`yt-channel` / `yt-channel-import` / `yt-workspace-status` / `yt-workspace-guard`）の削除と `pyproject` / `entrypoints` / harness gate / CLI 対応表 / test の整理
  - B2 doctor の workspace 分岐削除（A2 の check を含む）
  - B3 OAuth 候補列 `<workspace_root>/auth/` の削除と `oauth-setup.md` / onboarding 契約テスト
  - B4 state Git / skills sync / dashboard refresh / hybrid runner に残る workspace 分岐（到達不能分岐）の削除
  - B5 共通 `--channel` / `CHANNEL` / workspace 検出の本体削除（`find_workspace_root` を**最後に**消す）、A1 の警告撤去、`removed` fragment
  - B6 docs / site 撤去（旧移行ページ、navigation 6 → 5、`architecture.md` 用語集の `workspace` / `channel slug` 削除）、`migration` fragment、`docs/upgrades/<version>.md`
- **ADR-0022 の扱い**: Status を `superseded (2026-09-03) by ADR-0029` にし、本文冒頭に反転 / 維持の一覧を ⚠️ 注記で置く。本文は履歴として不変
- 実装 issue の起票は本 ADR 確定後の別 effort（wayfinder map #4871 の Out of scope）

## Consequences

- **external user（単一チャンネルリポジトリ）**: workspace 経路の削除による影響はない。ただし **SessionStart 自動追従（commit まで）が template hook 経由で既定 ON で届く**。これは ADR-0022 の「破壊的変更なし」とは質が違う挙動変化であり、CHANGELOG と upgrades ガイドで opt-out 環境変数とともに告知する
- **external user（workspace 利用者）**: 削除リリース（major）までに `yt-channel-export` で独立リポジトリへ戻す必要がある。警告リリースの `deprecated` fragment、削除リリースの `removed` + `migration` fragment、逆移行ガイドで案内する
- **channel registry**: ADR-0013 の「dashboard が消費する読み取り専用の台帳」から、fan-out の適格チャンネル列挙を兼ね、channel export が書き込む台帳へ役割が広がる。schema は変えないため dashboard 側の変更はない。登録 UX の不在と `~/.config/tayk/` が tayk と共有される点は引き続き未解決で、workspace エントリの登録解除は #4889 で扱う
- **cloud runner**: cloud session は「チャンネルリポジトリに commit 済みの skills」を正とし、cloud 側では追従しない（`CI` で no-op）。hybrid cloud（#4070）の前提は変わらない
- **移行期間**: workspace と独立リポジトリが併存し、dashboard には export 済みチャンネルが両方のパスで並ぶ。fan-out は workspace 内エントリを skip する
- **git 履歴**: 001〜006ch は workspace 移行時に旧リポジトリの履歴を捨てており、今回さらに workspace の履歴も捨てる（2 度目）。復旧は Suno プレイリスト・YouTube・export 後の初回 commit を正とする
- **first-party の workspace root 固有物**: `.claude/CLAUDE.local.md` / `settings.local.json` / `scripts/collect_reporting.sh` + launchd plist / 手書き `docs/*.md` は export の責務外であり、runbook の「手で持ち込む物の一覧」に従って手で持ち直す。同居運用のために生まれた物で、単一リポジトリ回帰で大半は不要になる
- **ディスク**: export はメディアを含む `channels/<slug>/` の実体を丸ごと copy する（003ch は約 12GB）ため、workspace 側を残置する期間はチャンネル分のディスクを二重に使う。workspace 側の削除は独立リポジトリで 1 周確認した後に手で行う

## Considered Options

### 構造

1. **1 チャンネル = 1 リポジトリ = 1 cwd への回帰（採用）** — AI の混乱・誤操作と cwd 前提基盤の再発を構造で消す
2. **workspace を維持し基盤側を workspace 対応に直し続ける（現状維持）** — hook / cloud runner / allowlist の全経路を 2 構造対応に保つコストが恒久化し、主因である AI の混乱は解消しない
3. **新規チャンネルのみ独立リポの併存** — ADR-0022 が退けたのと同じ「全 CLI が 2 構造対応」になる

### skills の配布

1. **各チャンネルリポジトリへの実体コピー + channel registry fan-out（採用）** — cloud / Desktop / CLI の全経路で同じ skills が読める唯一の方式。重複は操作の 1 回化で吸収
2. **user-scope（`~/.claude/skills`）** — 非 YouTube プロジェクトにも skills が漏れ、cloud session には届かない
3. **plugin 化** — plugin 管理コストと version pin の二重管理、cloud 非互換
4. **symlink hub / 上位ディレクトリの hub** — skills 探索がリポジトリルートで止まるため拾われない
5. **`--add-dir` hub** — `additionalDirectories` では skills が読まれず、Desktop アプリではフラグを渡せない

### CLI ランタイム

1. **per-channel `pyproject` + `.venv` の維持（採用）** — skills 内 `uv run yt-*` 552 箇所と hook・cloud runner が無傷
2. **`uv tool install` による global 化** — 552 箇所の書き換えと cloud 経路の再設計が必要で費用対効果が合わない

### 逆移行の手段

1. **`yt-channel-export`（copy + 検証、workspace 無変更）（採用）** — `yt-channel-import` と対称で、staging → 検証 → publish の idiom を流用できる。切り戻しは dest を消すだけ
2. **archive 済み旧リポジトリの復活** — workspace 移行後の state / collections / reports が無く、履歴の継ぎ足しは 2 系統の履歴を混ぜる。007ch は旧リポジトリ自体が無い
3. **手動 copy（runbook のみ）** — 7 回繰り返す手作業で symlink / auth / `.gitignore` の漏れが出る。external の workspace 利用者にも同じ手順を配る必要がある

### 廃止の仕方

1. **警告リリース → 削除リリースの 2 段（採用）** — semver 規則に従い、削除は 7 チャンネルの export 完了 + workspace archive をゲートにする
2. **即削除** — first-party 7 チャンネルが export を終える前に経路が消え、external の workspace 利用者にも予告なしの breaking になる
3. **恒久併存** — ADR-0022 が「全 CLI が 2 構造対応になり最悪」と退けた構造そのもの。Context 2 のコストを恒久に払う

## Related

- ADR-0013（multi-channel dashboard — channel registry の由来。台帳化の Amendment は 2026-09-03, #4879）
- ADR-0021 Amendment（メンテナンスモード撤回、2026-09-01）
- ADR-0022（マルチチャンネル workspace — 本 ADR が supersede）
- ADR-0024（クラウド移譲原則 — cloud は commit 済み skills を読む）
- wayfinder map #4871、棚卸し #4872 / #4873、仕様 #4874 / #4875 / #4876 / #4877
- 逆移行ガイド `docs/migration/workspace-to-single-repo.md`（警告リリース A4 で新規作成）
