from youtube_automation.domains.channel_readiness import evaluate_ttp_wf_new_readiness


def test_ttp_readiness_reports_missing_analytics_config(tmp_path) -> None:
    result = evaluate_ttp_wf_new_readiness(tmp_path)

    assert result.status == "warn"
    assert result.message == (
        "config/channel/analytics.json 未生成。/wf-new 接続前に承認済み TTP 対象の保存が必要; "
        "docs/channel/personas/persona-definition.md 未作成"
    )
    assert result.next_action == {
        "kind": "human",
        "instructions": (
            "/setup --channel Step 4 で config を生成し、Step 5 以降で承認済み TTP 対象を "
            "config/channel/analytics.json::benchmark.channels に保存してください。"
            "ペルソナの不足はユーザー承認済み例外にせず、/channel-strategy --persona で最終 "
            "persona-definition.md を更新してください"
        ),
    }
