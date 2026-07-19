import asyncio
import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest

os.environ.setdefault("ASTRBOT_ROOT", str(Path(__file__).resolve().parents[4]))

PLUGIN_MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"
PLUGIN_SPEC = importlib.util.spec_from_file_location(
    "astrbot_plugin_new_api_daily_ranking_main", PLUGIN_MAIN_PATH
)
assert PLUGIN_SPEC and PLUGIN_SPEC.loader
PLUGIN_MODULE = importlib.util.module_from_spec(PLUGIN_SPEC)
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)
NewApiDailyRankingPlugin = PLUGIN_MODULE.NewApiDailyRankingPlugin


@pytest.mark.asyncio
async def test_initialize_starts_only_valid_unique_third_party_channels():
    context = MagicMock()
    config = {
        "notify_interval_seconds": 0,
        "third_party_notify_interval_seconds": 60,
        "third_party_notify_platform_id": "third-party",
        "third_party_notify_group_ids": "100,100\n200",
        "third_party_notify_user_ids": "300",
        "third_party_pricing_channels": [
            {
                "__template_key": "channel",
                "name": "Alpha",
                "pricing_api_url": "https://alpha.example/api/pricing",
            },
            {
                "__template_key": "channel",
                "name": "Duplicate",
                "pricing_api_url": "https://alpha.example/api/pricing",
            },
            {
                "__template_key": "channel",
                "name": "Beta",
                "pricing_api_url": "https://beta.example/api/pricing",
            },
            {
                "__template_key": "channel",
                "name": "",
                "pricing_api_url": "https://invalid.example/api/pricing",
            },
        ],
    }
    plugin = NewApiDailyRankingPlugin(context, config)
    plugin._ratio_notify_loop = AsyncMock()

    await plugin.initialize()
    await asyncio.sleep(0)

    assert plugin._ratio_notify_task is None
    assert len(plugin._third_party_ratio_notify_tasks) == 2
    assert plugin._ratio_notify_loop.await_args_list == [
        call(
            60,
            "third-party",
            ["100", "200"],
            ["300"],
            pricing_url="https://alpha.example/api/pricing",
            source_name="Alpha",
            notify_initial=True,
        ),
        call(
            60,
            "third-party",
            ["100", "200"],
            ["300"],
            pricing_url="https://beta.example/api/pricing",
            source_name="Beta",
            notify_initial=True,
        ),
    ]

    await plugin.terminate()


@pytest.mark.asyncio
async def test_third_party_first_poll_sends_full_sorted_snapshot(monkeypatch):
    context = MagicMock()
    context.send_message = AsyncMock(return_value=True)
    plugin = NewApiDailyRankingPlugin(context, {})
    plugin._get_pricing_data = AsyncMock(
        return_value=(
            {"success": True, "group_ratio": {"zeta": 2, "alpha": "1.5"}},
            None,
        )
    )

    async def stop_after_first_poll(_interval):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_first_poll)

    with pytest.raises(asyncio.CancelledError):
        await plugin._ratio_notify_loop(
            60,
            "third-party",
            ["100"],
            ["200"],
            pricing_url="https://alpha.example/api/pricing",
            source_name="Alpha",
            notify_initial=True,
        )

    plugin._get_pricing_data.assert_awaited_once_with(
        "https://alpha.example/api/pricing"
    )
    assert context.send_message.await_count == 2
    assert context.send_message.await_args_list[0].args[0] == (
        "third-party:GroupMessage:100"
    )
    assert context.send_message.await_args_list[1].args[0] == (
        "third-party:FriendMessage:200"
    )
    message = context.send_message.await_args_list[0].args[1].get_plain_text()
    assert message == (
        "📢 第三方渠道分组倍率初始化\n"
        "渠道: Alpha\n"
        "Pricing: https://alpha.example/api/pricing\n"
        "alpha: 1.5x\n"
        "zeta: 2x"
    )


