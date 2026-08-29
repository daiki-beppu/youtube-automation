# CLAUDE.md

YouTube チャンネル運営を自動化するツールキット。`youtube-channels-automation` パッケージとして配布し、下流のチャンネルリポジトリ（`CHANNEL_DIR`）へ `yt-skills sync` で導入される 2 層構造。

詳細は必要になった時点で参照する: アーキテクチャ・責務境界・依存方向・公開/内部境界・新規ファイル配置規則・変更時の参照対応表は `docs/architecture.md`、bootstrap は `docs/development.md#開発者-bootstrap正規入口`（パッケージング / 品質ゲート / dashboard 開発も `docs/development.md`）、issue / worktree 運用は `docs/takt-operations.md`、スキル設計は `docs/skill-design/skill-authoring-guidelines.md`。

## 非自明な規約・落とし穴

- devShell 必須（direnv または `nix develop`。shellHook が `uv sync` を自動実行）。非対話 shell は `nix develop --command <cmd>`。Codex Cloud task の例外は `AGENTS.md`「Codex Cloud の検証」を正とする
- チャンネル固有値は `load_config` 経由でのみ取得（`config.meta.channel_name` 形式）。ハードコード禁止。新キー追加は dataclass（`configuration/<section>.py`）+ `loader.py::_build_*` + 必須なら `_REQUIRED_KEYS_BY_SECTION` の 3 点セット — 最後の登録を忘れやすい
- 下流の `config/channel/*.json` は責務別分割。optional は shorts.json / comments.json / pinned-comment.json / distrokid.json / community-draft.json（全容は `docs/architecture.md`）
- 本ファイルや README / ONBOARDING / AGENTS の実行契約は機械担保されている — 文言を変更・削除するときは `tests/test_*_contract.py` / `test_skill_docs_consistency.py` を確認
- 例外は `core/errors.py` のドメイン例外（`ConfigError`, `YouTubeAPIError` 等）を使う。生の `Exception` / `KeyError` を catch しない
- パッケージ内 import は `from youtube_automation.xxx import ...` の fully-qualified 固定
- 新規 CLI は必ず `yt-*` プレフィックスで `pyproject.toml::[project.scripts]` に登録。CLI は SKILL.md から呼ばれるインターフェースなので、引数は `choices=` / `help=` で自己記述にする
- `google-auth-httplib2` の直 import を新規追加しない（回帰テストで機械担保。経緯は `docs/migration/google-auth-httplib2.md`）
- Gemini の画像生成は Vertex AI（ADC）経路に統一し、Gemini CLI の subprocess 起動を追加しない（回帰テストで機械担保）
- スクリプトは該当 skill の `.claude/skills/<skill>/references/` 配下に置く。ルート直下に `scripts/` を設けない
- skill の実体は常に `.claude/skills/` 側（`.agents/skills` は Codex 用 symlink — 編集しない）。SKILL.md frontmatter は `purpose:` が必須で、`description:` は double-quoted 必須（値内の `: ` が strict YAML で誤解釈される）。検証は `uv run yt-skills lint`
- `.claude/skills/` と `.claude/CLAUDE.template.md` は wheel に force-include される。バージョン bump は `pyproject.toml::version` のみ（`__version__` は動的読込）
- 品質ゲート（ruff / CHANGELOG / any 型）はローカル git hook ではなく CI で担保。通常 PR の変更履歴は `changelog.d/<issue>-<slug>.<type>.md` に追加し、`CHANGELOG.md` を直接編集しない（`release/*` の release prepare だけが例外）
- fragment の `<type>` は added / changed / deprecated / removed / fixed / security / migration の 7 種のみ（commit の `docs` / `ci` / `chore` は type として使えない）。本文は全非空行を `- ` 始まりの bullet にする。書式の正本は `changelog.d/README.md`、検証は `python .github/scripts/validate-changelog-fragments.py`
- TypeScript は `dashboard/` のローカル表示層（ADR-0013）、`audio-studio/` のローカル音源編集表示層（ADR-0028）、`site/` の公開リリースノート静的サイト（ADR-0023）、`extensions/` の閉じた境界だけで許可する。他の TypeScript 実装・tayk core・削除済み `packages/` の復活は禁止（`docs/adr/0021-separate-repo-restart.md`）。dashboard / audio-studio から `extensions/shared-ui` を import しない

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は絶対にコミットしない
- シークレット解決順: `os.environ` → `op read`（1Password CLI）→ `ConfigError`。参照定義は `infrastructure/secrets.py::_SECRET_REFS`。テストでは `YOUTUBE_AUTOMATION_DISABLE_OP_READ=1`（既定有効）で `op read` をスキップ
- AI 系（Vertex AI）は ADC 認証のため `op` 取得は不要

## 開発ワークフロー

- 標準ルートは takt: `takt add '#<N>'` でタスクに合う builtin workflow を選び、`auto_pr` 有効で `takt run`。使い分けと運用は `docs/takt-operations.md`（既存 `takt:*` ラベルは履歴メタデータのみ — 新規に付与しない）
- issue は **1 issue = 1 PR = 1 振る舞い変更**の粒度に割る（要件 3 件以上 / 影響ファイル 4 件以上 / 独立した関心事 2 つ以上 / 複数 PR 見込みのいずれかで分割）。分割は sub-issue で階層化し、実装順の依存は `addBlockedBy` で表す
- PR は **stacked PR 前提**。takt 経路は生成された PR を `gh stack link <下段PR> <上段PR>` で後からまとめ、対話経路は worktree 内で `gh stack init` / `add` で積む。merge は `gh pr merge` ではなく `gh stack merge --yes --squash`（非対話フラグと落とし穴は `docs/takt-operations.md`）
- 人間と対話しながら進めたいタスク・要件が固まっていない探索は `/issue-direct <N>`（issue 専用 linked worktree、1 worktree = 1 stack）
- takt 経路以外の開発は必ず issue 専用 linked worktree 上で行う（メイン作業ツリーで直接ブランチを切らない）
- commit は日本語 Conventional Commits + タイトル末尾に `(#<N>)`。stack の PR タイトルは commit から自動生成されるため 1 branch 1 commit に寄せる
- リリースは `/automation-release`（post-release は `/release-notes`）

## Agent skills

mattpocock-skills の engineering skills（to-tickets / triage / to-spec / wayfinder 等）が読むリポジトリ固有設定:

- Issue tracker: GitHub Issues（`gh` CLI 経由）— `docs/agents/issue-tracker.md`
- Triage labels: デフォルト 5 ラベル（`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`）— `docs/agents/triage-labels.md`
- Domain docs: 単一コンテキスト構成。グロッサリ正本は `docs/architecture.md`「プロジェクト用語集」（旧 `CONTEXT.md` 統合済み）+ `docs/adr/` — 読み方は `docs/agents/domain.md`
