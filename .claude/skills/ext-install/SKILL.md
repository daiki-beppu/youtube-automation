---
name: ext-install
description: "Use when Chrome 拡張（suno-helper / distrokid-helper）のインストール・更新をするとき。「拡張入れて」「extension インストール」で発動"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `/suno-helper`, `/distrokid-helper`

## Overview

automation リポジトリの GitHub Release (`ext-v*` タグ) に添付された Chrome 拡張 zip をダウンロードし、Chrome にインストール（または更新）する operator ガイドスキル。

対象拡張:
- **suno-helper** — Suno UI 上で曲の連続生成 + playlist 追加を自動化
- **distrokid-helper** — DistroKid 登録フォームへの自動入力

## 前提

以下を確認し、満たさなければ代替手段を案内する:

- `gh` CLI がインストール済みで `gh auth login` による認証が完了していること（リポジトリがプライベートのため）。未インストール / 未認証の場合は GitHub Release ページ（`https://github.com/daiki-beppu/youtube-automation/releases`）からの手動ダウンロードを案内する
- Chrome がインストール済みで、user が `chrome://extensions` のデベロッパーモードを操作できること（Load unpacked / リロードは user の手動操作）
- automation リポジトリの GitHub Release に `ext-v*` タグのリリースが存在すること。1 件も無ければ拡張が未リリースであると報告して停止する

## When to Use

- Chrome 拡張を初めてインストールするとき
- 新しいバージョンの拡張に更新したいとき
- 「拡張入れて」「extension 更新して」「suno-helper インストール」などと user が言ったとき

## Instructions

### Step 0: upstream リポジトリの解決

以降の `gh` コマンドが参照する automation リポジトリ（`<owner>/<repo>`）は、導入済みパッケージの `automation_update_refs.UPSTREAM_REPO`（official upstream の単一ソース。既定: `daiki-beppu/youtube-automation`）から導出する。fork 運用でも自動で fork 側の upstream を参照できる:

```bash
UPSTREAM_REPO="$(uv run python -c 'from youtube_automation.cli.automation_update_refs import UPSTREAM_REPO; print(UPSTREAM_REPO)')"
```

Bash 呼び出し間でシェル変数が保持されない環境では、この導出行を後続の各コマンドと同一の Bash 呼び出し内で先頭に付けて実行する。

### Step 1: 最新リリースの確認

```bash
gh release view --repo "$UPSTREAM_REPO" $(gh release list --repo "$UPSTREAM_REPO" --limit 10 --json tagName --jq '[.[] | select(.tagName | startswith("ext-v"))][0].tagName') --json tagName,assets --jq '{tag:.tagName, assets:[.assets[] | {name, url:.url}]}'
```

user に最新バージョンと含まれる拡張を提示する。

### Step 2: 既存バージョンの確認

Chrome で拡張がすでにインストール済みか user に確認する:

- **初回インストール**: Step 3 へ
- **更新**: Step 4 へ

### Step 3: 初回インストール

1. zip をダウンロードする（user が必要な拡張を選択）:

```bash
# suno-helper の場合
gh release download --repo "$UPSTREAM_REPO" <tag> --pattern 'suno-helper-*.zip' --dir ~/Downloads

# distrokid-helper の場合
gh release download --repo "$UPSTREAM_REPO" <tag> --pattern 'distrokid-helper-*.zip' --dir ~/Downloads
```

2. zip を展開する:

```bash
# suno-helper の場合
mkdir -p ~/chrome-extensions/suno-helper && cd ~/chrome-extensions/suno-helper && unzip -o ~/Downloads/suno-helper-*.zip

# distrokid-helper の場合
mkdir -p ~/chrome-extensions/distrokid-helper && cd ~/chrome-extensions/distrokid-helper && unzip -o ~/Downloads/distrokid-helper-*.zip
```

3. user に以下の手順を案内する:
   - Chrome で `chrome://extensions` を開く
   - 右上の **デベロッパーモード** を ON にする
   - **パッケージ化されていない拡張機能を読み込む**（Load unpacked）をクリック
   - 展開したフォルダ（`~/chrome-extensions/<name>/`）を選択する

4. 拡張アイコンが Chrome ツールバーに表示されたことを確認する。

### Step 4: 更新

1. 新しい zip をダウンロードする:

```bash
gh release download --repo "$UPSTREAM_REPO" <tag> --pattern '<name>-*.zip' --dir ~/Downloads
```

2. 既存フォルダを置き換える:

```bash
# suno-helper の場合
cd ~/chrome-extensions/suno-helper && rm -rf * && unzip -o ~/Downloads/suno-helper-*.zip

# distrokid-helper の場合
cd ~/chrome-extensions/distrokid-helper && rm -rf * && unzip -o ~/Downloads/distrokid-helper-*.zip
```

3. user に以下を案内する:
   - Chrome で `chrome://extensions` を開く
   - 対象拡張の **リロード**（更新アイコン 🔄）をクリックする

### Step 5: 動作確認

インストールした拡張に応じた確認を案内する:

- **suno-helper**: Suno (suno.com/create) を開き、拡張アイコンをクリックして popup が表示されることを確認
- **distrokid-helper**: DistroKid のアップロードページを開き、拡張アイコンをクリックして popup が表示されることを確認

## Notes

- 展開先は `~/chrome-extensions/<name>/` を推奨するが、user が別の場所を希望すればそれに従う
- `gh` CLI 未インストール / 未認証時の手動ダウンロード fallback は冒頭「## 前提」を単一ソースとする（本セクションに重複記載しない）
