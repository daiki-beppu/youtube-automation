from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.commands.analytics import experiment as cli
from youtube_automation.core.errors import ValidationError

TODAY = date(2026, 8, 13)


def _item(video_id: str, vpd: float, title: str = "") -> dict[str, object]:
    return {"video_id": video_id, "title": title, "vpd": vpd}


def _ranking(items: list[dict[str, object]], *, min_age_days: int = 7) -> dict[str, object]:
    return {"n": len(items), "min_age_days": min_age_days, "ranking": items}


def _config(*, judge_after_days: object = 14) -> dict[str, object]:
    return {"experiment": {"judge_after_days": judge_after_days}}


def _channel_config(themes: dict[str, list[str]] | None = None) -> object:
    return SimpleNamespace(content=SimpleNamespace(tags=SimpleNamespace(themes=themes or {})))


def _register(
    path: Path,
    ranking: dict[str, object],
    *,
    target: str = "next-collection",
    lever: str = "thumbnail",
    baseline_scope: str = "all",
) -> dict[str, object]:
    return cli.register_experiment(
        lever=lever,
        target=target,
        change="text-heavy -> textless",
        hypothesis_source="20260812-analysis-thumbnail",
        baseline_scope=baseline_scope,
        experiments_path=path,
        today=TODAY,
        ranking_loader=lambda: ranking,
        skill_config=_config(),
        theme_keywords=_channel_config({"focus": ["study"]}).content.tags.themes,
    )


def test_register_appends_one_schema_valid_line_and_stdout_record_matches(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "data" / "experiments.jsonl"
    ranking = _ranking([_item("a", 0), _item("b", 10), _item("c", 20), _item("d", 30)])
    monkeypatch.setattr(cli, "channel_dir", lambda: tmp_path)
    monkeypatch.setattr(cli.vpd_rank, "_load_ranking", lambda **_kwargs: ranking)
    monkeypatch.setattr(cli, "load_skill_config", lambda _name: _config())
    monkeypatch.setattr(cli, "load_config", lambda: _channel_config())
    monkeypatch.setattr(cli, "_today", lambda: TODAY)

    assert (
        cli.main(
            [
                "register",
                "--lever",
                "thumbnail",
                "--target",
                "next-collection",
                "--change",
                "text-heavy -> textless",
                "--hypothesis-source",
                "20260812-analysis-thumbnail",
            ]
        )
        == 0
    )

    stdout_record = json.loads(capsys.readouterr().out)
    file_record = json.loads(path.read_text(encoding="utf-8"))
    assert stdout_record == file_record
    assert file_record == {
        "schema_version": 1,
        "id": "20260813-thumbnail-next-collection",
        "registered_date": "2026-08-13",
        "lever": "thumbnail",
        "change": "text-heavy -> textless",
        "hypothesis_source": "20260812-analysis-thumbnail",
        "target": "next-collection",
        "baseline_vpd": 15.0,
        "baseline_basis": "source=yt-vpd-rank; scope=all; n=4; median=15.0; min_age_days=7",
        "judge_after_days": 14,
        "status": "pending",
    }
    assert cli.validate_entries(path) == []


@pytest.mark.parametrize("values, expected", [([0, 10, 20], 10.0), ([0, 0, 10, 20], 5.0)])
def test_baseline_uses_all_eligible_ranking_median_for_odd_even_and_zero(
    tmp_path, values: list[int], expected: float
) -> None:
    record = _register(tmp_path / "experiments.jsonl", _ranking([_item(str(i), v) for i, v in enumerate(values)]))

    assert record["baseline_vpd"] == expected
    assert f"n={len(values)}" in record["baseline_basis"]


def test_theme_scope_uses_existing_classifier_and_ranking_population(tmp_path) -> None:
    ranking = _ranking(
        [
            _item("a", 1, "Deep Study Focus"),
            _item("b", 3, "Focus Session"),
            _item("c", 100, "Ambient Sleep"),
        ],
        min_age_days=11,
    )

    record = _register(tmp_path / "experiments.jsonl", ranking, baseline_scope="focus")

    assert record["baseline_vpd"] == 2.0
    assert record["baseline_basis"] == "source=yt-vpd-rank; scope=theme:focus; n=2; median=2.0; min_age_days=11"


def test_unknown_theme_scope_is_rejected_before_live_ranking(tmp_path) -> None:
    calls = 0

    def loader() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _ranking([_item("a", 1), _item("b", 2)])

    with pytest.raises(ValidationError, match="baseline_scope theme"):
        cli.register_experiment(
            lever="thumbnail",
            target="next",
            change="old -> new",
            hypothesis_source="insight-id",
            baseline_scope="missing",
            experiments_path=tmp_path / "experiments.jsonl",
            today=TODAY,
            ranking_loader=loader,
            skill_config=_config(),
            theme_keywords={},
        )
    assert calls == 0


@pytest.mark.parametrize("lever", ["thumbnail,title", "thumbnail, title", "", "   "])
def test_multiple_comma_or_blank_lever_is_rejected_before_api_and_file_change(tmp_path, lever: str) -> None:
    path = tmp_path / "experiments.jsonl"
    path.write_bytes(b"sentinel")
    calls = 0

    def loader() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _ranking([_item("a", 1), _item("b", 2)])

    with pytest.raises(ValidationError, match="lever"):
        cli.register_experiment(
            lever=lever,
            target="next",
            change="old -> new",
            hypothesis_source="insight-id",
            baseline_scope="all",
            experiments_path=path,
            today=TODAY,
            ranking_loader=loader,
            skill_config=_config(),
            theme_keywords={},
        )

    assert calls == 0
    assert path.read_bytes() == b"sentinel"


def test_repeated_lever_option_exits_nonzero_before_live_ranking(monkeypatch) -> None:
    calls = 0

    def loader(**_kwargs) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _ranking([_item("a", 1), _item("b", 2)])

    monkeypatch.setattr(cli.vpd_rank, "_load_ranking", loader)
    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "register",
                "--lever",
                "thumbnail",
                "--lever",
                "title",
                "--target",
                "next",
                "--change",
                "old -> new",
                "--hypothesis-source",
                "insight-id",
            ]
        )
    assert raised.value.code == 2
    assert calls == 0


