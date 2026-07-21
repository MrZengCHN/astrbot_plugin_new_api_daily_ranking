import asyncio
from datetime import date
from urllib.parse import urljoin

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register


@register("new_api_daily_ranking", "MrZengCHN", "newApi每日排行查询", "1.0.0")
class NewApiDailyRankingPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._ratio_notify_task: asyncio.Task | None = None
        self._third_party_ratio_notify_tasks: list[asyncio.Task] = []

    async def initialize(self) -> None:
        """Start configured primary and third-party group-ratio polling tasks."""
        interval = int(self.config.get("notify_interval_seconds", 300))
        platform_id = str(self.config.get("notify_platform_id") or "default").strip()
        group_ids = list(
            dict.fromkeys(
                item.strip()
                for item in str(self.config.get("notify_group_ids") or "")
                .replace("\n", ",")
                .split(",")
                if item.strip()
            )
        )
        user_ids = list(
            dict.fromkeys(
                item.strip()
                for item in str(self.config.get("notify_user_ids") or "")
                .replace("\n", ",")
                .split(",")
                if item.strip()
            )
        )

        if interval <= 0 or not platform_id or not (group_ids or user_ids):
            logger.info("分组倍率主动通知未启用：未配置有效目标或检测间隔。")
        else:
            self._ratio_notify_task = asyncio.create_task(
                self._ratio_notify_loop(interval, platform_id, group_ids, user_ids)
            )

        third_party_interval = int(
            self.config.get("third_party_notify_interval_seconds", 300)
        )
        third_party_platform_id = str(
            self.config.get("third_party_notify_platform_id") or "default"
        ).strip()
        third_party_group_ids = list(
            dict.fromkeys(
                item.strip()
                for item in str(self.config.get("third_party_notify_group_ids") or "")
                .replace("\n", ",")
                .split(",")
                if item.strip()
            )
        )
        third_party_user_ids = list(
            dict.fromkeys(
                item.strip()
                for item in str(self.config.get("third_party_notify_user_ids") or "")
                .replace("\n", ",")
                .split(",")
                if item.strip()
            )
        )

        raw_channels = self.config.get("third_party_pricing_channels") or []
        if not isinstance(raw_channels, list):
            logger.warning("第三方渠道倍率监听配置无效：渠道配置应为列表。")
            raw_channels = []

        channels: list[tuple[str, str, str, str]] = []
        seen_urls: set[str] = set()
        for channel in raw_channels:
            if not isinstance(channel, dict):
                logger.warning("第三方渠道倍率监听已跳过无效渠道配置。")
                continue
            name = str(channel.get("name") or "").strip()
            pricing_url = str(channel.get("pricing_api_url") or "").strip()
            if not name or not pricing_url:
                logger.warning("第三方渠道倍率监听已跳过缺少名称或 URL 的配置。")
                continue
            if pricing_url in seen_urls:
                logger.warning(f"第三方渠道倍率监听已跳过重复 URL: {pricing_url}")
                continue
            new_api_user = str(channel.get("new_api_user") or "").strip()
            authorization_token = str(
                channel.get("authorization_token") or ""
            ).strip()
            seen_urls.add(pricing_url)
            channels.append(
                (name, pricing_url, new_api_user, authorization_token)
            )

        if (
            third_party_interval <= 0
            or not third_party_platform_id
            or not (third_party_group_ids or third_party_user_ids)
            or not channels
        ):
            logger.info(
                "第三方渠道分组倍率主动通知未启用：未配置有效渠道、目标或检测间隔。"
            )
            return

        for name, pricing_url, new_api_user, authorization_token in channels:
            self._third_party_ratio_notify_tasks.append(
                asyncio.create_task(
                    self._ratio_notify_loop(
                        third_party_interval,
                        third_party_platform_id,
                        third_party_group_ids,
                        third_party_user_ids,
                        pricing_url=pricing_url,
                        source_name=name,
                        notify_initial=True,
                        new_api_user=new_api_user,
                        authorization_token=authorization_token,
                    )
                )
            )

    async def terminate(self) -> None:
        """Stop all group-ratio polling tasks when the plugin is terminated."""
        tasks = list(self._third_party_ratio_notify_tasks)
        if self._ratio_notify_task is not None:
            tasks.insert(0, self._ratio_notify_task)
        if not tasks:
            return

        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._ratio_notify_task = None
            self._third_party_ratio_notify_tasks = []

    async def _ratio_notify_loop(
        self,
        interval: int,
        platform_id: str,
        group_ids: list[str],
        user_ids: list[str],
        pricing_url: str | None = None,
        source_name: str | None = None,
        notify_initial: bool = False,
        new_api_user: str | None = None,
        authorization_token: str | None = None,
    ) -> None:
        """Poll group ratios and notify configured OneBot sessions.

        Args:
            interval: Polling interval in seconds.
            platform_id: OneBot platform instance ID used for notifications.
            group_ids: QQ group IDs that receive notifications.
            user_ids: QQ user IDs that receive notifications.
            pricing_url: Pricing endpoint override for a third-party channel.
            source_name: Third-party channel name shown in notifications.
            notify_initial: Whether to notify the first successful snapshot.
            new_api_user: Optional new-api-user header for a third-party channel.
            authorization_token: Optional bearer token for a third-party channel.
        """
        previous_ratios: dict[str, float] | None = None
        log_prefix = (
            f"第三方渠道分组倍率主动通知[{source_name} | {pricing_url}]"
            if source_name and pricing_url
            else "分组倍率主动通知"
        )
        while True:
            if new_api_user or authorization_token:
                data, error = await self._get_pricing_data(
                    pricing_url, new_api_user, authorization_token
                )
            else:
                data, error = await self._get_pricing_data(pricing_url)
            if error:
                logger.warning(f"{log_prefix}检测失败: {error}")
            else:
                raw_ratios = data.get("group_ratio")
                if not isinstance(raw_ratios, dict):
                    logger.warning(f"{log_prefix}检测失败: group_ratio 格式无效")
                else:
                    try:
                        current_ratios = {
                            str(group): float(ratio)
                            for group, ratio in raw_ratios.items()
                        }
                    except (TypeError, ValueError):
                        logger.warning(
                            f"{log_prefix}检测失败: group_ratio 包含无效倍率"
                        )
                    else:
                        lines: list[str] | None = None
                        if previous_ratios is None:
                            if notify_initial:
                                lines = [
                                    "📢 第三方渠道分组倍率初始化",
                                    f"渠道: {source_name}",
                                    f"Pricing: {pricing_url}",
                                ]
                                if current_ratios:
                                    for group in sorted(current_ratios):
                                        lines.append(
                                            f"{group}: {current_ratios[group]:g}x"
                                        )
                                else:
                                    lines.append("暂无数据")
                        elif current_ratios != previous_ratios:
                            changed_groups = sorted(
                                set(previous_ratios) | set(current_ratios)
                            )
                            if source_name and pricing_url:
                                lines = [
                                    "📢 第三方渠道分组倍率发生变化",
                                    f"渠道: {source_name}",
                                    f"Pricing: {pricing_url}",
                                ]
                            else:
                                lines = ["📢 分组倍率发生变化"]
                            for group in changed_groups:
                                old_ratio = previous_ratios.get(group)
                                new_ratio = current_ratios.get(group)
                                if old_ratio is not None and old_ratio == new_ratio:
                                    continue
                                if old_ratio is None:
                                    lines.append(f"{group}: 新增 {new_ratio:g}x")
                                elif new_ratio is None:
                                    lines.append(f"{group}: {old_ratio:g}x -> 已移除")
                                else:
                                    lines.append(
                                        f"{group}: {old_ratio:g}x -> {new_ratio:g}x"
                                    )

                        if lines is not None:
                            message = MessageChain().message("\n".join(lines))
                            targets = [
                                (
                                    f"{platform_id}:GroupMessage:{group_id}",
                                    "群聊",
                                    group_id,
                                )
                                for group_id in group_ids
                            ] + [
                                (
                                    f"{platform_id}:FriendMessage:{user_id}",
                                    "私聊",
                                    user_id,
                                )
                                for user_id in user_ids
                            ]
                            for session, target_type, target_id in targets:
                                try:
                                    sent = await self.context.send_message(
                                        session, message
                                    )
                                    if not sent:
                                        logger.warning(
                                            f"{log_prefix}未找到{target_type}平台: {target_id}"
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"{log_prefix}发送到{target_type} {target_id}失败: {e}"
                                    )

                        if previous_ratios is None or current_ratios != previous_ratios:
                            previous_ratios = current_ratios

            await asyncio.sleep(interval)

    @filter.command("查看排名", alias={"排名"})
    async def query_ranking(self, event: AstrMessageEvent, username: str = None):
        """查看每日消费排行榜，可指定用户名查询"""
        api_base_url = self.config.get("api_base_url", "https://docs.vibebabo.com").rstrip("/")
        default_limit = self.config.get("default_limit", 10)

        limit = 100 if username else default_limit
        url = f"{api_base_url}/api/consumption-rankings/daily?limit={limit}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"请求排行榜接口失败，状态码: {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            logger.error(f"请求排行榜接口异常: {e}")
            yield event.plain_result(f"请求排行榜接口异常: {e}")
            return

        date = data.get("date", "未知")
        items = data.get("items", [])

        if username:
            yield event.plain_result(self._format_user_ranking(username, date, items))
        else:
            total_usd = data.get("totalUsd", 0)
            yield event.plain_result(self._format_ranking_list(date, items, total_usd))

    def _format_ranking_list(self, date: str, items: list, total_usd: float) -> str:
        if not items:
            return f"📊 每日消费排行榜 ({date})\n\n暂无数据"

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [f"📊 每日消费排行榜 ({date})\n"]
        for item in items:
            rank = item["rank"]
            prefix = medal.get(rank, f"{rank}.")
            prefix = medal.get(rank, "")
            name = item["username"]
            usd = item["usd"]
            req_count = item["requestCount"]
            lines.append(f"{prefix} {name} - ${usd:.2f} ({req_count}次请求)" if prefix else f"{rank}. {name} - ${usd:.2f} ({req_count}次请求)")

        lines.append(f"\n💰 总消费: ${total_usd:.2f}")
        return "\n".join(lines)

    @filter.command("查看签到排名", alias={"签到"})
    async def query_checkin_ranking(self, event: AstrMessageEvent, query_date: str = None):
        """查看每日签到排行榜，可指定日期查询"""
        api_base_url = self.config.get("api_base_url", "https://docs.vibebabo.com").rstrip("/")
        default_limit = self.config.get("checkin_default_limit", self.config.get("default_limit", 10))
        query_date = query_date or date.today().isoformat()
        url = f"{api_base_url}/api/consumption-rankings/daily-checkins?date={query_date}&limit={default_limit}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"请求签到排行榜接口失败，状态码: {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            logger.error(f"请求签到排行榜接口异常: {e}")
            yield event.plain_result(f"请求签到排行榜接口异常: {e}")
            return

        ranking_date = data.get("date", query_date)
        items = data.get("items", [])
        total_amount = data.get("totalAmount", 0)
        yield event.plain_result(self._format_checkin_ranking_list(ranking_date, items, total_amount))

    def _format_checkin_ranking_list(self, ranking_date: str, items: list, total_amount: float) -> str:
        if not items:
            return f"📊 每日签到排行榜 ({ranking_date})\n\n暂无数据"

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [f"📊 每日签到排行榜 ({ranking_date})\n"]
        for item in items:
            rank = item["rank"]
            prefix = medal.get(rank, "")
            name = item["username"]
            amount = item["amount"]
            if amount > 0:
                amount_text = f"赚到 {amount:.6f}"
            elif amount < 0:
                amount_text = f"血亏 {abs(amount):.6f}"
            else:
                amount_text = f"持平 {amount:.6f}"
            if prefix:
                lines.append(f"{prefix} {name} - {amount_text}")
            else:
                lines.append(f"{rank}. {name} - {amount_text}")

        if total_amount > 0:
            total_amount_text = f"赚到 {total_amount:.6f}"
        elif total_amount < 0:
            total_amount_text = f"血亏 {abs(total_amount):.6f}"
        else:
            total_amount_text = f"持平 {total_amount:.6f}"
        lines.append(f"\n💰 签到总额: {total_amount_text}")
        return "\n".join(lines)

    async def _get_pricing_data(
        self,
        url: str | None = None,
        new_api_user: str | None = None,
        authorization_token: str | None = None,
    ) -> tuple[dict | None, str | None]:
        """请求中转站倍率数据。

        Args:
            url: 指定的倍率接口地址；为空时使用主倍率接口配置。
            new_api_user: 指定接口的 new-api-user 请求头。
            authorization_token: 指定接口的 Bearer 令牌。

        Returns:
            倍率数据和错误信息；请求成功时错误信息为 None。
        """
        if url is None:
            url = self.config.get("pricing_api_url", "https://vibebabo.com/api/pricing")
            new_api_user = self.config.get("pricing_new_api_user")
            authorization_token = self.config.get("pricing_authorization_token")

        headers: dict[str, str] = {}
        new_api_user = str(new_api_user or "").strip()
        authorization_token = str(authorization_token or "").strip()
        if new_api_user:
            headers["new-api-user"] = new_api_user
        if authorization_token:
            headers["Authorization"] = f"Bearer {authorization_token}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers or None,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None, f"请求倍率接口失败，状态码: {resp.status}"
                    data = await resp.json()
        except Exception as e:
            logger.error(f"请求倍率接口异常: {e}")
            return None, f"请求倍率接口异常: {e}"

        if not data.get("success"):
            return None, f"请求倍率接口失败: {data.get('message', '未知错误')}"

        return data, None

    @filter.command("第三方倍率")
    async def query_third_party_pricing(
        self, event: AstrMessageEvent, channel_name: str = None
    ):
        """查询一个或全部第三方渠道的分组倍率。

        Args:
            event: 当前消息事件。
            channel_name: 要查询的渠道名称；为空时查询全部渠道。

        Yields:
            MessageEventResult: 每个第三方渠道各自的倍率查询结果。
        """
        raw_channels = self.config.get("third_party_pricing_channels") or []
        if not isinstance(raw_channels, list):
            raw_channels = []

        channels: list[tuple[str, str, str, str]] = []
        seen_urls: set[str] = set()
        for channel in raw_channels:
            if not isinstance(channel, dict):
                continue
            name = str(channel.get("name") or "").strip()
            pricing_url = str(channel.get("pricing_api_url") or "").strip()
            if not name or not pricing_url or pricing_url in seen_urls:
                continue
            new_api_user = str(channel.get("new_api_user") or "").strip()
            authorization_token = str(
                channel.get("authorization_token") or ""
            ).strip()
            seen_urls.add(pricing_url)
            channels.append(
                (name, pricing_url, new_api_user, authorization_token)
            )

        if channel_name:
            channel_name = channel_name.strip()
            channels = [channel for channel in channels if channel[0] == channel_name]
            if not channels:
                yield event.plain_result(f"未找到第三方渠道：{channel_name}")
                return
        elif not channels:
            yield event.plain_result("未配置第三方渠道倍率接口")
            return

        for name, pricing_url, new_api_user, authorization_token in channels:
            lines = [
                "📊 第三方渠道分组倍率",
                f"渠道: {name}",
                f"Pricing: {pricing_url}",
            ]
            if new_api_user or authorization_token:
                data, error = await self._get_pricing_data(
                    pricing_url, new_api_user, authorization_token
                )
            else:
                data, error = await self._get_pricing_data(pricing_url)
            if error:
                lines.append(error)
                yield event.plain_result("\n".join(lines))
                continue

            raw_ratios = data.get("group_ratio")
            if not isinstance(raw_ratios, dict):
                lines.append("倍率接口返回的 group_ratio 格式无效")
            else:
                try:
                    group_ratio = {
                        str(group): float(ratio) for group, ratio in raw_ratios.items()
                    }
                except (TypeError, ValueError):
                    lines.append("倍率接口返回的 group_ratio 包含无效倍率")
                else:
                    if group_ratio:
                        for group in sorted(group_ratio):
                            lines.append(f"{group}: {group_ratio[group]:g}x")
                    else:
                        lines.append("暂无数据")

            yield event.plain_result("\n".join(lines))

    @filter.command("模型倍率")
    async def query_model_pricing(
        self, event: AstrMessageEvent, model_name: str = None
    ):
        """精确查询指定模型在各分组下的倍率。

        Args:
            event: 当前消息事件。
            model_name: 要精确查询的模型名称。

        Yields:
            MessageEventResult: 模型倍率查询结果。
        """
        if not model_name:
            yield event.plain_result("请指定模型名称，例如：模型倍率 gpt-5.5")
            return

        data, error = await self._get_pricing_data()
        if error:
            yield event.plain_result(error)
            return

        models = [
            item
            for item in data.get("data", [])
            if item.get("model_name") == model_name
        ]
        if not models:
            yield event.plain_result(
                f"未找到模型：{model_name}（模型名称需要精确匹配）"
            )
            return

        group_ratio = data.get("group_ratio", {})
        lines = [f"📊 模型倍率：{model_name}"]
        for item in models:
            groups = item.get("enable_groups") or []
            if not groups:
                lines.append(f"\n{model_name}: 未配置可用分组")
                continue

            for group in groups:
                ratio = group_ratio.get(group)
                if ratio is None:
                    lines.append(f"{model_name}  {group}: 分组倍率未知")
                    continue

                lines.append(f"{model_name}  {group}: {ratio:g}x")

        yield event.plain_result("\n".join(lines))

    @filter.command("模型价格")
    async def query_model_price(
        self, event: AstrMessageEvent, model_name: str = None
    ):
        """精确查询指定模型的基础价格。

        Args:
            event: 当前消息事件。
            model_name: 要精确查询的模型名称。

        Yields:
            MessageEventResult: 模型价格查询结果。
        """
        if not model_name:
            yield event.plain_result("请指定模型名称，例如：模型价格 gpt-5.5")
            return

        data, error = await self._get_pricing_data()
        if error:
            yield event.plain_result(error)
            return

        models = [
            item
            for item in data.get("data", [])
            if item.get("model_name") == model_name
        ]
        if not models:
            yield event.plain_result(
                f"未找到模型：{model_name}（模型名称需要精确匹配）"
            )
            return

        quota_per_unit = None
        if any(
            item.get("quota_type") != 1
            and item.get("billing_mode") != "tiered_expr"
            for item in models
        ):
            pricing_url = self.config.get(
                "pricing_api_url", "https://vibebabo.com/api/pricing"
            )
            status_url = urljoin(pricing_url, "/api/status")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        status_url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status != 200:
                            yield event.plain_result(
                                f"请求系统状态接口失败，状态码: {resp.status}"
                            )
                            return
                        status_data = await resp.json()
            except Exception as e:
                logger.error(f"请求系统状态接口异常: {e}")
                yield event.plain_result(f"请求系统状态接口异常: {e}")
                return

            if not status_data.get("success"):
                yield event.plain_result(
                    f"请求系统状态接口失败: {status_data.get('message', '未知错误')}"
                )
                return

            try:
                quota_per_unit = float(
                    status_data.get("data", {}).get("quota_per_unit")
                )
            except (TypeError, ValueError):
                quota_per_unit = 0
            if quota_per_unit <= 0:
                yield event.plain_result("系统状态接口未返回有效的 quota_per_unit")
                return

        lines = [f"📊 模型价格：{model_name}（未乘分组倍率）"]
        for item in models:
            if item.get("billing_mode") == "tiered_expr":
                lines.append(
                    f"计费表达式: {item.get('billing_expr') or '未配置'}"
                )
                continue

            if item.get("quota_type") == 1:
                lines.append(f"按次价格: ${item.get('model_price', 0):g}/次")
                continue

            input_price = item.get("model_ratio", 0) * 1_000_000 / quota_per_unit
            lines.append(f"输入价格: ${input_price:g}/1M Tokens")
            lines.append(
                f"输出价格: ${input_price * item.get('completion_ratio', 1):g}/1M Tokens"
            )
            if "cache_ratio" in item:
                lines.append(
                    f"缓存价格: ${input_price * item['cache_ratio']:g}/1M Tokens"
                )
            if "create_cache_ratio" in item:
                lines.append(
                    f"写缓存价格: ${input_price * item['create_cache_ratio']:g}/1M Tokens"
                )

        yield event.plain_result("\n".join(lines))

    @filter.command("分组倍率")
    async def query_group_pricing(self, event: AstrMessageEvent):
        """查看中转站全部分组倍率。

        Args:
            event: 当前消息事件。

        Yields:
            MessageEventResult: 分组倍率查询结果。
        """
        data, error = await self._get_pricing_data()
        if error:
            yield event.plain_result(error)
            return

        group_ratio = data.get("group_ratio", {})
        if not group_ratio:
            yield event.plain_result("📊 分组倍率\n\n暂无数据")
            return

        lines = ["📊 分组倍率"]
        for group, ratio in group_ratio.items():
            lines.append(f"{group}: {ratio:g}x")
        yield event.plain_result("\n".join(lines))
