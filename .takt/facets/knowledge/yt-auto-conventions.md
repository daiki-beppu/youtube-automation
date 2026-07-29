# 規約文書知識（規約整合性判定）

このリポジトリの設計・実装が規約に整合しているかを判定するための知識。**規約文書の本文が正であり、本ファイルは索引と判定基準にすぎない。** 判定の根拠には必ず規約文書本文の該当箇所を引用すること。

本ファイルの記述が規約文書本文と食い違っていたら、**本文に従って判定し、本ファイルの修正をレポートの「スコープ外の発見」に記録する**こと。索引が古いまま放置されると、次の判定も同じだけ狂う。

## 判定前に必ず読むファイル

| ファイル                                         | 内容                                                                                                                       |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `CLAUDE.md`（リポジトリルート）                  | 非自明な規約・落とし穴の一覧（設定アクセス / エラーハンドリング / import 規約 / 依存ポリシー / スクリプト配置 / skill frontmatter / パッケージング / TS レイヤー例外 / セキュリティ）。**全変更が照合対象** |
| `docs/development.md`                            | パッケージング / 品質ゲート（CI）/ dashboard / extensions / skill 開発ループの詳細                                         |
| `docs/skill-design/skill-authoring-guidelines.md` | skill の設計規約。`.claude/skills/**` を変更する差分で照合する                                                            |
| `docs/adr/`                                      | 歴史的 ADR 群。現在も効力を持つのは主に **ADR-0013**（dashboard の TS 例外）と **ADR-0021**（別リポ再出発・Python メンテナンスモード）。TypeScript / dashboard / extensions に触れる差分では必ず Read する |
| `docs/takt-operations.md`                        | issue / worktree / PR 運用。`.takt/**` への変更はここを照合する                                                            |

`docs/adr/` の古い ADR（TS rewrite 期の 0001〜0009 等）は歴史的文書として読む。現行規約の根拠には `CLAUDE.md` / `docs/development.md` を優先し、ADR 同士が食い違う場合は後発の ADR-0021 が優先する。要約や記憶で判定してはならない。

## 機械担保（契約テスト）

`CLAUDE.md` / docs の規約の多くは契約テストで機械担保されている（`tests/test_*_contract.py` 群、`tests/test_no_google_auth_httplib2_direct_import.py`、`tests/test_skill_frontmatter_yaml.py`、`tests/test_features_catalog_documentation.py` 等）。

- 規約文書を改訂するときは、対応する契約テストも同じ差分で改訂する（文書だけ直すとテストが落ち、テストだけ直すと文書とドリフトする）
- 契約テストの削除・skip・アサーション緩和で規約との衝突を解消することは、規約違反の隠蔽として扱う

## 代表的な規約と違反パターン

網羅ではない。規約の文言は本文を読むこと。

| 規約                                             | 違反パターン                                                                                                               |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| メンテナンスモード（ADR-0021 / CLAUDE.md）       | `dashboard/` / `extensions/` 以外への TypeScript 実装追加。tayk core の持ち込み。削除済み `packages/` の復活               |
| 設定アクセス（CLAUDE.md）                        | チャンネル固有値のハードコーディング。`load_config` を経由しない設定読み込み。新規設定キーで dataclass / `_build_*` / `_REQUIRED_KEYS_BY_SECTION` の追随漏れ |
| import 規約（CLAUDE.md）                         | fully-qualified `from youtube_automation.xxx import ...` 以外のパッケージ内 import                                         |
| エラーハンドリング（CLAUDE.md）                  | 生の `Exception` / `KeyError` の catch。`infrastructure/errors.py` のドメイン例外を使わないエラー表現                      |
| CLI 追加（CLAUDE.md）                            | `yt-*` prefix でない新規 CLI。`pyproject.toml [project.scripts]` への未登録。値域の決まった引数に `choices=` が無い        |
| skill frontmatter（CLAUDE.md）                   | SKILL.md の `description:` が double-quoted string でない                                                                  |
| スクリプト配置（CLAUDE.md）                      | ルート直下 `scripts/` の新設（skill 付属スクリプトは `.claude/skills/<skill>/references/` へ）                             |
| 依存ポリシー（CLAUDE.md / docs/development.md）  | `google_auth_httplib2` の直 import 新規追加                                                                                |
| CHANGELOG（docs/development.md）                 | 実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）変更で `[Unreleased]` 未更新（`skip-changelog` ラベルなし） |
| セキュリティ（CLAUDE.md）                        | `auth/client_secrets.json` / `auth/token.json` / `.env` のコミット。`_SECRET_REFS` を経由しないシークレット解決            |

## 逸脱の扱い

「黙って逸脱しない。技術的に正当な逸脱は規約文書の改訂を要求する」を原則とする。したがって判定は 3 値になる。

- **整合**: 規約文書の記述に沿っている
- **要規約改訂**: 逸脱に技術的な正当性はあるが、規約文書が未改訂。差分に規約文書（および対応する契約テスト）の改訂が含まれていなければ差し戻す
- **違反**: 正当性がない、または正当性が示されていない逸脱。差し戻す

「既存コードがそうなっているから」は正当性にならない。既存の違反はそれ自体を「スコープ外の発見」として記録する対象であり、新規逸脱の免罪符ではない。

## スコープの規律

本リポジトリは Python 版のメンテナンスモード（ADR-0021）。TS 版の新機能・アーキテクチャ刷新は別リポ（tayk）の担当であり、本リポジトリの差分に紛れ込んでいたらスコープ逸脱として指摘する。dashboard の TypeScript は ADR-0013 の範囲（Python の読み取り専用 JSON API に従属する表示層）に限る。
