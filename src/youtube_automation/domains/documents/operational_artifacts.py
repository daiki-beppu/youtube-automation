"""生成される運用成果物の正本 inventory と repository ratchet。"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from importlib.resources import files
from pathlib import Path
from typing import Final, Iterable, Literal, Mapping

from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.documents.published import read_published_json_document
from youtube_automation.domains.documents.schema_registry import RepositorySchema, repository_schema_names
from youtube_automation.domains.skills.inventory import SkillInventory

_TARGET_SEGMENTS: Final[tuple[str, ...]] = (
    "reports/",
    "docs/channel/",
    "docs/plans/",
    "docs/benchmarks/",
    "20-documentation/",
)


@dataclass(frozen=True, slots=True)
class OperationalArtifact:
    """One schema-backed, human-readable generated document."""

    path: str
    owner: str
    schema: str
    consumers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InvalidArtifact:
    """A canonical artifact instance which failed its published-document contract."""

    path: Path
    reason: str


FreshnessReason = Literal["missing", "relative", "absolute"]


@dataclass(frozen=True, slots=True)
class ArtifactFreshness:
    """Result of comparing an artifact set with its upstream evidence."""

    is_stale: bool
    reason: FreshnessReason | None
    artifact_date: date | None
    against_date: date | None


@dataclass(frozen=True, slots=True)
class ArtifactSet:
    """Resolved valid and invalid instances of one inventory artifact."""

    artifact: OperationalArtifact
    valid: tuple[Path, ...]
    invalid: tuple[InvalidArtifact, ...]
    latest: Path | None

    def freshness(
        self,
        *,
        against: Path | ArtifactSet | Iterable[Path],
        max_age_days: int | None = None,
        today: date | None = None,
    ) -> ArtifactFreshness:
        """Compare filename dates, optionally applying an absolute age limit."""
        artifact_date = _filename_date(self.latest) if self.latest is not None else None
        against_date = _latest_against_date(against)
        if artifact_date is None:
            return ArtifactFreshness(True, "missing", None, against_date)
        if against_date is not None and artifact_date < against_date:
            return ArtifactFreshness(True, "relative", artifact_date, against_date)
        if max_age_days is not None:
            if max_age_days < 0:
                raise ValueError("max_age_days は 0 以上で指定してください")
            # Absolute freshness describes the age of upstream evidence.  With no
            # upstream date there is nothing against which to declare the artifact
            # stale; using the artifact's own date here would turn an unavailable
            # upstream into a false stale result.
            if against_date is not None and ((today or date.today()) - against_date).days > max_age_days:
                return ArtifactFreshness(True, "absolute", artifact_date, against_date)
        return ArtifactFreshness(False, None, artifact_date, against_date)


@dataclass(frozen=True, slots=True)
class AllowlistEntry:
    """One intentional exception with a concrete owner and rationale."""

    path: str
    owner: str
    reason: str


@dataclass(frozen=True, slots=True)
class OperationalArtifactInventory:
    """Canonical structured-document and explicit exception inventory."""

    artifacts: tuple[OperationalArtifact, ...]
    hand_written_inputs: tuple[AllowlistEntry, ...]
    repository_docs: tuple[AllowlistEntry, ...]
    machine_only: tuple[AllowlistEntry, ...]
    other_writes: tuple[AllowlistEntry, ...]
    schema_allowlist: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> OperationalArtifactInventory:
        """Parse a JSON-compatible mapping and reject ambiguous declarations."""
        raw_artifacts = _mapping_list(payload.get("artifacts"), "artifacts")
        artifacts = tuple(
            OperationalArtifact(
                path=_string(item, "path"),
                owner=_string(item, "owner"),
                schema=_string(item, "schema"),
                consumers=tuple(_string_list(item.get("consumers"), "consumers")),
            )
            for item in raw_artifacts
        )
        paths = [item.path for item in artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("operational artifact path は一意である必要があります")

        allowlists = payload.get("allowlists")
        if not isinstance(allowlists, Mapping):
            raise ValueError("allowlists は object で指定してください")
        return cls(
            artifacts=artifacts,
            hand_written_inputs=_allowlist(allowlists, "hand_written_inputs"),
            repository_docs=_allowlist(allowlists, "repository_docs"),
            machine_only=_allowlist(allowlists, "machine_only"),
            other_writes=_allowlist(allowlists, "other_writes"),
            schema_allowlist=tuple(_string_list(allowlists.get("schemas"), "schemas")),
        )


def load_operational_artifact_inventory() -> OperationalArtifactInventory:
    """Load the wheel-shipped canonical inventory."""
    resource = files("youtube_automation.domains.documents").joinpath("operational-artifacts.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("operational-artifacts.json は object である必要があります")
    return OperationalArtifactInventory.from_mapping(payload)


def resolve_artifacts(
    channel_dir: Path,
    artifact_id: str,
    inventory: OperationalArtifactInventory | None = None,
) -> ArtifactSet:
    """Resolve one inventory path to validated runtime instances under a channel."""
    contract = inventory or load_operational_artifact_inventory()
    matches = [artifact for artifact in contract.artifacts if artifact.path == artifact_id]
    if len(matches) != 1:
        raise ValueError(f"未登録の operational artifact です: {artifact_id}")
    artifact = matches[0]
    canonical = _canonical_path_pattern(artifact.path)
    glob_pattern = re.sub(r"<[^/]+>", "*", artifact.path)
    candidates = sorted(path for path in channel_dir.glob(glob_pattern) if path.is_file())
    valid: list[Path] = []
    invalid: list[InvalidArtifact] = []
    schema = RepositorySchema(artifact.schema)
    for path in candidates:
        relative = path.relative_to(channel_dir).as_posix()
        # A broad inventory glob may also match sidecars. They are other artifact
        # kinds, not malformed instances of this artifact.
        if canonical.fullmatch(relative) is None:
            continue
        try:
            read_published_json_document(path, schema)
        except AutomationError as error:
            invalid.append(InvalidArtifact(path, str(error)))
        else:
            valid.append(path)
    latest = _latest_dated_path(valid)
    return ArtifactSet(artifact, tuple(valid), tuple(invalid), latest)


def _canonical_path_pattern(path: str) -> re.Pattern[str]:
    pieces: list[str] = []
    cursor = 0
    token_pattern = re.compile(r"\*|<[^/]+>")
    for match in token_pattern.finditer(path):
        pieces.append(re.escape(path[cursor : match.start()]))
        pieces.append(r"\d{8}" if match.group() == "*" else r"[^/]+")
        cursor = match.end()
    pieces.append(re.escape(path[cursor:]))
    return re.compile("".join(pieces))


def _filename_date(path: Path) -> date | None:
    match = re.search(r"(?<!\d)(\d{8})(?!\d)", path.name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _latest_dated_path(paths: Iterable[Path]) -> Path | None:
    return max(paths, key=lambda path: (_filename_date(path) or date.min, path.name), default=None)


def _latest_against_date(against: Path | ArtifactSet | Iterable[Path]) -> date | None:
    if isinstance(against, ArtifactSet):
        paths = against.valid
    elif isinstance(against, Path):
        paths = (against,)
    else:
        paths = tuple(against)
    latest = _latest_dated_path(paths)
    return _filename_date(latest) if latest is not None else None


def lint_operational_artifacts(
    repository_root: Path,
    skills: SkillInventory,
    inventory: OperationalArtifactInventory | None = None,
    *,
    repository_schemas: tuple[str, ...] | None = None,
) -> list[str]:
    """Return concrete repository contract violations for generated artifacts."""
    contract = inventory or load_operational_artifact_inventory()
    schemas = repository_schema_names() if repository_schemas is None else repository_schemas
    writes, reads = _skill_declarations(skills)
    source_writes, source_violations = _scan_python_contracts(repository_root, contract)
    writes.update(source_writes)
    violations: list[str] = []
    violations.extend(source_violations)
    artifacts = {item.path: item for item in contract.artifacts}
    markdown = {(item.owner, item.path): item for item in contract.hand_written_inputs}
    machine = {(item.owner, item.path): item for item in contract.machine_only}
    other = {(item.owner, item.path): item for item in contract.other_writes}

    for owner, path in sorted(writes):
        if not _is_target(path):
            continue
        if path.endswith(".md"):
            if (owner, path) not in markdown:
                violations.append(f"Markdown writer は禁止です: owner={owner} path={path}")
            continue
        if path.endswith(".json"):
            artifact = artifacts.get(path)
            if artifact is None:
                if (owner, path) not in machine:
                    violations.append(
                        f"JSON に HTML pair または machine-only 指定がありません: owner={owner} path={path}"
                    )
                continue
            if artifact.owner != owner:
                violations.append(
                    f"artifact owner が一致しません: path={path} inventory={artifact.owner} declaration={owner}"
                )
            html = str(Path(path).with_suffix(".html"))
            if (owner, html) not in writes:
                violations.append(f"JSON/HTML pair が欠落しています: owner={owner} path={html}")
            continue
        if path.endswith(".html"):
            json_path = str(Path(path).with_suffix(".json"))
            artifact = artifacts.get(json_path)
            if artifact is None or artifact.owner != owner:
                violations.append(f"orphan HTML です: owner={owner} path={path}")
            continue
        if (owner, path) not in other:
            violations.append(f"未登録の運用成果物です: owner={owner} path={path}")

    for artifact in contract.artifacts:
        if (artifact.owner, artifact.path) not in writes:
            violations.append(f"orphan inventory artifact です: owner={artifact.owner} path={artifact.path}")
        for consumer in artifact.consumers:
            if (consumer, artifact.path) not in reads:
                violations.append(f"stale consumer です: consumer={consumer} path={artifact.path}")

    for owner, path in sorted(reads):
        artifact = artifacts.get(path)
        if artifact is not None and owner not in artifact.consumers and owner != artifact.owner:
            violations.append(f"schema未検証consumerです: consumer={owner} path={path}")

    used_schemas = {artifact.schema for artifact in contract.artifacts}
    known_schemas = set(schemas)
    for artifact in contract.artifacts:
        if artifact.schema not in known_schemas:
            violations.append(f"未登録 schema です: path={artifact.path} schema={artifact.schema}")
    for schema in sorted(known_schemas - used_schemas - set(contract.schema_allowlist)):
        violations.append(f"orphan schema です: {schema}")
    for schema in sorted(set(contract.schema_allowlist) - known_schemas):
        violations.append(f"stale allowlist です: schema={schema}")

    declared_writes = set(writes)
    for label, entries in (
        ("hand_written_inputs", contract.hand_written_inputs),
        ("machine_only", contract.machine_only),
        ("other_writes", contract.other_writes),
    ):
        for entry in entries:
            if (entry.owner, entry.path) not in declared_writes:
                violations.append(f"stale allowlist です: category={label} owner={entry.owner} path={entry.path}")
    if (repository_root / ".claude" / "skills").is_dir():
        for entry in contract.repository_docs:
            if not (repository_root / entry.path).is_file():
                violations.append(f"stale allowlist です: category=repository_docs path={entry.path}")
    return violations


def _skill_declarations(skills: SkillInventory) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    writes: set[tuple[str, str]] = set()
    reads: set[tuple[str, str]] = set()
    for directory in skills.skill_directories():
        if not (directory / "SKILL.md").is_file():
            continue
        declaration = skills.artifacts(directory.name)
        writes.update((directory.name, path) for path in _expanded_paths(declaration.writes))
        reads.update((directory.name, path) for path in _expanded_paths(declaration.reads))
        for markdown in directory.rglob("*.md"):
            text = markdown.read_text(encoding="utf-8")
            writes.update((directory.name, path) for path in _declared_paths(text, "書き込む"))
            reads.update((directory.name, path) for path in _declared_paths(text, "読み込む"))
    return writes, reads


def _declared_paths(text: str, label: str) -> tuple[str, ...]:
    paths: list[str] = []
    prefix = f"- `{label}`:"
    for line in text.splitlines():
        if line.startswith(prefix):
            paths.extend(re.findall(r"`([^`]+)`", line.removeprefix(prefix)))
    return _expanded_paths(tuple(path for path in paths if path != "なし"))


def _scan_python_contracts(
    repository_root: Path, contract: OperationalArtifactInventory
) -> tuple[set[tuple[str, str]], list[str]]:
    """Find literal writer/consumer evidence in shipped Python and skill scripts."""
    writes: set[tuple[str, str]] = set()
    violations: list[str] = []
    artifacts_by_name = {
        Path(artifact.path).name: artifact
        for artifact in contract.artifacts
        if "<" not in Path(artifact.path).name and "*" not in Path(artifact.path).name
    }
    roots = (repository_root / "src" / "youtube_automation", repository_root / ".claude" / "skills")
    for root in roots:
        if not root.is_dir():
            continue
        for source in sorted(root.rglob("*.py")):
            try:
                text = source.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, UnicodeError, SyntaxError):
                continue
            relative = source.relative_to(repository_root).as_posix()
            owner_hint = _source_owner(relative)
            for node in _scopes(tree):
                constants = {
                    child.value
                    for child in ast.walk(node)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str) and _is_target(child.value)
                }
                if _has_writer_call(node):
                    for path in constants:
                        if not path.endswith((".md", ".json", ".html")):
                            continue
                        owner = owner_hint or _declared_owner(path, contract) or relative
                        writes.add((owner, path))
                if not _has_unvalidated_reader(node):
                    continue
                for path in constants:
                    artifact = artifacts_by_name.get(Path(path).name)
                    if artifact is not None:
                        violations.append(f"schema未検証consumerです: consumer={relative} path={path}")
    return writes, violations


def _scopes(tree: ast.AST) -> tuple[ast.AST, ...]:
    functions = tuple(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return functions or (tree,)


def _has_writer_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Attribute) and child.func.attr in {"write_text", "write_bytes"}:
            return True
        if isinstance(child.func, ast.Name) and child.func.id == "open":
            modes = [argument.value for argument in child.args[1:] if isinstance(argument, ast.Constant)]
            if any(isinstance(mode, str) and set(mode) & {"w", "a", "x"} for mode in modes):
                return True
    return False


def _has_unvalidated_reader(node: ast.AST) -> bool:
    names = {
        child.func.attr if isinstance(child.func, ast.Attribute) else child.func.id
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, (ast.Attribute, ast.Name))
    }
    if not names.intersection({"read_text", "load", "loads"}):
        return False
    validators = {
        "read_published_json_document",
        "validate_repository_document",
        "read_video_description_document",
        "read_video_description_metadata",
        "read_suno_prompt_entries",
    }
    return names.isdisjoint(validators)


def _source_owner(relative: str) -> str | None:
    parts = Path(relative).parts
    if len(parts) >= 3 and parts[:2] == (".claude", "skills"):
        return parts[2]
    return None


def _declared_owner(path: str, contract: OperationalArtifactInventory) -> str | None:
    owners = {
        item.owner
        for item in (
            *contract.artifacts,
            *contract.hand_written_inputs,
            *contract.machine_only,
            *contract.other_writes,
        )
        if item.path == path
    }
    return next(iter(owners)) if len(owners) == 1 else None


def _expanded_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    expanded: list[str] = []
    for path in paths:
        if path == ".html" and expanded and expanded[-1].endswith(".json"):
            expanded.append(str(Path(expanded[-1]).with_suffix(".html")))
        elif path.endswith(".{json,html}"):
            stem = path.removesuffix(".{json,html}")
            expanded.extend((f"{stem}.json", f"{stem}.html"))
        else:
            expanded.append(path)
    return tuple(expanded)


def _is_target(path: str) -> bool:
    return any(segment in path for segment in _TARGET_SEGMENTS)


def _mapping_list(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field} は object array で指定してください")
    return list(value)


def _string(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} は空でない文字列で指定してください")
    return value


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} は空でない string array で指定してください")
    return list(value)


def _allowlist(mapping: Mapping[str, object], field: str) -> tuple[AllowlistEntry, ...]:
    return tuple(
        AllowlistEntry(path=_string(item, "path"), owner=_string(item, "owner"), reason=_string(item, "reason"))
        for item in _mapping_list(mapping.get(field), field)
    )
