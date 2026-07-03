---
name: ext-install
description: "Use when Chrome 拡張（suno-helper / distrokid-helper）のインストール・更新をするとき。「拡張入れて」「extension インストール」で発動"
---

## Overview

automation リポジトリの GitHub Release (`ext-v*` タグ) に添付された Chrome 拡張 zip をダウンロードし、Chrome にインストール（または更新）する operator ガイドスキル。

対象拡張:
- **suno-helper** — Suno UI 上で曲の連続生成 + playlist 追加を自動化
- **distrokid-helper** — DistroKid 登録フォームへの自動入力

## When to Use

- Chrome 拡張を初めてインストールするとき
- 新しいバージョンの拡張に更新したいとき
- 「拡張入れて」「extension 更新して」「suno-helper インストール」などと user が言ったとき

## Instructions

### Step 1: 最新リリースの確認

```bash
gh release view --repo daiki-beppu/youtube-automation $(gh release list --repo daiki-beppu/youtube-automation --limit 10 --json tagName --jq '[.[] | select(.tagName | startswith("ext-v"))][0].tagName') --json tagName,assets --jq '{tag:.tagName, assets:[.assets[] | {name, url:.url}]}'
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
gh release download --repo daiki-beppu/youtube-automation <tag> --pattern 'suno-helper-*.zip' --dir ~/Downloads

# distrokid-helper の場合
gh release download --repo daiki-beppu/youtube-automation <tag> --pattern 'distrokid-helper-*.zip' --dir ~/Downloads
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
gh release download --repo daiki-beppu/youtube-automation <tag> --pattern '<name>-*.zip' --dir ~/Downloads
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
- `gh` CLI が未インストールの場合は、GitHub Release ページ (`https://github.com/daiki-beppu/youtube-automation/releases`) から手動ダウンロードを案内する
- リポジトリがプライベートの場合、`gh auth login` で認証済みであることが前提
