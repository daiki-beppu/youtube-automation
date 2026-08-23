# Chrome 拡張インストールガイド

YouTube 自動化ツールキットの Chrome 拡張を導入・更新する手順。通常は `/extension` skill を正規入口として使う。

## 対象拡張

| 拡張 | 用途 |
|---|---|
| **suno-helper** | Suno UI 上で曲の連続生成と playlist 追加を自動化 |
| **distrokid-helper** | DistroKid 登録フォームへの自動入力 |
| **community-helper** | YouTube Studio のコミュニティ投稿を補助 |

## 推奨: `/extension` で導入・更新する

リポジトリを Codex または Claude Code で開き、フラグなしで実行する。

```text
/extension
```

agent はローカルの `~/chrome-extensions/<name>/manifest.json` と最新の `ext-v*` Release を比較し、3 拡張をそれぞれ次のいずれかに自動判定する。

- **install**: 未導入の拡張を新規インストールする
- **update**: Release より古い拡張を安全に更新する
- **skip**: 最新版の拡張は変更しない

### 対象や操作を指定する

対象だけを絞る modifier は複数指定できる。省略時は 3 拡張すべてが対象になる。

```text
/extension --suno
/extension --distrokid
/extension --community
/extension --suno --community
```

自動判定を使わず操作を固定する場合は、排他的な mode を 1 つ指定する。`--install` は指定対象を新規導入し、`--update` は比較結果にかかわらず指定対象を更新する。

```text
/extension --install --suno
/extension --update --distrokid --community
```

## agent と利用者の責務

### agent が行うこと

- 最新 `ext-v*` Release と対象 asset の特定・download
- 一時ディレクトリへの安全な展開と、更新時の既存ディレクトリの backup
- `manifest.json` の name / version が対象拡張と Release に一致することの検証
- 検証済みファイルの `~/chrome-extensions/<name>/` への配置
- install / update / skip の結果と、Chrome で開くディレクトリの提示

### 利用者が Chrome で行うこと

agent は Chrome の GUI 操作を代行しない。案内された後に、利用者が次を行う。

1. `chrome://extensions` を開き、**Developer mode（デベロッパーモード）**を ON にする。
2. 初回導入では **Load unpacked（パッケージ化されていない拡張機能を読み込む）**を選び、案内された `~/chrome-extensions/<name>/` を指定する。
3. 更新では対象拡張の **reload（リロード）**をクリックする。
4. 対象サービスを開き、popup または overlay が表示・動作することを確認する。

## 手動取得（フォールバック）

`/extension` skill を実行できない場合や、`gh` が未導入・未認証の場合だけ使用する。

1. [GitHub Releases](https://github.com/daiki-beppu/youtube-automation/releases) を開き、最新の `ext-v*` Release を選ぶ。
2. 必要な `<name>-*.zip` を download し、`~/chrome-extensions/<name>/` へ展開する。
3. 展開先の `manifest.json` で name / version が選んだ拡張と Release に一致することを確認する。
4. 前節の Chrome 操作を行う。更新時は既存フォルダを backup してから置き換え、Chrome で reload する。

`gh` を利用できる場合の手動取得例:

```bash
TAG=$(gh release list --repo daiki-beppu/youtube-automation --limit 10 \
  --json tagName --jq '[.[] | select(.tagName | startswith("ext-v"))][0].tagName')

# <name> は suno-helper / distrokid-helper / community-helper のいずれか
gh release download --repo daiki-beppu/youtube-automation "$TAG" \
  --pattern '<name>-*.zip' --dir ~/Downloads
```

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `gh` を利用できない | `gh auth status` を確認する。復旧できなければ手動取得（フォールバック）を使う |
| 拡張を読み込めない | Developer mode が ON か、指定フォルダ直下に検証済みの `manifest.json` があるか確認する |
| popup / overlay が表示されない | 拡張をピン留めし、対象ページと拡張を reload して再確認する |
| 古いバージョンのまま | `/extension --update` を実行し、完了後に Chrome で対象拡張を reload する |
