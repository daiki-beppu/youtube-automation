# 公開リリースノート authoring 契約

この reference は、release 完了後に `docs/release-notes/<tag>.md` を作るときの入力、公開内容、検証、pull request の契約を定める。この段では `/automation-release` の publish flow は接続しない。既存の version bump、tag push、GitHub Release 作成、extension asset 公開の動作は変更しない。

## 入力の単一ソース

最初に対象 tag を確定し、`git fetch origin --tags --prune` で tag history を取得する。対象 tag が `git rev-parse --verify "refs/tags/${TAG}"` で実在しなければ authoring を停止する。

- Python 本体（`vX.Y.Z`）は、対象 version の `CHANGELOG.md` section を入力とする。`[Unreleased]` や別 version の section を混ぜない。
- Chrome 拡張（`ext-vX.Y.Z`）は、同一 tag の GitHub Release body を入力とする。`gh release view "${TAG}" --json body --jq .body` で取得し、別 tag の release やローカル CHANGELOG で補完しない。

入力から、設定変更、移行、導入・更新手順、利用可能になった機能、挙動変更、修正された不具合など、運営者への影響がある項目を全件保持する。近い項目の統合や利用者向け表現への翻訳はよいが、短文化を理由に項目を落とさない。

## 出力 identity と frontmatter

出力先は `docs/release-notes/<tag>.md` とし、filename / frontmatter `version` / GitHub Release link を同一 tag に揃える。GitHub Release link は `https://github.com/daiki-beppu/youtube-automation/releases/tag/<tag>` とする。

frontmatter は `title` / `version` / `released_at` / `kind` / `summary` / `sidebar` の exact keys だけを持つ。`sidebar` の子は `order` だけとする。

- `title`: 詳細ページと sidebar に表示するタイトル
- `version`: filename と同じ tag
- `released_at`: `YYYY-MM-DD` の公開日
- `kind`: Python 本体は `main`、Chrome 拡張は `extension`
- `summary`: 改行を含まない一覧用の要約
- `sidebar.order`: 新しい公開日ほど先になる負数。同日では本体を拡張より先にする

## 本文契約

本文に level 1 heading は置かない。次の見出しをこの順序で置く。

## 30 秒サマリー

運営者が更新の規模、必要な作業、主要な影響を短時間で判断できるようにまとめる。

## アップデート方法

Python 本体は `/automation-update`、Chrome 拡張は `/extension` を単独の `text` code block で示す。必要な移行作業があれば省略しない。

## 新機能

入力に該当項目がない場合も見出しを残し、追加がないことを利用者向けに記す。

## 改善

運用、安全性、性能、使い勝手への影響が分かる表現にする。

## 直った不具合

症状と修正後の状態を運営者の視点で説明する。

## 詳しい変更内容

同一 tag の GitHub Release link を置く。必要なら「移行作業」や「今後のアップデート予定」を追加できるが、必須見出しの順序は変えない。

内部実装・issue・PR 番号、内部関数・内部 package 名、特定 community 向けの記号や link は本文から除外する。実装の羅列を消すときも、その変更が運営者へ与える影響は消さない。

## branch・preview・merge gate

post-release の authoring は最新 `origin/main` から専用 branch を作り、変更を commit して pull request にする。main へ直接 push しない。

pull request では site の check / build / test を実行し、Cloudflare Pages の preview で一覧、詳細ページ、link、見出し、mobile 表示を確認する。active main ruleset が要求する pull request、preview、required checks の `lint` / `test` をすべて通し、未通過のまま merge しない。

この手順は公開ノートの authoring と review だけを扱う。GitHub Release や Cloudflare production への再 publish は行わない。