@pytest.mark.parametrize("field", ["target", "change", "hypothesis_source"])
def test_required_strings_reject_blank_before_api(tmp_path, field: str) -> None:
    values = {"target": "next", "change": "old -> new", "hypothesis_source": "insight-id"}
    values[field] = "  "
    calls = 0

    def loader() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _ranking([_item("a", 1), _item("b", 2)])

    with pytest.raises(ValidationError, match=field):
        cli.register_experiment(
            lever="thumbnail",
            baseline_scope="all",
            experiments_path=tmp_path / "experiments.jsonl",
            today=TODAY,
            ranking_loader=loader,
            skill_config=_config(),
            theme_keywords={},
            **values,
        )
    assert calls == 0


@pytest.mark.parametrize(
    "content, message",
    [
        (b"not json\n", "JSON"),
        (b'{"schema_version":1}\n', "schema"),
        (
            b'{"schema_version":1,"id":"same","registered_date":"2026-08-12","lever":"title",'
            b'"change":"a","hypothesis_source":"h","target":"one","baseline_vpd":1,'
            b'"baseline_basis":"b","judge_after_days":1,"status":"pending"}\n'
            b'{"schema_version":1,"id":"same","registered_date":"2026-08-12","lever":"topic",'
            b'"change":"b","hypothesis_source":"h","target":"two","baseline_vpd":1,'
            b'"baseline_basis":"b","judge_after_days":1,"status":"pending"}\n',
            "重複",
        ),
    ],
)
def test_invalid_existing_jsonl_fails_before_api_and_preserves_bytes(tmp_path, content: bytes, message: str) -> None:
    path = tmp_path / "experiments.jsonl"
    path.write_bytes(content)
    calls = 0

    def loader() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _ranking([_item("a", 1), _item("b", 2)])

    with pytest.raises(ValidationError, match=message):
        _register_with_loader(path, loader)

    assert calls == 0
    assert path.read_bytes() == content


def test_pending_target_fails_before_api_and_preserves_bytes(tmp_path) -> None:
    path = tmp_path / "experiments.jsonl"
    first = _register(path, _ranking([_item("a", 1), _item("b", 2)]))
    before = path.read_bytes()
    calls = 0

    def loader() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _ranking([_item("a", 1), _item("b", 2)])

    with pytest.raises(ValidationError, match="pending"):
        _register_with_loader(path, loader, target=str(first["target"]))
    assert calls == 0
    assert path.read_bytes() == before


