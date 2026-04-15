# 検証・認証ユーティリティ

`/channel-setup` `/channel-import` から共通参照する検証コマンド集。
すべて **fully-qualified import**（`from youtube_automation...`）を使用する（CLAUDE.md 規約）。

## JSON 構文検証

```bash
python3 -c "import json; json.load(open('config/channel_config.json'))"
```

エラーが出なければ構文 OK。

## ChannelConfig ロードテスト

```bash
uv run python3 -c "
from youtube_automation.utils.channel_config import ChannelConfig
c = ChannelConfig.load()
print(f'Channel: {c.channel_name} ({c.channel_short})')
print(f'Genre: {c.genre_primary} / {c.genre_style}')
print(f'Benchmarks: {len(c.benchmark_config.get(\"channels\", []))} channels')
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

出力された ID を `config/channel_config.json` の `channel.channel_id` に設定する。

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
python3 -c "
from PIL import Image
icon = Image.open('branding/icon.png').resize((800, 800), Image.LANCZOS)
icon.save('branding/icon.png', 'PNG', optimize=True)
banner = Image.open('branding/banner.png').resize((2048, 1152), Image.LANCZOS)
banner.save('branding/banner.png', 'PNG', optimize=True)
"
```
