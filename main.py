import aiohttp

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig


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
            prefix = medal.get(rank, "")
            name = item["username"]
            usd = item["usd"]
            req_count = item["requestCount"]
            lines.append(f"{prefix} {name} - ${usd:.2f} ({req_count}次请求)" if prefix else f"{rank}. {name} - ${usd:.2f} ({req_count}次请求)")

        lines.append(f"\n💰 总消费: ${total_usd:.2f}")
        return "\n".join(lines)

    def _format_user_ranking(self, username: str, date: str, items: list) -> str:
        for item in items:
            if item["username"].lower() == username.lower():
                rank = item["rank"]
                usd = item["usd"]
                req_count = item["requestCount"]
                return (
                    f"📊 用户 \"{item['username']}\" 的排名信息 ({date})\n\n"
                    f"排名: 第{rank}名\n"
                    f"消费: ${usd:.2f}\n"
                    f"请求次数: {req_count}次"
                )
        return f"📊 用户 \"{username}\" 未在当日排行榜中上榜 ({date})"