@pytest.mark.asyncio
async def test_primary_listener_keeps_baseline_without_initial_notification(monkeypatch):
    context = MagicMock()
    context.send_message = AsyncMock(return_value=True)
    plugin = NewApiDailyRankingPlugin(context, {})
    plugin._get_pricing_data = AsyncMock(
        side_effect=[
            ({"success": True, "group_ratio": {"default": 1}}, None),
            (
                {
                    "success": True,
                    "group_ratio": {"default": 2, "vip": 0.5},
                },
                None,
            ),
        ]
    )
    sleep_calls = 0

    async def stop_after_second_poll(_interval):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_second_poll)

    with pytest.raises(asyncio.CancelledError):
        await plugin._ratio_notify_loop(60, "default", ["100"], [])

    context.send_message.assert_awaited_once()
    message = context.send_message.await_args.args[1].get_plain_text()
    assert message == (
        "📢 分组倍率发生变化\n"
        "default: 1x -> 2x\n"
        "vip: 新增 0.5x"
    )


@pytest.mark.asyncio
async def test_third_party_listener_reports_added_removed_and_changed_groups(
    monkeypatch,
):
    context = MagicMock()
    context.send_message = AsyncMock(return_value=True)
    plugin = NewApiDailyRankingPlugin(context, {})
    plugin._get_pricing_data = AsyncMock(
        side_effect=[
            (
                {"success": True, "group_ratio": {"alpha": 1, "beta": 2}},
                None,
            ),
            (
                {"success": True, "group_ratio": {"alpha": 1.5, "gamma": 3}},
                None,
            ),
        ]
    )
    sleep_calls = 0

    async def stop_after_second_poll(_interval):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_second_poll)

    with pytest.raises(asyncio.CancelledError):
        await plugin._ratio_notify_loop(
            60,
            "third-party",
            ["100"],
            [],
            pricing_url="https://alpha.example/api/pricing",
            source_name="Alpha",
            notify_initial=True,
        )

    assert context.send_message.await_count == 2
    change_message = context.send_message.await_args_list[1].args[1].get_plain_text()
    assert change_message == (
        "📢 第三方渠道分组倍率发生变化\n"
        "渠道: Alpha\n"
        "Pricing: https://alpha.example/api/pricing\n"
        "alpha: 1x -> 1.5x\n"
        "beta: 2x -> 已移除\n"
        "gamma: 新增 3x"
    )


@pytest.mark.asyncio
async def test_invalid_third_party_response_does_not_set_the_initial_baseline(
    monkeypatch,
):
    context = MagicMock()
    context.send_message = AsyncMock(return_value=True)
    plugin = NewApiDailyRankingPlugin(context, {})
    plugin._get_pricing_data = AsyncMock(
        side_effect=[
            ({"success": True, "group_ratio": ["invalid"]}, None),
            ({"success": True, "group_ratio": {"default": 1}}, None),
        ]
    )
    sleep_calls = 0

    async def stop_after_second_poll(_interval):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_second_poll)

    with pytest.raises(asyncio.CancelledError):
        await plugin._ratio_notify_loop(
            60,
            "third-party",
            ["100"],
            [],
            pricing_url="https://alpha.example/api/pricing",
            source_name="Alpha",
            notify_initial=True,
        )

    context.send_message.assert_awaited_once()
    message = context.send_message.await_args.args[1].get_plain_text()
    assert message.endswith("default: 1x")


@pytest.mark.asyncio
async def test_terminate_cancels_primary_and_third_party_tasks():
    context = MagicMock()
    plugin = NewApiDailyRankingPlugin(context, {})
    blocker = asyncio.Event()

    async def wait_forever():
        await blocker.wait()

    plugin._ratio_notify_task = asyncio.create_task(wait_forever())
    plugin._third_party_ratio_notify_tasks = [
        asyncio.create_task(wait_forever()),
        asyncio.create_task(wait_forever()),
    ]
    tasks = [plugin._ratio_notify_task, *plugin._third_party_ratio_notify_tasks]
    await asyncio.sleep(0)

    await plugin.terminate()

    assert all(task.cancelled() for task in tasks)
    assert plugin._ratio_notify_task is None
    assert plugin._third_party_ratio_notify_tasks == []
