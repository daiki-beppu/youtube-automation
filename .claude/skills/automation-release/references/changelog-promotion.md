# CHANGELOG.md Unreleased 昇格手順

`/automation-release` スキル prepare Phase 1-4 で参照する `CHANGELOG.md` 同期手順。Keep a Changelog 1.1.0 準拠。

Migration セクションのフォーマット契約は `docs/changelog-contract.md` を参照。本ドキュメントは昇格手順（[Unreleased] → [VER] への置換）に絞る。

---

## 基本構造

```markdown
## [Unreleased]

（次のリリースに含まれる変更を書き溜める場所）

## [5.5.0] - 2026-05-17

### Added / Changed / Fixed / Removed / Deprecated

（リリース済みバージョンの記録）

...

[5.5.0]: https://github.com/.../releases/tag/v5.5.0
[5.4.0]: https://github.com/.../releases/tag/v5.4.0
```

---

## 昇格手順（3 段階）

### Step 1: `[Unreleased]` ヘッダの直後に新セクションを挿入

```diff
 ## [Unreleased]
+
+## [<VER>] - <DATE>
 
 ### Changed
 
 #### ...（既存の Unreleased 内容がそのまま v<VER> セクションになる）
```

具体的には、`[Unreleased]` の直後に空行を挟んでから `## [<VER>] - <DATE>` を 1 行挿入するだけ。既存の Unreleased 配下のサブセクション（Added / Changed / Fixed など）はそのまま v<VER> 配下に属する形になる。

### Step 2: Migration セクションを v<VER> 用に更新

`### Migration` セクションは v<VER> のリリースに合わせて書き換える。必須要素は `docs/changelog-contract.md` 参照（所要時間の目安 / local fix 衝突注意 / サマリ）:

```diff
 ### Migration
 
+所要時間の目安: X〜Y 分
+
+local fix 衝突注意:
+- <該当 skill 名>（または「無し」）
+
 サマリ:
 
-- （旧サマリ）
+- （v<VER> リリースに含まれる主要な変更のサマリ、3〜5 行）
```

旧版で `[docs/upgrades/v<PREV>.md](docs/upgrades/v<PREV>.md)` への参照が残っていたら、本リリースから削除する（過去資料として `docs/upgrades/` 自体は残るが、Migration セクション本文では言及しない）。

### Step 3: ファイル末尾のリンク参照定義に新エントリを追加

```diff
+[<VER>]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v<VER>
+[<PREV>]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v<PREV>
 [5.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.0.0
 [2.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v2.0.0
```

過去リリースで参照定義が漏れていたバージョン（[5.4.0], [5.3.0] など）があれば、合わせて追加する。

---

## Unreleased 内容が累積している場合の対応

過去リリース時に Unreleased 昇格を忘れていたケースがある（例: v5.4.0 リリース時に昇格されず v5.5.0 と内容が混在）。

### 判定方法

`[Unreleased]` 配下の内容（issue 番号や日付ヒント）から、複数バージョンの内容が混在しているか確認:

```bash
# v<prev> のリリース日後に書かれた entry が Unreleased 配下に残っていないか
grep -E "#[0-9]+" CHANGELOG.md | head -20
```

各 PR / issue の作成日と前回リリース日を比較し、前回リリース後に書かれた entry のみを v<VER> に残すのが厳密対応だが、**手作業で分離するのは困難**。

### 推奨アプローチ: 累積で昇格

「v<VER> リリースに累積で含まれる」として、Unreleased 全体を v<VER> セクションに昇格させる。

```diff
 ## [Unreleased]
+
+## [<VER>] - <DATE>
+
+※ 本セクションは v<PREV> リリース時に Unreleased 昇格が見送られたため、
+v<PREV> 〜 v<VER> の累積変更を含む。
```

注釈を付ければ正確性は保たれる。

---

## Edit 操作の具体例

`/automation-release` の prepare Phase 1-4 から `Edit` ツールで実施する場合の具体的な変更:

### Edit 1: Unreleased の直後に v<VER> セクション挿入

```python
Edit(
  file_path="/Users/mba/02-yt/automation/CHANGELOG.md",
  old_string="""## [Unreleased]

### Changed

#### <最初のサブセクション見出し>""",
  new_string="""## [Unreleased]

## [<VER>] - <DATE>

### Changed

#### <最初のサブセクション見出し>""",
)
```

### Edit 2: Migration セクションの書き換え

```python
Edit(
  file_path="/Users/mba/02-yt/automation/CHANGELOG.md",
  old_string="<旧 Migration セクション全文>",
  new_string="<新 Migration セクション全文>",
)
```

### Edit 3: リンク参照定義の追加

```python
Edit(
  file_path="/Users/mba/02-yt/automation/CHANGELOG.md",
  old_string="[5.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.0.0\n[2.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v2.0.0",
  new_string="[<VER>]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v<VER>\n[<PREV>]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v<PREV>\n[5.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.0.0\n[2.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v2.0.0",
)
```

---

## Keep a Changelog 1.1.0 の規約まとめ

- `## [<version>] - <YYYY-MM-DD>` 形式
- `<version>` は `v` プレフィックス無し（リンク参照は `v` 付き）
- 日付は ISO 8601
- サブセクション: `Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` / `Security`
- ファイル末尾にリンク参照定義（`[<version>]: <URL>`）を集約
- `[Unreleased]` セクションを常に先頭に置き、次のリリース時に昇格させる慣例
