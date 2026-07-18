"""Shared argparse contracts for public ``yt-*`` CLIs."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


class CompetitorArgumentParser(argparse.ArgumentParser):
    """Reject the removed benchmark ``--channel`` flag with migration guidance."""

    def parse_known_args(
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> tuple[argparse.Namespace, list[str]]:
        tokens = list(sys.argv[1:] if args is None else args)
        if any(token == "--channel" or token.startswith("--channel=") for token in tokens):
            self.error("--channel は --competitor に変わりました。--competitor を使用してください")
        return super().parse_known_args(tokens, namespace)
