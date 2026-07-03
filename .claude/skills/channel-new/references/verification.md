# 検証・認証ユーティリティ

`/channel-new`（再生成モード / 既存チャンネル取り込みモード）から共通参照する検証コマンド集。
すべて **fully-qualified import**（`from youtube_automation...`）を使用する（CLAUDE.md 規約）。

## JSON 構文検証

```bash
uv run python3 -c "
import json, glob
for p in sorted(glob.glob('config/channel/*.json')):
    json.load(open(p))
    print(f'OK: {p}')
"
```

エラーが出なければ構文 OK。

## load_config() ロードテスト

```bash
uv run yt-config-migrate verify
```

または直接 API で確認:

```bash
uv run python3 -c "
from youtube_automation.utils.config import load_config
c = load_config()
print(f'Channel: {c.meta.channel_name} ({c.meta.channel_short})')
print(f'Genre: {c.content.genre.primary} / {c.content.genre.style}')
print(f'Benchmarks: {len(c.analytics.benchmark.channels)} channels')
print('Config loaded successfully!')
"
```

バリデーションエラーが出なければ config は正常。

## OAuth 認証（初回のみ）

```bash
uv run yt-channel-status
```

初回実行時にブラウザが開き Google アカウントで認証 → `auth/token.json` が生成される。

## channel_id の自動取得

`channel.channel_id` が未設定の場合、OAuth 認証後に以下で取得:

```bash
uv run python3 -c "
from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler
handler = YouTubeOAuthHandler()
service = handler.get_youtube_service()
resp = service.channels().list(part='id', mine=True).execute()
print(resp['items'][0]['id'])
"
```

出力された ID を `config/channel/meta.json` の `channel.channel_id` に設定する。

## ブランディング素材生成

チャンネル開設直後に必要:

- **バナー画像** (`branding/banner.png`): 2048 x 1152 px、6 MB 以下、アスペクト比 16:9
- **プロフィール写真** (`branding/icon.png`): 800 x 800 px 程度、4 MB 以下、PNG 形式、アスペクト比 1:1

```bash
# アイコン生成
uv run yt-generate-image --prompt "..." --output branding/icon.png --aspect-ratio 1:1 -y
# バナー生成
uv run yt-generate-image --prompt "..." --output branding/banner.png --aspect-ratio 16:9 -y

# リサイズ（上限超過時）
uv run python3 -c "
from PIL import Image
icon = Image.open('branding/icon.png').resize((800, 800), Image.LANCZOS)
icon.save('branding/icon.png', 'PNG', optimize=True)
banner = Image.open('branding/banner.png').resize((2048, 1152), Image.LANCZOS)
banner.save('branding/banner.png', 'PNG', optimize=True)
"
```
