# distrokid.json の PII（本名）取り扱いと .gitignore 運用

`config/channel/distrokid.json` の `distrokid.profile.songwriter` は **作曲者の本名（PII）** を保持する。
DistroKid（distrokid.com/new）の songwriter 欄は法的な実名登録を求めるため、芸名・アーティスト名では代用できない。
本ドキュメントは、本名を config に記載する際のリポジトリ公開リスクと、その回避運用の単一ソースである。

## 記入例

```json
{
  "distrokid": {
    "enabled": true,
    "profile": {
      "artist": "Example Artist",
      "language": "en",
      "main_genre": "Electronic",
      "songwriter": { "first": "Jane", "last": "Doe" }
    }
  }
}
```

- `first` / `last` は必須、`middle` は任意（distrokid.com/new の氏名 3 分割欄に対応）
- schema 上 `songwriter` 自体は任意。省略時は DistroKid Web フォームで曲ごとに手入力する（CLI バリデーションは行われない）

## リスク: config はコミット対象である

チャンネルリポジトリの `config/channel/*.json` は通常 git 管理下にあり、`distrokid.json` に `songwriter` を書くと **本名がコミット履歴に残る**。リポジトリが public の場合、または将来 public 化・共有する可能性がある場合は、本名がそのまま公開される。

## 運用の判断基準

| リポジトリの状態 | 推奨運用 |
|---|---|
| private で今後も公開予定なし | そのままコミットしてよい（リポジトリのアクセス制御が境界） |
| public、または公開・共有の可能性あり | `distrokid.json` を `.gitignore` に追加し、ローカル専用ファイルとして管理する |

## .gitignore 運用手順（public / 公開可能性ありの場合）

1. チャンネルリポジトリの `.gitignore` に追記する:

   ```gitignore
   config/channel/distrokid.json
   ```

2. すでにコミット済みの場合は index から外す（ローカルファイルは残る）:

   ```bash
   git rm --cached config/channel/distrokid.json
   git commit -m "chore(config): distrokid.json を git 管理から除外（PII 保護）"
   ```

3. **過去のコミット履歴に本名が残っている場合**、`git rm --cached` では履歴から消えない。public リポジトリで履歴にも本名が含まれるときは、履歴書き換え（`git filter-repo` 等）またはリポジトリ再作成を検討する

## .gitignore 化した場合の注意

- `distrokid.json` はローカルに実体があれば `load_config` / `yt-collection-serve` から通常どおり読める（git 管理の有無は動作に影響しない）
- 新しいクローン・別マシンにはファイルが存在しないため、手動で再作成が必要になる。1Password 等のシークレット管理にファイル内容を控えておくと復元しやすい
- `yt-config-migrate` / `yt-doctor` などの診断はファイルの存在を前提とするため、クローン直後は再作成してから実行する
