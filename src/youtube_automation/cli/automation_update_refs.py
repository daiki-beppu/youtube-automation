"""Pin/ref parsing and pyproject rewriting for `yt-automation-update`."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field

from youtube_automation.utils.exceptions import ConfigError

UPSTREAM_REPO = "daiki-beppu/youtube-automation"
PACKAGE_NAME = "youtube-channels-automation"

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_RELEASE_TAG_RE = re.compile(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
_DEPENDENCY_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_GIT_REFERENCE_RE = re.compile(r"@\s*git\+(?P<url>[^\s;]+)")


@dataclass(frozen=True)
class Pin:
    """pyproject.toml における youtube-channels-automation の参照形式."""

    style: str  # "inline-table" ([tool.uv.sources]) | "url" (PEP 508 direct reference)
    kind: str  # "tag" | "branch" | "sha" | "registry"
    value: str  # tag 名 / branch 名 / sha / requirement 文字列
    git_url: str | None = field(default=None, compare=False)


def _canonicalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _split_git_ref(url: str) -> tuple[str, str | None]:
    """git URL 末尾の @<ref> を分離する。ssh 形式の git@host は ref と誤認しない."""
    base, sep, ref = url.rpartition("@")
    if sep and ref and "/" not in ref and ":" not in ref:
        return base, ref
    return url, None


def _normalized_github_path(path: str) -> str:
    return urllib.parse.unquote(path).strip("/").removesuffix(".git")


def _is_official_upstream_url(git_url: str) -> bool:
    url = git_url.removeprefix("git+")
    if url.startswith("git@github.com:"):
        path = _normalized_github_path(url.removeprefix("git@github.com:"))
        return path == UPSTREAM_REPO
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        if parsed.hostname != "github.com":
            return False
        if parsed.params or parsed.query or parsed.fragment:
            return False
        path = _normalized_github_path(parsed.path)
        return path == UPSTREAM_REPO
    if parsed.scheme == "ssh":
        if parsed.hostname != "github.com" or parsed.username != "git":
            return False
        if parsed.params or parsed.query or parsed.fragment:
            return False
        path = _normalized_github_path(parsed.path)
        return path == UPSTREAM_REPO
    return False


def _require_official_upstream(git_url: str) -> None:
    if not _is_official_upstream_url(git_url):
        raise ConfigError(
            f"{PACKAGE_NAME} の Git URL は official upstream ({UPSTREAM_REPO}) を参照してください: {git_url}"
        )


def _classify_git_ref(ref: str) -> tuple[str, str]:
    if ref == "main":
        return "branch", ref
    if _SHA_RE.fullmatch(ref):
        return "sha", ref
    if _RELEASE_TAG_RE.fullmatch(ref):
        return "tag", ref
    raise ConfigError(f"pyproject.toml の Git ref は main / 40 桁 sha / vX.Y.Z tag 以外を自動追従できません: {ref}")


def _detect_pin(pyproject: dict) -> Pin:
    tool = pyproject.get("tool")
    sources = None
    if isinstance(tool, dict):
        uv_table = tool.get("uv")
        if isinstance(uv_table, dict):
            sources = uv_table.get("sources")
    if isinstance(sources, dict):
        for key, spec in sources.items():
            if _canonicalize_name(key) != PACKAGE_NAME or not isinstance(spec, dict):
                continue
            git_url = spec.get("git")
            if not isinstance(git_url, str):
                continue
            _require_official_upstream(git_url)
            ref_keys = [key for key in ("tag", "rev", "branch") if key in spec]
            if len(ref_keys) > 1:
                raise ConfigError(
                    f"[tool.uv.sources] の tag / rev / branch は同時指定できません: {', '.join(ref_keys)}"
                )
            tag = spec.get("tag")
            if isinstance(tag, str):
                kind, _ = _classify_git_ref(tag)
                if kind != "tag":
                    raise ConfigError(f"[tool.uv.sources] の tag には vX.Y.Z 形式の tag を指定してください: {tag}")
                return Pin("inline-table", "tag", tag, git_url)
            rev = spec.get("rev")
            if isinstance(rev, str):
                kind, _ = _classify_git_ref(rev)
                if kind != "sha":
                    raise ConfigError(f"[tool.uv.sources] の rev には 40 桁の hex sha を指定してください: {rev}")
                return Pin("inline-table", "sha", rev, git_url)
            branch = spec.get("branch")
            branch_ref = branch if isinstance(branch, str) else "main"
            kind, value = _classify_git_ref(branch_ref)
            if kind != "branch":
                raise ConfigError(f"[tool.uv.sources] の branch は main のみ自動追従できます: {branch_ref}")
            return Pin("inline-table", "branch", value, git_url)

    project = pyproject.get("project")
    dependencies = project.get("dependencies") if isinstance(project, dict) else None
    if isinstance(dependencies, list):
        for dependency in dependencies:
            if not isinstance(dependency, str):
                continue
            match = _DEPENDENCY_NAME_RE.match(dependency)
            if not match or _canonicalize_name(match.group(1)) != PACKAGE_NAME:
                continue
            git_match = _GIT_REFERENCE_RE.search(dependency)
            if not git_match:
                return Pin("url", "registry", dependency.strip())
            url = git_match.group("url").split("#", 1)[0]
            base_url, ref = _split_git_ref(url)
            _require_official_upstream(base_url)
            if ref is None:
                return Pin("url", "branch", "main", base_url)
            kind, value = _classify_git_ref(ref)
            return Pin("url", kind, value, base_url)
    raise ConfigError(f"pyproject.toml から {PACKAGE_NAME} の pin を特定できません")


def _describe_pin(pin: Pin) -> str:
    style = "inline table [tool.uv.sources]" if pin.style == "inline-table" else "URL 直接参照 (dependencies)"
    if pin.kind == "tag":
        return f"tag pin ({pin.value}, {style})"
    if pin.kind == "sha":
        return f"sha pin ({pin.value[:12]}, {style})"
    if pin.kind == "branch":
        return f"main 追従 (branch={pin.value}, {style})"
    return f"registry 参照 ({pin.value})"


def _rewrite_pin(text: str, pin: Pin, new_ref: str) -> str:
    """pyproject.toml のテキストを直接書き換える（コメント・整形を保存するため TOML 再出力はしない）."""
    package_pattern = r"[\"']?youtube[-_.]channels[-_.]automation[\"']?"
    if pin.style == "inline-table":
        key = "tag" if pin.kind == "tag" else "rev"
        pattern = re.compile(
            r"(" + package_pattern + r"\s*=\s*\{[^}]*?" + key + r"\s*=\s*)([\"'])([^\"']+)(\2)",
            re.DOTALL,
        )
        new_text, count = pattern.subn(lambda m: f"{m.group(1)}{m.group(2)}{new_ref}{m.group(4)}", text, count=1)
    else:
        pattern = re.compile(r"(" + package_pattern + r"\s*@\s*git\+)([^\s\"';]+)")

        def _replace_url_ref(match: re.Match[str]) -> str:
            url, sep, fragment = match.group(2).partition("#")
            base_url, ref = _split_git_ref(url)
            if ref is None:
                raise ConfigError(
                    "pyproject.toml の URL 直接参照に ref が無いため自動書き換えできません。"
                    "該当行を手動で更新してから再実行してください"
                )
            suffix = f"{sep}{fragment}" if sep else ""
            return f"{match.group(1)}{base_url}@{new_ref}{suffix}"

        new_text, count = pattern.subn(_replace_url_ref, text, count=1)
    if count != 1:
        raise ConfigError(
            "pyproject.toml の pin 記法が想定と異なり自動書き換えできません。"
            "該当行を手動で更新してから再実行してください"
        )
    return new_text