def test_live_ranking_loader_is_called_exactly_once_and_old_bytes_stay_prefix(tmp_path) -> None:
    path = tmp_path / "experiments.jsonl"
    _register(path, _ranking([_item("a", 1), _item("b", 2)]), target="first")
    prefix = path.read_bytes()
    calls = 0

    def loader() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _ranking([_item("a", 2), _item("b", 4)])

    _register_with_loader(path, loader, target="second")

    assert calls == 1
    assert path.read_bytes().startswith(prefix)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_replace_failure_preserves_original_bytes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "experiments.jsonl"
    _register(path, _ranking([_item("a", 1), _item("b", 2)]), target="first")
    before = path.read_bytes()
    monkeypatch.setattr(cli.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))

    with pytest.raises(OSError, match="replace failed"):
        _register(path, _ranking([_item("a", 1), _item("b", 2)]), target="second")

    assert path.read_bytes() == before


@pytest.mark.parametrize("judge_after_days", [True, 0, -1, 1.5, "7"])
def test_invalid_judge_after_days_fails_without_writing(tmp_path, judge_after_days: object) -> None:
    path = tmp_path / "experiments.jsonl"
    with pytest.raises(ValidationError, match="judge_after_days"):
        cli.register_experiment(
            lever="thumbnail",
            target="next",
            change="old -> new",
            hypothesis_source="insight-id",
            baseline_scope="all",
            experiments_path=path,
            today=TODAY,
            ranking_loader=lambda: _ranking([_item("a", 1), _item("b", 2)]),
            skill_config=_config(judge_after_days=judge_after_days),
            theme_keywords={},
        )
    assert not path.exists()


@pytest.mark.parametrize("baseline", [float("nan"), float("inf"), -1.0, True])
def test_invalid_baseline_values_fail_without_writing(tmp_path, baseline: object) -> None:
    path = tmp_path / "experiments.jsonl"
    with pytest.raises(ValidationError, match="vpd"):
        _register(path, _ranking([_item("a", baseline), _item("b", 2)]))
    assert not path.exists()


@pytest.mark.parametrize(
    "field, value",
    [
        ("registered_date", "2026-02-30"),
        ("baseline_vpd", float("nan")),
        ("baseline_vpd", -1),
        ("baseline_vpd", True),
        ("judge_after_days", True),
        ("judge_after_days", 0),
        ("status", "complete"),
        ("change", "   "),
    ],
)
def test_schema_rejects_invalid_dates_numbers_status_and_blank_strings(field: str, value: object) -> None:
    schema, insights_schema = cli.load_schema()
    record = {
        "schema_version": 1,
        "id": "20260813-thumbnail-next",
        "registered_date": "2026-08-13",
        "lever": "thumbnail",
        "change": "old -> new",
        "hypothesis_source": "insight-id",
        "target": "next",
        "baseline_vpd": 1.0,
        "baseline_basis": "source=yt-vpd-rank; scope=all; n=2; median=1.0; min_age_days=7",
        "judge_after_days": 14,
        "status": "pending",
    }
    record[field] = value

    assert cli.validate_entry(record, schema, insights_schema)


def test_schema_rejects_additional_property_and_reuses_insights_lever_enum() -> None:
    schema, insights_schema = cli.load_schema()
    properties = schema["properties"]
    assert properties["lever"] == {"$ref": "insights-entry.schema.json#/properties/lever"}
    record = {
        "schema_version": 1,
        "id": "20260813-thumbnail-next",
        "registered_date": "2026-08-13",
        "lever": "thumbnail",
        "change": "old -> new",
        "hypothesis_source": "insight-id",
        "target": "next",
        "baseline_vpd": 1.0,
        "baseline_basis": "basis",
        "judge_after_days": 14,
        "status": "pending",
        "unexpected": "value",
    }

    assert any("未知のキー" in error for error in cli.validate_entry(record, schema, insights_schema))


def _register_with_loader(path: Path, loader, *, target: str = "next") -> dict[str, object]:
    return cli.register_experiment(
        lever="thumbnail",
        target=target,
        change="old -> new",
        hypothesis_source="insight-id",
        baseline_scope="all",
        experiments_path=path,
        today=TODAY,
        ranking_loader=loader,
        skill_config=_config(),
        theme_keywords={},
    )
