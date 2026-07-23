"""DistroKid naming policy."""

import re


def kebab_to_title(dirname: str) -> str:
    return re.sub(r"[-_]+", " ", dirname).strip().title()
