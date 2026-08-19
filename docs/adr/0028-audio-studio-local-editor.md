# Audio Studio を独立したローカル編集 UI として配布する

## Status

accepted (2026-08-20, #4380)

## Context

collection の個別音源は Finder と外部 player を往復しないと連続確認できず、後続の EQ・曲順・master 調整を「聴きながら操作する」単一画面がない。既存 `yt-collection-serve` は Chrome 拡張向け API、`yt-dashboard` は read-only Analytics 表示であり、音源編集を同居させると責務と lifecycle が結合する。

ADR-0021 は TypeScript を `dashboard/`、`site/`、`extensions/` の閉じた範囲だけに許可しているため、新しい表示層には同等に限定された例外と配布境界が必要である。

## Decision

1. `yt-audio-studio` を `127.0.0.1` だけに bind する独立 Python process とし、collection filesystem、duration probe、audio allowlist、HTTP Range、PID / stop lifecycle を所有させる。
2. `audio-studio/` を React / Vite / TypeScript / Tailwind CSS v4 / shadcn/ui（Base UI）の独立 workspace として許可する。`dashboard/` と `extensions/shared-ui` から component や source を import しない。
3. frontend は同一 origin の JSON / audio API だけを利用し、filesystem path や編集の正本を持たない。
4. build output は `src/youtube_automation/audio_studio_dist/` に固定して commit し、wheel / sdist に同梱する。runtime は Node.js に依存せず `importlib.resources` から配信する。
5. 認証、LAN / 外部 bind、dashboard 統合は提供しない。collection server と server-kind 別 lifecycle path を共有し、同時起動時も干渉させない。

## Consequences

- TypeScript 許容範囲が `audio-studio/` とその build output に限って増える。
- Python と frontend は同一 origin API contract で独立してテストし、build asset の差分を CI で拒否する。
- EQ、曲順、master 調整は同じ process / workspace に積み上げられるが、各段で filesystem write の検証・rollback 契約を追加する必要がある。

## Considered Options

- `yt-collection-serve` へ相乗り: Chrome 拡張向け配信と編集責務が結合するため不採用。
- `yt-dashboard` へ統合: read-only Analytics 境界を壊すため不採用。
- frontend を Python template だけで構築: 後続の操作 UI と状態管理の拡張性が不足するため不採用。

## Related

- ADR-0013（multi-channel dashboard）
- ADR-0021（TypeScript 許容境界）
- #4379（localserver 共有規約）
- #4380（初回 player 実装）
