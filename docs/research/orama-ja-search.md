# Orama 日本語全文検索の導入設定調査

発端: #4734（マップ #4729）

- 調査日: 2026-08-29
- 対象: blume 1.2.1（`site/node_modules/blume/` のドキュメントと実装ソース）と現行 `site/blume.config.ts`
- 結論: `i18n` ブロックを 1 つ追加するだけでよい（`defaultLocale: "ja"` + 単一 locale `ja`）。URL・ルーティング・サイドバー・カスタムソースへの副作用はゼロで、`<html lang>` と UI 文言はむしろ改善方向に変わる
- 未実施: `blume dev` / `blume build` での実機検証（実装 issue 側のチェックリストとして本文末尾に列挙）

## 要約

blume の全文検索は **Orama がデフォルト provider** であり、`search` キーを書いていない現行 config でもすでに有効になっている。問題は Orama の標準トークナイザがスペース区切り言語前提で、日本語本文がトークン 0 個に潰れてクエリが常に 0 件になること。blume はこれを `i18n.defaultLocale` の主要言語サブタグが `ja` / `zh` / `ko` / `th` のとき、`Intl.Segmenter` ベースの単語分割トークナイザに自動で差し替えることで解決する（`src/search/orama-index.ts` の `SEGMENTED_LANGUAGES` と `segmentingTokenizer`）。つまり日本語検索の有効化に必要なのは **`i18n` ブロックの追加だけ**で、`search` キーの変更は不要。

`i18n.defaultLocale: "ja"` を単一 locale で設定した場合の副作用を実装ソースで追った結果、**URL・ルーティング・サイドバー・カスタムソース（operator-doc-source / skill-page-source）はすべて不変**であることを確認した。変わるのは `<html lang>`（`en` → `ja`）と UI 文言（英語 → 日本語 UI パック）で、日本語サイトとしてはどちらも改善である。

## 推奨する導入設定

`site/blume.config.ts` の `defineConfig` に以下を追加する（これが最小設定。`search` キーは不要 — Orama がデフォルト）:

```ts
i18n: {
  defaultLocale: "ja",
  locales: [{ code: "ja", label: "日本語" }],
},
```

明示したければ `search: { provider: "orama" }` を併記してもよいが挙動は変わらない。schema 上 `locales` は `min(1)` で、`defaultLocale` は `locales` 内の code と一致必須（`src/core/schema.ts` の `i18nConfigSchema.superRefine`）。

## トークナイザ差し替えの仕組み（一次情報）

- `src/search/orama-index.ts`: `SEGMENTED_LANGUAGES = {"ja","ko","th","zh"}`。`i18n.defaultLocale` の主要サブタグが該当すると `Intl.Segmenter(language, { granularity: "word" })` の単語分割トークナイザで Orama DB を作る。入力は lowercase 化されるため Latin 語（"DistroKid" 等）も大文字小文字を無視してヒットする。`Intl.Segmenter` が無いランタイムでは黙って標準トークナイザにフォールバック
- `src/astro/templates.ts::searchClientTemplate`: 生成される検索クライアントに `config.i18n?.defaultLocale` が焼き込まれる（Orama のみ。FlexSearch には分割フックが無い）
- 同じトークナイザが検索ダイアログ・MCP `search_docs`・Ask AI grounding で共有される（`src/ai/mcp/data.ts` / `src/ai/ask-data.ts` も `config.i18n?.defaultLocale` を転送）
- 混在言語でも安全: トークナイザは DB 全体に効くが、Latin 単語は分割後も原形を保つため英語ページの検索は劣化しない（docs/configuration/search.mdx 明記）

## `i18n.defaultLocale: "ja"` の副作用（単一 locale の場合）

