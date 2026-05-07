"""音声拡張子の共通定数。

`metadata_generator`（個別楽曲解析）と `video_validator`（個別動画と音声ファイル数の整合性チェック）
で共通利用する。シェルスクリプト `.claude/skills/videoup/references/generate_videos.sh` 側の master-mix 候補リストとは
独立に管理する（用途と並び順の意味づけが異なるため）。
"""

AUDIO_EXTS: frozenset[str] = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac"})
