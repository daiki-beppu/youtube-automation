"""intro skill の references スクリプトが共有する小さなヘルパー群。

スクリプトが配布物 (`yt-skills sync`) 経由でチャンネル側に置かれた状態でも、
ローカル開発から `python <script>.py` で直接実行された状態でも、または
`tests/_skill_loader.load_skill_script` 経由で unit test から import された
状態でも、同じ import 経路で読めるようにするため、この module を 1 箇所に
集約する。各スクリプトは自身の親ディレクトリを `sys.path` に追加した上で
`from _common import resolve_repo_root` する (アーキテクチャレビュー
ARCH-NEW-resolve-repo-root-dry の修正案に従う実装)。
"""
from __future__ import annotations

from pathlib import Path


def resolve_repo_root(start: Path) -> Path:
    """`config/channel/meta.json` を持つディレクトリを祖先探索で解決する。

    Args:
        start: 探索の起点 (通常は呼び出し側スクリプトの `__file__` の親)

    Returns:
        `config/channel/meta.json` を含む最も近い祖先ディレクトリ

    Raises:
        FileNotFoundError: 起点から祖先方向に `config/channel/meta.json` が
            見つからなかったとき
    """
    cur = start.resolve()
    for ancestor in [cur, *cur.parents]:
        if (ancestor / 'config' / 'channel' / 'meta.json').exists():
            return ancestor
    raise FileNotFoundError(f'config/channel/meta.json not found upward from {start}')
