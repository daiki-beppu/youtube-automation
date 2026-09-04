# 1 チャンネル = 1 リポジトリへの回帰: マルチチャンネル workspace（ADR-0022）を supersede する

## Status

accepted (2026-09-03, wayfinder map #4871 / 起草 #4879)。**ADR-0022（マルチチャンネル workspace）を supersede** する。

- 削除リリースは **first-party 7 チャンネルの export 完了 + workspace リポジトリの archive** をゲートにし、版数では切らない（§移行計画）
- amended (2026-09-04, #4902): 逆移行 runbook の残論点（dogfood 対象の選定 #4878 / 独立リポジトリの GitHub 新設手順 #4880 / channel registry からの workspace エントリ登録解除 #4889）の確定を §移行計画へ同期した。#4880 で警告リリースを A3 / A4 に縮小して B7 を追加し、終着点を「ADR と CHANGELOG 以外に workspace の痕跡を残さない」に再定義している（§Decision 9）
- 実装 issue: epic [#4905](https://github.com/daiki-beppu/youtube-automation/issues/4905)（2026-09-04 起票）。sub-issue 16 件 = 前提 minor（`yt-channel-export` #4906 / registry 置換 #4907 / A3 #4908 / A4 #4909）+ トラッキング #4910 + fan-out 系（`apply --commit` #4911 / `yt-channels list` #4912 / `yt-channels update` #4913 / `yt-session-start` #4914）+ 削除 major（B1 #4915 → B2 #4916 → B3 #4917 → B4 #4918 → B5 #4919 → B6 #4920 → B7 #4921）。依存の正は各 issue の blockedBy

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
7. **fan-out の台帳は dashboard の channel registry（`~/.config/tayk/channels.json`）を流用する。** schema（絶対パス文字列の JSON 配列）は変えず、registry は「dashboard の表示対象」と「fan-out の適格チャンネル」の両方を列挙する台帳になる。channel export が registry 初の writer となり、export の最終段で workspace エントリを同じ index で戻し先に置換する（一致が無ければ追加、#4889）。移行期間中に残る未 export の workspace 内エントリは fan-out が skip する。
8. **逆移行は `yt-channel-export <slug> <dest>`（copy + 検証のみ）で行い、workspace 側は変更しない。** ADR-0022 の `yt-channel-import` と対称。git 履歴は捨て、archive 済みの旧リポジトリは復活させず新設し、push 直後に削除する。仕様は #4876、GitHub 新設と命名は #4880。
9. **deprecation は警告リリース → 削除リリースの 2 段で、版数は semver 規則に任せる。** 警告リリースは CHANGELOG の `deprecated` fragment と逆移行ガイドの公開で告知し、コード上の警告（`find_workspace_root` の `DeprecationWarning` / `yt-doctor` の warn check）は置かない（外部 workspace 利用者の痕跡が無く、削除リリースで消える一時コードのため、#4880）。削除は CLI 削除を含むため規則上 major で、終着点は ADR と CHANGELOG 以外から workspace の痕跡を無くすこと。廃止 hook の prune を `yt-skills sync --asset settings` に追加し、旧 guard hook を下流から除去する。計画は #4877（#4880 で修正）。
10. **ADR-0022 のうち次の 3 点は維持する。** benchmark 系の `--competitor` リネーム（`--channel` の予約は解けるが 2 度目の breaking を避ける）、プロセス内 singleton 切替による横断実行の恒久禁止、生成成果物を git 管理外にするデータ 4 分類への忠実化。

## 移行計画

決定チケット #4877（deprecation 計画）/ #4878（dogfood と 1 周）/ #4880（GitHub 新設と終着点）/ #4889（registry の置換）の確定内容。本節は「何を・どの順で・何をもって完了とするか」だけを持ち、操作手順（凍結・等式検証・切り戻し・手編集）は逆移行ガイド `docs/migration/workspace-to-single-repo.md` に置く。

- **終着点**（#4880 で再定義）: ADR（ADR-0022 の ⚠️ 注記と本 ADR）と CHANGELOG 系だけが履歴として残り、src / tests / skills / docs / site から workspace の文字が 0 件になる。workspace 用に追加したコード（import / export / guard / registry の workspace パス定義）も全て削除する
- **逆移行の順序**: 1 チャンネルを export → 独立リポジトリでフルライフサイクル 1 周を実走 → 残り 6 チャンネル。ADR-0022 の段階移行と同じ形で、越境事故の防止は guard ではなくこの順序で吸収する
  - **dogfood チャンネルは 002ch-deepfocus365**（#4878。live 82 + planning 進行中で、全段階を実データで踏める唯一の候補。003ch は cloud 経路、007ch は live 0、004ch は進行中の collection が無い）。進行中の planning collection は独立リポジトリ側で続行し、workflow-state の継続性も検証に含める
  - **前提リリース**: `yt-channel-export` + 逆移行ガイド（A4）を含む最初の minor で開始する。fan-out（#4874）と SessionStart 自動追従（#4875）は前提にせず、独立リポジトリ側の追従は `/automation --update` wizard で 1 回行う（単一リポジトリで wizard が動く証拠を兼ねる）。fan-out / SessionStart は toolkit 側の単体テストと 6 チャンネル展開後の初回 fan-out で検証する
  - **1 周の定義**: 独立リポジトリ側で `/wf-next` を planning から upload まで通し、公開後処理（playlist / community / pinned）・`/analytics`（collect → report）・`/audit --metadata` を各 1 回。**合格 = 移行起因の失敗（ConfigError / パス不在 / workspace 検出の誤発火）0 件 + `yt-doctor` green + dashboard に独立リポジトリ側が表示されること**。動画の成績は判定に含めない
  - **1 周中の workspace 側**: export 済み slug は 3 層で凍結する（`chmod -R a-w` / `.claude/CLAUDE.local.md` の凍結中一覧 / launchd 定期収集の unload）。launchd は dogfood 開始時点で workspace 全体について止め、未 export チャンネルの制作は workspace 側で従来どおり続ける。凍結は registry に触らない
  - **失敗の扱い**: fix-forward を既定とし、移行起因の失敗は dest と凍結を維持したまま toolkit へ修正 PR を出してリリース後に再実行する。rollback は「独立リポジトリで collection を 1 つも前に進められない構造的欠陥」に限る。**export から 14 日**を上限とし、超えたら fix-forward 中でも 6 チャンネル展開を始めず wayfinder map #4871 へ差し戻す
  - **残り 6 チャンネル**: 001 → 005 → 006 → 004 → 007 → 003 の順（進行中なし・小さい順。planning 中の 007ch と 12GB + cloud 前提の 003ch を最後）で、1 セッションにまとめて実行する。各チャンネルは 4 点 smoke（export の等式 pass / `yt-doctor` green / `/wf-status` が collections を読める / `/analytics --status` が返る）のみで、フル 1 周は dogfood の 1 回で済ませたと見なす
- **channel registry の扱い**（#4889）: `yt-channel-export` が export の最終段で、workspace エントリ（`<workspace>/channels/<slug>`）を**同じ index で戻し先に置換**する（一致が無ければ追加のみ = 007ch、戻し先が既にあれば no-op、照合は `normpath` + `resolve()`）。宣言順 = 開設順 = fan-out の直列処理順を保つため末尾追加はしない。書込は tmp + rename で、直前に `channels.json.bak` を 1 世代残す。書込に失敗したら戻し先は残して手編集すべき内容を印字し非 0 で終了する。登録解除の CLI は持たず、rollback の戻しは `.bak` からの手編集。archive 後に registry へ残った不在パスは fan-out の error（#4874）を維持する
- **GitHub リポジトリの新設**（#4880）: リポジトリ名 = workspace slug（`001ch-afro-deep-noir` … `007ch-slowpour`）、戻し先 = `/Users/mba/02-yt/<slug>` とし、ディレクトリ名 = リポジトリ名 = registry パスの basename = `YTA_CHANNEL_SLUG` に識別子を 1 本化する。初回 commit は export 分と bootstrap（`/setup --tool`）分の 2 commit に分け、export 分の `git ls-files` を workspace 側と突き合わせる等式検証（差分は export が書く `.gitignore` / `auth/client_secrets.template.json` の 2 ファイルだけ）を push の前提にする。**archive 済み旧リポジトリ 6 件は新リポジトリの push 直後に削除**し、周辺 4 リポジトリ（`youtube-template` / `youtube-channels` / `youtube-fantasy-celtic-music` / `youtube-8bah`）も最初の export と同時に削除する。Actions secrets は写さず、cloud を使うチャンネルだけ `/wf-new --schedule` で新規設定する（単一リポジトリ非対応 2 点の修正 #4899 が入ったリリース以降）
- **完了条件**（5 点が揃った時点で削除リリースのゲートが開く）: (1) 7 リポジトリが push 済みで等式 pass、(2) registry が独立リポジトリ 7 パスのみ（workspace パス 0 件）、(3) launchd plist を削除、(4) 旧リポジトリ 6 + 周辺 4 が削除済み、(5) workspace リポジトリに最終 commit「7ch export 完了」を積んで `gh repo archive`。ローカル workspace ディレクトリ（メディア込み 19GB 超）は archive 直後に削除する
- **進捗の記録**: 実装 effort の開始時にトラッキング issue を 1 件（7 チャンネル × export / push / 旧リポジトリ削除 / smoke の表）切り、dogfood 合格もそこへ comment で記録する
- **警告リリース**（A3 / A4 のみ。互いに独立、stack 不要。`### Deprecated` fragment を含むため規則上 minor）
  - A1（`find_workspace_root` の `DeprecationWarning`）と A2（`yt-doctor` の `workspace_deprecated` check）は #4880 で落とした。外部 workspace 利用者の痕跡が無く、B5 で消える一時コードのため。`deprecated` fragment は A3 / A4 に載せる
  - A3 `skills_sync/_settings.py` に廃止 hook の prune、template から guard hook 2 件（PreToolUse `check` / SessionStart `context`）を除去、settings test 差し替え（B1 の技術的前提）
  - A4 逆移行ガイド `docs/migration/workspace-to-single-repo.md` を公開 map（#4802）・`site.yml` paths・Cloudflare watch path へ登録し、旧 workspace 移行ページを即撤去する（site の `legacyRoute` / `site.yml` paths / Cloudflare watch path も同時に外し、navigation 6 → 5）
- **削除リリース**（依存順の stack。**7 チャンネルの export 完了 + workspace archive がゲート**。`### Removed` を含むため規則上 major）
  - B1 console script 4 件（`yt-channel` / `yt-channel-import` / `yt-workspace-status` / `yt-workspace-guard`）の削除と `pyproject` / `entrypoints` / harness gate / CLI 対応表 / test の整理
  - B2 doctor の workspace 分岐削除
  - B3 OAuth 候補列 `<workspace_root>/auth/` の削除と `oauth-setup.md` / onboarding 契約テスト
  - B4 state Git / skills sync / dashboard refresh / hybrid runner に残る workspace 分岐（到達不能分岐）の削除
  - B5 共通 `--channel` / `CHANNEL` / workspace 検出の本体削除（`find_workspace_root` を**最後に**消す）、`removed` fragment
  - B6 docs / site 撤去（`architecture.md` 用語集の `workspace` / `channel slug` と、棚卸し #4873 で「残す」に分類した物のうち workspace の語を含む物の全消し）、`migration` fragment、`docs/upgrades/<version>.md`
  - B7 `yt-channel-export`・逆移行ガイド・`channel_registry` の workspace パス定義の削除（stack 末尾。7 チャンネルの export 完了 + workspace archive 後にしか消せない物）
- **ADR-0022 の扱い**: Status を `superseded (2026-09-03) by ADR-0029` にし、本文冒頭に反転 / 維持の一覧を ⚠️ 注記で置く。本文は履歴として不変
- 実装 issue は epic #4905 の sub-issue 群（§Status）。wayfinder map #4871 は 2026-09-04 に close 済み

## Consequences

- **external user（単一チャンネルリポジトリ）**: workspace 経路の削除による影響はない。ただし **SessionStart 自動追従（commit まで）が template hook 経由で既定 ON で届く**。これは ADR-0022 の「破壊的変更なし」とは質が違う挙動変化であり、CHANGELOG と upgrades ガイドで opt-out 環境変数とともに告知する
- **external user（workspace 利用者）**: 削除リリース（major）までに `yt-channel-export` で独立リポジトリへ戻す必要がある。警告リリースの `deprecated` fragment、削除リリースの `removed` + `migration` fragment、逆移行ガイドで案内する
- **channel registry**: ADR-0013 の「dashboard が消費する読み取り専用の台帳」から、fan-out の適格チャンネル列挙を兼ね、channel export が書き込む台帳へ役割が広がる。schema は変えないため dashboard 側の変更はない。登録 UX の不在と `~/.config/tayk/` が tayk と共有される点は引き続き未解決。workspace エントリは export が同位置で戻し先に置換するため、dashboard に同名チャンネルが 2 行並ぶ期間は無い（#4889）
- **cloud runner**: cloud session は「チャンネルリポジトリに commit 済みの skills」を正とし、cloud 側では追従しない（`CI` で no-op）。hybrid cloud（#4070）の前提は変わらない
- **移行期間**: workspace と独立リポジトリがディスク上で併存するが、export 済み slug は workspace 側で凍結し、registry は戻し先だけを指す。fan-out は未 export の workspace 内エントリを skip する
- **launchd 定期収集**: workspace の `scripts/collect_reporting.sh` + launchd plist は dogfood 開始時点で止め、完了時に削除する。単一リポジトリ版の定期収集は fan-out CLI が存在してから初めて設計できるため別 effort とし、1 周中は手動 `/analytics` で代替する（wayfinder map #4871 の Out of scope）
- **git 履歴**: 001〜006ch は workspace 移行時に旧リポジトリの履歴を捨てており、今回さらに workspace の履歴も捨てる（2 度目）。復旧は Suno プレイリスト・YouTube・export 後の初回 commit を正とする
- **first-party の workspace root 固有物**: `.claude/CLAUDE.local.md` / `settings.local.json` / `scripts/collect_reporting.sh` + launchd plist / 手書き `docs/*.md` は export の責務外であり、runbook の「手で持ち込む物の一覧」に従って手で持ち直す。同居運用のために生まれた物で、単一リポジトリ回帰で大半は不要になる
- **ディスク**: export はメディアを含む `channels/<slug>/` の実体を丸ごと copy する（003ch は約 12GB）ため、workspace 側を残置する期間はチャンネル分のディスクを二重に使う。workspace 側（メディア込み 19GB 超）は完了条件 5 点が揃って archive した直後に丸ごと削除する（メディアは 7 リポジトリへ copy 済み、Time Machine が控え）

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
- wayfinder map #4871、棚卸し #4872 / #4873、仕様 #4874 / #4875 / #4876 / #4877、逆移行 runbook #4878 / #4880 / #4889、docs 同期 #4902
- 逆移行ガイド `docs/migration/workspace-to-single-repo.md`（警告リリース A4 で公開、B7 で削除）
- 単一リポジトリで hybrid cloud runner が動かない 2 点の修正 #4899（地図外）
