# Chrome 拡張インストールガイド

YouTube 自動化ツールキットの Chrome 拡張を GitHub Release からインストールする手順。

## 対象拡張

| 拡張 | 用途 |
|---|---|
| **suno-helper** | Suno UI 上で曲の連続生成 + playlist 追加を自動化 |
| **distrokid-helper** | DistroKid 登録フォームへの自動入力 |

## 前提条件

- Google Chrome（最新版推奨）
- [GitHub CLI (`gh`)](https://cli.github.com/) がインストール済みで、`gh auth login` で認証済みであること
- リポジトリへのアクセス権があること

> `gh` がない場合は、[GitHub Release ページ](https://github.com/daiki-beppu/youtube-automation/releases)から手動でダウンロードできる。`ext-v*` タグの Release を探す。

## インストール手順

### 1. 最新バージョンを確認する

```bash
gh release list --repo daiki-beppu/youtube-automation --limit 5 \
  --json tagName,publishedAt \
  --jq '[.[] | select(.tagName | startswith("ext-v"))] | .[0]'
```

### 2. zip をダウンロードする

必要な拡張のみダウンロードする。

```bash
# 最新タグを変数に入れる
TAG=$(gh release list --repo daiki-beppu/youtube-automation --limit 10 \
  --json tagName --jq '[.[] | select(.tagName | startswith("ext-v"))][0].tagName')

# suno-helper
gh release download --repo daiki-beppu/youtube-automation "$TAG" \
  --pattern 'suno-helper-*.zip' --dir ~/Downloads

# distrokid-helper
gh release download --repo daiki-beppu/youtube-automation "$TAG" \
  --pattern 'distrokid-helper-*.zip' --dir ~/Downloads
```

### 3. zip を展開する

```bash
# suno-helper
mkdir -p ~/chrome-extensions/suno-helper
cd ~/chrome-extensions/suno-helper
unzip -o ~/Downloads/suno-helper-*.zip

# distrokid-helper
mkdir -p ~/chrome-extensions/distrokid-helper
cd ~/chrome-extensions/distrokid-helper
unzip -o ~/Downloads/distrokid-helper-*.zip
```

### 4. Chrome に読み込む

1. Chrome のアドレスバーに `chrome://extensions` と入力して開く
2. 右上の **デベロッパーモード** を ON にする
3. **パッケージ化されていない拡張機能を読み込む**（Load unpacked）をクリック
4. 展開したフォルダを選択する
   - suno-helper: `~/chrome-extensions/suno-helper/`
   - distrokid-helper: `~/chrome-extensions/distrokid-helper/`
5. ツールバーに拡張アイコンが表示されれば完了

### 5. 動作確認

| 拡張 | 確認方法 |
|---|---|
| suno-helper | [suno.com/create](https://suno.com/create) を開き、拡張アイコンをクリック → popup が表示される |
| distrokid-helper | DistroKid のアップロードページを開き、拡張アイコンをクリック → popup が表示される |

## 更新手順

新しいバージョンがリリースされたら、以下の手順で更新する。

### 1. 新しい zip をダウンロードする

```bash
TAG=$(gh release list --repo daiki-beppu/youtube-automation --limit 10 \
  --json tagName --jq '[.[] | select(.tagName | startswith("ext-v"))][0].tagName')

# suno-helper の場合
gh release download --repo daiki-beppu/youtube-automation "$TAG" \
  --pattern 'suno-helper-*.zip' --dir ~/Downloads
```

### 2. 既存ファイルを置き換える

```bash
cd ~/chrome-extensions/suno-helper
rm -rf *
unzip -o ~/Downloads/suno-helper-*.zip
```

### 3. Chrome で拡張をリロードする

1. `chrome://extensions` を開く
2. 対象拡張のリロードボタン（更新アイコン）をクリック

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `gh release download` で 404 | `gh auth status` で認証状態を確認。リポジトリへのアクセス権があるか確認する |
| 拡張を読み込めない | デベロッパーモードが ON になっているか確認。展開先に `manifest.json` が存在するか確認する |
| popup が表示されない | ツールバーのパズルアイコンから拡張をピン留めする。ページをリロードしてから再度試す |
| 古いバージョンのまま | Chrome の拡張ページでリロードボタンを押したか確認。キャッシュが残る場合は拡張を一度削除して再インストールする |
