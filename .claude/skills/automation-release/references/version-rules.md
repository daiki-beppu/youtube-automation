# Semver bump 判定ルール

`/automation-release` の prepare Phase 1-1 で `CHANGELOG.md::[Unreleased]` の内容から次バージョンを提案するための判定ルール。

最終決定はユーザーが行う（`AskUserQuestion` で上書き可）。本ドキュメントは提案ロジックを定める。

---

## 判定フローチャート

```
[Unreleased] 配下に以下のいずれかがあるか？
  ├─ ### Removed セクション あり
  │    → major bump
  ├─ 本文中に "BREAKING" / "破壊的変更" / "後方互換性無し" / "API 削除" 記述
  │    → major bump
  ├─ ### Added セクション あり
  │    → minor bump
  ├─ ### Changed セクション あり で挙動変更を含む（追加・拡張系）
  │    → minor bump（保守的に判定するなら patch も可）
  ├─ ### Fixed セクションのみ
  │    → patch bump
  ├─ ### Security セクション あり
  │    → patch bump（CVE 等の脆弱性修正、メジャー昇格は別途判断）
  └─ ### Deprecated セクション あり（削除はしていない）
       → minor bump（廃止予告は新機能扱い）
```

---

## 各種別の具体例

### major（X.0.0）

- 公開関数の削除・シグネチャ変更
- `config/channel/*.json` の必須キー追加（既存チャンネルが動かなくなる）
- CLI コマンドの削除・命名変更
- 環境変数の必須化

例:
```markdown
### Removed
- `yt-legacy-uploader` CLI を削除（`yt-upload-collection` に統合）

### Changed
- BREAKING: `config/channel/youtube.json::api.category_id` を必須化
```

### minor（5.X.0）

- 新規 CLI / スキル / モジュール追加
- 既存機能への後方互換オプション追加
- 廃止予告（Deprecated）

例:
```markdown
### Added
- `/automation-release` スキル新設
- `yt-doctor` CLI の `--json` 出力オプション

### Deprecated
- `yt-old-cmd` は v6.0.0 で削除予定。代替: `yt-new-cmd`
```

### patch（5.5.X）

- バグ修正（挙動を「正しい状態」に戻すもの）
- ドキュメント・型定義・コメントの修正
- 内部リファクタ（外部 API に影響しない）
- セキュリティ修正（CVE 対応で API 変更を伴わないもの）

例:
```markdown
### Fixed
- `yt-upload-collection` がローカライゼーション 0 件で落ちる問題

### Security
- 依存パッケージの脆弱性修正（CVE-2026-XXXX）
```

---

## 例外・グレーゾーン

### 「### Changed」のみの場合

`### Changed` だけだと判定が分かれる:

- **挙動が拡張された**（オプション追加・パラメータ拡張）→ minor
- **挙動が変わったが互換性は保たれている**（内部最適化、エラーメッセージ改善）→ patch
- **挙動が変わって互換性が破壊されている**（戻り値形式変更、デフォルト値変更）→ major

判定難しい場合は **保守的に minor**（patch だと利用者が想定外の挙動変化に気付かないリスク）。

### マルチセクション混在

`### Added` と `### Removed` が両方ある → 上位の major を採用。

`### Added` と `### Fixed` が両方ある → 上位の minor を採用。

---

## 自動検出のための grep スニペット

prepare Phase 1-1 で Unreleased 内容を判定するときの実装ヒント:

```bash
# Unreleased セクション本文を抽出
unreleased=$(awk '/^## \[Unreleased\]/{flag=1; next} /^## \[/{flag=0} flag' CHANGELOG.md)

# major 判定
if echo "$unreleased" | grep -qE "^### Removed|BREAKING|破壊的変更|後方互換性無し"; then
  bump="major"
# minor 判定
elif echo "$unreleased" | grep -qE "^### Added|^### Deprecated"; then
  bump="minor"
# patch 判定
elif echo "$unreleased" | grep -qE "^### Fixed|^### Security"; then
  bump="patch"
# Changed のみ → 保守的に minor
elif echo "$unreleased" | grep -qE "^### Changed"; then
  bump="minor"
else
  bump="unknown"
fi
```

`bump="unknown"` は明示的にユーザーへ判断を委ねる（`AskUserQuestion` で major / minor / patch を選ばせる）。
