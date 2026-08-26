# Chrome 拡張インストールガイド

YouTube 自動化ツールキットの Chrome 拡張は、下流チャンネルリポジトリで **`/extension` をフラグなしで実行する方法を推奨**します。

```text
/extension
```

agent はローカルの `~/chrome-extensions/<name>/manifest.json` と最新の `ext-v*` GitHub Release を比較し、次の処理を自動で選びます。初回か更新かを利用者が判断する必要はありません。

- manifest がない拡張: **install**
- release より古い拡張: **update**
- release と同じ version の拡張: **skip**

## 対象拡張

フラグなしでは次の 3 拡張をすべて確認します。

| 拡張 | 用途 |
|---|---|
| **suno-helper** | Suno UI 上で曲の連続生成と playlist 追加を自動化 |
| **distrokid-helper** | DistroKid 登録フォームへの自動入力 |
| **community-helper** | YouTube Studio のコミュニティ投稿入力を補助 |

## 対象や操作を指定する

対象だけを絞る modifier は複数指定できます。省略時は 3 拡張すべてが対象です。

```text
/extension --suno
/extension --distrokid
/extension --community
/extension --suno --community
```

通常はフラグなしの自動判定を使います。操作を明示的に固定したい場合だけ mode を指定します。

```text
# 指定対象を新規インストールする
/extension --install --suno

# 指定対象を現在の version にかかわらず更新する
/extension --update --distrokid --community
```

`--install` と `--update` は排他的です。対象 modifier を省略した場合、どちらの mode も 3 拡張すべてを対象にします。

## agent と利用者の責務

### agent が行うこと

- GitHub CLI (`gh`) の認証状態と最新の `ext-v*` release を確認する
- 対象 asset をダウンロードし、安全な一時ディレクトリへ展開する
- 展開した `manifest.json` の name と version を対象 asset / release と照合する
- install では `~/chrome-extensions/<name>/` へ配置する
- update では検証後に既存ディレクトリを timestamp 付き backup へ移し、検証済みディレクトリで置き換える
- 完了後の manifest version を再確認し、install / update / skip の結果を報告する

### 利用者が Chrome で行うこと

agent は Chrome の GUI 操作を代行しません。案内された対象について、次の操作だけを手動で行います。

**初回インストールの場合**

1. Chrome で `chrome://extensions` を開く
2. 右上の **デベロッパーモード** を ON にする
3. **パッケージ化されていない拡張機能を読み込む**（Load unpacked）をクリックする
4. agent が提示した `~/chrome-extensions/<name>/` を選択する

**更新の場合**

1. `chrome://extensions` を開く
2. 対象拡張の **リロード**（更新アイコン）をクリックする

最後に対象ページを再読み込みし、拡張の popup または overlay が表示されることを確認します。

| 拡張 | 確認先 |
|---|---|
| suno-helper | [suno.com/create](https://suno.com/create) で拡張アイコンをクリックし、popup を確認 |
| distrokid-helper | DistroKid のアップロードページで拡張アイコンをクリックし、popup を確認 |
| community-helper | YouTube Studio の投稿作成画面で community-helper の overlay を確認 |

## `/extension` を利用できない場合（手動フォールバック）

`gh` が未導入・未認証などで skill を利用できない場合に限り、[GitHub Release ページ](https://github.com/daiki-beppu/youtube-automation/releases)から手動で取得します。

1. `ext-v*` タグのうち最新の Release を開く
2. 必要な `<name>-*.zip` をダウンロードする
3. zip を空の `~/chrome-extensions/<name>/` へ展開する
4. 展開先直下の `manifest.json` を開き、name が対象拡張、version が Release version と一致することを確認する
5. 初回は Load unpacked、更新時は既存フォルダを backup してから置き換え、Chrome でリロードする

手動更新でも、検証前に既存ファイルを削除しないでください。新しい展開内容に問題がある場合は backup を正規位置へ戻します。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `gh` が見つからない | [GitHub CLI](https://cli.github.com/) を導入するか、上記の手動フォールバックを使う |
| `gh` が未認証 | `gh auth login` を実行し、`gh auth status` でリポジトリへのアクセスを確認する |
| 拡張を読み込めない | デベロッパーモードが ON で、選択先直下に検証済みの `manifest.json` があるか確認する |
| popup / overlay が表示されない | 拡張をピン留めし、対象ページと拡張をリロードしてから再確認する |
| 古い version のまま | `/extension` を再実行して結果を確認し、update 後なら Chrome 側でリロードする |
