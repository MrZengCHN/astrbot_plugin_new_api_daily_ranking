import aiohttp

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

RANKING_TMPL = '''
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 30px 40px; background: #fff; min-width: 600px;">
  <h2 style="margin: 0 0 4px 0; font-size: 24px; color: #333;">用户消耗排行</h2>
  <p style="margin: 0 0 20px 0; font-size: 14px; color: #888;">{{ date }} &nbsp; 总计：${{ "%.2f"|format(total_usd) }}</p>
  <div style="border-left: 3px solid #333; padding-left: 0;">
    {% for item in items %}
    <div style="display: flex; align-items: center; margin-bottom: 8px; padding-left: 12px;">
      <span style="width: 100px; font-size: 14px; color: #555; flex-shrink: 0; text-align: right; padding-right: 12px;">{{ item.username }}</span>
      <div style="height: 28px; background: {{ colors[loop.index0 % colors|length] }}; width: {{ item.percent }}%; border-radius: 0 4px 4px 0; min-width: 4px;"></div>
      <span style="margin-left: 8px; font-size: 14px; color: {{ colors[loop.index0 % colors|length] }}; font-weight: 500;">${{ "%.2f"|format(item.usd) }}</span>
    </div>
    {% endfor %}
  </div>
</div>
'''

BAR_COLORS = ["#4285f4", "#ea4335", "#34a853", "#fbbc04", "#9c27b0", "#e91e63", "#00bcd4", "#ff5722", "#673ab7", "#009688"]


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
            img_url = await self._render_ranking_image(date, items, total_usd)
            yield event.image_result(img_url)

    async def _render_ranking_image(self, date: str, items: list, total_usd: float) -> str:
        if not items:
            return await self.html_render(RANKING_TMPL, {"date": date, "total_usd": 0, "items": [], "colors": BAR_COLORS})

        max_usd = max(item["usd"] for item in items)
        render_items = []
        for item in items:
            percent = (item["usd"] / max_usd * 100) if max_usd > 0 else 0
            render_items.append({
                "username": item["username"],
                "usd": item["usd"],
                "percent": percent,
            })

        return await self.html_render(RANKING_TMPL, {
            "date": date,
            "total_usd": total_usd,
            "items": render_items,
            "colors": BAR_COLORS,
        })

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