| 観点 | 影響 | 根拠 |
|---|---|---|
| URL・ルーティング | **不変**。`hideDefaultLocalePrefix` の既定値は `true`（`schema.ts:768`）で、デフォルト locale の prefix は空文字。`detectLocale` は非デフォルト locale の先頭ディレクトリしか照合しないため、単一 locale では全ページが `ja` に割り当てられ route はそのまま | `core/i18n.ts::localePrefix` / `detectLocale`、`core/sources/normalize.ts::normalizeEntry` |
| カスタムソース | **不変**。custom source のエントリも filesystem と同じ `normalizeEntry` → `localePlacement(entry.ref, …)` を通るが、ref（`docs/tool-setup.md`、`<skill>.md`、`ONBOARDING.md` 等）に locale ディレクトリ・`.$` マーカーが無く、parser 既定 `dir` では filename suffix も見ないため、slug 由来の route（`/tool-setup`、`/skills/<name>` 等）は変わらない | `core/sources/normalize.ts:649-709`、`site/operator-doc-source.ts`、`site/skill-page-source.ts` |
| サイドバー | **不変**。明示 sidebar 設定は locale 非依存の参照で各 locale のページに解決される。単一 locale なら従来と同一 | `core/navigation.ts`（explicit-sidebar の locale-agnostic 解決コメント） |
| 言語スイッチャー | **表示されない**。`options.length > 1` のときだけ描画 | `components/layout/LanguageSwitcher.astro:22` |
| 検索ダイアログの locale フィルタ | **表示されない**。「All languages」トグルと locale 絞り込みは `localeSwitch.length > 1` のときだけ有効 | `components/layout/RootLayout.astro:253-254`、`components/layout/Search.astro:136` |
| `<html lang>` | `en` → `ja` に**改善**。i18n 未設定だと `htmlLang` は固定で `"en"`（日本語サイトなのに現状 `lang="en"`） | `astro/templates.ts:1533` |
| UI 文言 | 検索ボタン・ページネーション等の chrome が日本語 UI パックに切り替わる（見た目の変化はここだけ）。個別上書きは `i18n.ui.ja` で可能 | `core/ui-packs/ja.ts`、docs/content/i18n.mdx |
| hreflang | 変化なし。alternates は `deployment.site` 設定時のみ絶対 URL で出力され、現行 config は未設定。将来 site を設定しても単一 locale では `hreflang="ja"` + 同一 URL の `x-default` が出るだけで無害 | `astro/templates.ts:1546-1551` |
| sitemap | 変化なし。`buildSitemap` は `deployment.site` 必須（現状 null で未出力）。出力される場合も route が不変なので同一 | `deploy/sitemap.ts:37-41` |
| diagnostics | `BLUME_I18N_UNCONFIGURED_LOCALE` 警告は「locale コードに見える最上位フォルダ」だけが対象。release-notes の `vX.Y.Z.md` / custom source の ref に該当なし | `core/i18n.ts::i18nDiagnostics` |

## i18n を設定しない代替手段の評価

- **Pagefind provider**（`search: { provider: "pagefind" }`）: `pagefind_extended` が CJK をネイティブ分割するが、Pagefind はビルド済み HTML の `<html lang>` から言語を判定する。blume は i18n 未設定だと `lang="en"` を出すため、**i18n なしでは日本語ページが英語として索引される恐れがあり、結局 i18n 設定が要る**。さらに `blume build` 時のみ動作し `blume dev` では検索が使えない（docs/configuration/search.mdx:105）。大規模化して index の初期ロードが重くなったときの移行先としては有力
- **FlexSearch**: 分割フックが無く日本語不可（docs 明記）
- **ホスト型（Algolia / Orama Cloud / Typesense / Mixedbread）**: API キー管理・ビルド時 sync・外部サービス依存が増える。このサイト規模では過剰

結論: i18n なしで日本語検索品質を確保する現実的な手段は無い。`i18n` ブロック追加が唯一かつ最小の経路。

## 実装時の検証チェックリスト

1. `blume dev` で ⌘K を開き、日本語クエリ（例: 「セットアップ」「サムネイル」「配信」）がヒットする
2. 英語クエリ（例: `DistroKid`、`OAuth`）も引き続きヒットする
3. URL 不変: `/tool-setup`、`/skills`、`/skills/<name>`、`/v5.6.0` 等が従来どおりの path で表示される（`/ja/...` が生えていない）
4. ヘッダーに言語スイッチャーが表示されない
5. 検索ダイアログ下部に「All languages」トグルが表示されない
6. `<html lang="ja">` になっている
7. UI 文言（検索ボタン、前後ページ等）の日本語化を意図した変化として確認する
8. `/blume-search.json` に release notes・operator docs・skill pages が載っている（`/onboarding` は `search.exclude` 指定のため除外のままでよい）
9. `blume build` が成功し、`BLUME_I18N_UNCONFIGURED_LOCALE` 等の新規 diagnostics が出ない
