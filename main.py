from datetime import date

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


@register("new_api_daily_ranking", "MrZengCHN", "newApi每日排行查询", "1.0.0")
class NewApiDailyRankingPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

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

        url = self.config.get(
            "pricing_api_url", "https://vibebabo.com/api/pricing"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        yield event.plain_result(
                            f"请求倍率接口失败，状态码: {resp.status}"
                        )
                        return
                    data = await resp.json()
        except Exception as e:
            logger.error(f"请求倍率接口异常: {e}")
            yield event.plain_result(f"请求倍率接口异常: {e}")
            return

        if not data.get("success"):
            yield event.plain_result(
                f"请求倍率接口失败: {data.get('message', '未知错误')}"
            )
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

    @filter.command("分组倍率")
    async def query_group_pricing(self, event: AstrMessageEvent):
        """查看中转站全部分组倍率。

        Args:
            event: 当前消息事件。

        Yields:
            MessageEventResult: 分组倍率查询结果。
        """
        url = self.config.get(
            "pricing_api_url", "https://vibebabo.com/api/pricing"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        yield event.plain_result(
                            f"请求倍率接口失败，状态码: {resp.status}"
                        )
                        return
                    data = await resp.json()
        except Exception as e:
            logger.error(f"请求倍率接口异常: {e}")
            yield event.plain_result(f"请求倍率接口异常: {e}")
            return

        if not data.get("success"):
            yield event.plain_result(
                f"请求倍率接口失败: {data.get('message', '未知错误')}"
            )
            return

        group_ratio = data.get("group_ratio", {})
        if not group_ratio:
            yield event.plain_result("📊 分组倍率\n\n暂无数据")
            return

        lines = ["📊 分组倍率"]
        for group, ratio in group_ratio.items():
            lines.append(f"{group}: {ratio:g}x")
        yield event.plain_result("\n".join(lines))
