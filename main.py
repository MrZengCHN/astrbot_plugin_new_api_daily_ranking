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

    @filter.command("查看排名")
    async def query_ranking(self, event: AstrMessageEvent, username: str = None):
        """查看每日消费排行榜，可指定用户名查询"""
        api_base_url = self.config.get("api_base_url", "https://docs.mrzengchn.com").rstrip("/")
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

    @filter.command("签到排行")
    async def query_checkin_ranking(self, event: AstrMessageEvent, query_date: str = None):
        """查看每日签到排行榜，可指定日期查询"""
        api_base_url = self.config.get("api_base_url", "https://docs.mrzengchn.com").rstrip("/")
        default_limit = self.config.get("default_limit", 10)
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
            checkin_count = item["checkinCount"]
            if prefix:
                lines.append(f"{prefix} {name} - {amount:.6f} ({checkin_count}次签到)")
            else:
                lines.append(f"{rank}. {name} - {amount:.6f} ({checkin_count}次签到)")

        lines.append(f"\n💰 签到总额: {total_amount:.6f}")
        return "\n".join(lines)
