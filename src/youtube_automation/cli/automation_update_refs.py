"""Pin/ref parsing and pyproject rewriting for `yt-automation-update`."""

from __future__ import annotations

import re
import tomllib
import urllib.parse
from dataclasses import dataclass, field

from youtube_automation.utils.exceptions import ConfigError

UPSTREAM_REPO = "daiki-beppu/youtube-automation"
PACKAGE_NAME = "youtube-channels-automation"

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_RELEASE_TAG_RE = re.compile(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
_DEPENDENCY_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_GIT_REFERENCE_RE = re.compile(r"@\s*git\+(?P<url>[^\s;]+)")
_TABLE_HEADER_RE = re.compile(r"(?m)^[ \t]*\[(?P<name>[^\]\n]+)\][ \t]*(?:#.*)?$")
_PACKAGE_KEY_PATTERN = (
    r"(?:youtube[-_.]channels[-_.]automation|"
    r"\"youtube[-_.]channels[-_.]automation\"|"
    r"'youtube[-_.]channels[-_.]automation')"
)


@dataclass(frozen=True)
class Pin:
    """pyproject.toml における youtube-channels-automation の参照形式."""

    style: str  # "inline-table" ([tool.uv.sources]) | "url" (PEP 508 direct reference)
    kind: str  # "tag" | "branch" | "sha" | "registry"
    value: str  # tag 名 / branch 名 / sha / requirement 文字列
    git_url: str | None = field(default=None, compare=False)
    dependency: str | None = field(default=None, compare=False)


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
                return Pin("url", "registry", dependency.strip(), dependency=dependency)
            url = git_match.group("url").split("#", 1)[0]
            base_url, ref = _split_git_ref(url)
            _require_official_upstream(base_url)
            if ref is None:
                return Pin("url", "branch", "main", base_url, dependency)
            kind, value = _classify_git_ref(ref)
            return Pin("url", kind, value, base_url, dependency)
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


def _find_table_range(text: str, table_name: str) -> tuple[int, int]:
    for match in _TABLE_HEADER_RE.finditer(text):
        if match.group("name").strip() != table_name:
            continue
        next_match = _TABLE_HEADER_RE.search(text, match.end())
        return match.end(), next_match.start() if next_match else len(text)
    raise ConfigError(f"pyproject.toml の [{table_name}] table を特定できません")


def _find_array_range(text: str, start: int) -> tuple[int, int]:
    bracket_start = text.find("[", start)
    if bracket_start == -1:
        raise ConfigError("pyproject.toml の dependencies 配列を特定できません")

    depth = 0
    in_quote: str | None = None
    escaped = False
    in_comment = False
    for index in range(bracket_start, len(text)):
        char = text[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            continue
        if in_quote:
            if in_quote == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == in_quote and not escaped:
                in_quote = None
            escaped = False
            continue
        if char == "#":
            in_comment = True
            continue
        if char in {'"', "'"}:
            in_quote = char
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return bracket_start, index + 1
    raise ConfigError("pyproject.toml の dependencies 配列が閉じていません")


def _find_project_dependencies_range(text: str) -> tuple[int, int]:
    project_start, project_end = _find_table_range(text, "project")
    body = text[project_start:project_end]
    match = re.search(r"(?m)^[ \t]*dependencies[ \t]*=", body)
    if not match:
        raise ConfigError("pyproject.toml の [project].dependencies を特定できません")
    return _find_array_range(text, project_start + match.end())


def _iter_toml_string_spans(text: str):
    in_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            index += 1
            continue
        if char == "#":
            in_comment = True
            index += 1
            continue
        if char not in {'"', "'"}:
            index += 1
            continue
        quote = char
        quote_start = index
        index += 1
        content_start = index
        escaped = False
        while index < len(text):
            char = text[index]
            if quote == '"' and char == "\\" and not escaped:
                escaped = True
                index += 1
                continue
            if char == quote and not escaped:
                yield quote_start, content_start, index, index + 1, text[content_start:index]
                index += 1
                break
            escaped = False
            index += 1


def _rewrite_url_dependency(dependency: str, new_ref: str) -> str:
    git_match = _GIT_REFERENCE_RE.search(dependency)
    if not git_match:
        raise ConfigError("pyproject.toml の URL 直接参照を特定できません")
    url, sep, fragment = git_match.group("url").partition("#")
    base_url, ref = _split_git_ref(url)
    if ref is None:
        raise ConfigError(
            "pyproject.toml の URL 直接参照に ref が無いため自動書き換えできません。"
            "該当行を手動で更新してから再実行してください"
        )
    start, end = git_match.span("url")
    suffix = f"{sep}{fragment}" if sep else ""
    return f"{dependency[:start]}{base_url}@{new_ref}{suffix}{dependency[end:]}"


def _rewrite_inline_table_pin(text: str, pin: Pin, new_ref: str) -> tuple[str, int]:
    start, end = _find_table_range(text, "tool.uv.sources")
    body = text[start:end]
    key = "tag" if pin.kind == "tag" else "rev"
    pattern = re.compile(
        r"(?m)^([ \t]*" + _PACKAGE_KEY_PATTERN + r"\s*=\s*\{[^\n}]*?" + key + r"\s*=\s*)([\"'])([^\"']+)(\2)"
    )
    new_body, count = pattern.subn(lambda m: f"{m.group(1)}{m.group(2)}{new_ref}{m.group(4)}", body, count=1)
    return f"{text[:start]}{new_body}{text[end:]}", count


def _rewrite_url_pin(text: str, pin: Pin, new_ref: str) -> tuple[str, int]:
    if pin.dependency is None:
        raise ConfigError("pyproject.toml の active dependency を特定できません")

    start, end = _find_project_dependencies_range(text)
    body = text[start:end]
    matches = [
        (quote_start, content_start, content_end, quote_end)
        for quote_start, content_start, content_end, quote_end, value in _iter_toml_string_spans(body)
        if value == pin.dependency
    ]
    if len(matches) != 1:
        raise ConfigError(
            "pyproject.toml の active dependency が一意に特定できないため自動書き換えできません。"
            "該当行を手動で更新してから再実行してください"
        )

    quote_start, content_start, content_end, quote_end = matches[0]
    new_dependency = _rewrite_url_dependency(pin.dependency, new_ref)
    new_body = f"{body[:content_start]}{new_dependency}{body[content_end:]}"
    return f"{text[:start]}{new_body}{text[end:]}", 1 if quote_end > quote_start else 0


def _verify_rewritten_pin(text: str, pin: Pin, new_ref: str) -> None:
    try:
        rewritten_pin = _detect_pin(tomllib.loads(text))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"pyproject.toml の書き換え結果を TOML として読めません: {e}") from e
    if rewritten_pin.style != pin.style or rewritten_pin.kind != pin.kind or rewritten_pin.value != new_ref:
        raise ConfigError(
            "pyproject.toml の pin 書き換え結果を検証できません。検出対象と書き換え対象が一致しているか確認してください"
        )


def _rewrite_pin(text: str, pin: Pin, new_ref: str) -> str:
    """pyproject.toml のテキストを直接書き換える（コメント・整形を保存するため TOML 再出力はしない）."""
    if pin.style == "inline-table":
        new_text, count = _rewrite_inline_table_pin(text, pin, new_ref)
    else:
        new_text, count = _rewrite_url_pin(text, pin, new_ref)
    if count != 1:
        raise ConfigError(
            "pyproject.toml の pin 記法が想定と異なり自動書き換えできません。"
            "該当行を手動で更新してから再実行してください"
        )
    _verify_rewritten_pin(new_text, pin, new_ref)
    return new_text
