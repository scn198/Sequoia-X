"""微信通知模块：通过 PushPlus 将多策略选股结果合并为一条消息推送。"""

from datetime import date

import requests

from sequoia_x.core.config import Settings
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)

PUSHPLUS_URL = "https://www.pushplus.plus/send"
MAX_PER_STRATEGY = 10


class WeChatNotifier:
    """PushPlus 微信推送器（替代飞书）。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _to_xueqiu_code(code: str) -> str:
        """将纯数字代码转为雪球格式：6开头→SH，4/8开头→BJ，其余→SZ。"""
        if code.startswith("6"):
            return f"SH{code}"
        elif code.startswith(("4", "8")):
            return f"BJ{code}"
        return f"SZ{code}"

    @staticmethod
    def _get_stock_names(symbols: list[str]) -> dict[str, str]:
        """通过 baostock 一次性查询全部股票名称，返回 {code: name}。"""
        if not symbols:
            return {}
        import baostock as bs

        bs.login()
        mapping: dict[str, str] = {}
        try:
            for code in symbols:
                prefix = "sh" if code.startswith(("6", "9")) else "sz"
                rs = bs.query_stock_basic(code=f"{prefix}.{code}")
                while rs.next():
                    row = rs.get_row_data()
                    mapping[code] = row[1]
        finally:
            bs.logout()
        return mapping

    def _build_markdown(self, grouped: dict[str, list[str]]) -> tuple[str, str]:
        """把 {策略: [代码]} 拼成一条 markdown 消息。"""
        today = date.today().strftime("%Y-%m-%d")
        all_codes = sorted({c for codes in grouped.values() for c in codes})
        names = self._get_stock_names(all_codes)

        lines = [
            f"**日期：** {today}",
            f"**命中策略：** {len(grouped)} 个 ｜ **涉及个股：** {len(all_codes)} 只",
            "",
        ]

        for strategy, codes in grouped.items():
            lines.append(f"#### {strategy}（{len(codes)} 只）")
            for code in codes[:MAX_PER_STRATEGY]:
                xq = self._to_xueqiu_code(code)
                name = names.get(code, code)
                lines.append(f"- [{name}](https://xueqiu.com/S/{xq})")
            if len(codes) > MAX_PER_STRATEGY:
                lines.append(f"- …… 另有 {len(codes) - MAX_PER_STRATEGY} 只")
            lines.append("")

        title = f"Sequoia-X 选股 {today}｜{len(all_codes)} 只"
        return title, "\n".join(lines).strip()

    def send(self, grouped: dict[str, list[str]]) -> None:
        """推送合并后的选股结果到微信。"""
        token = getattr(self.settings, "pushplus_token", "")
        if not token:
            logger.error("未配置 PUSHPLUS_TOKEN，跳过推送")
            return
        if not grouped:
            logger.info("无选股结果，跳过推送")
            return

        title, content = self._build_markdown(grouped)
        payload = {
            "token": token,
            "title": title[:100],
            "content": content,
            "template": "markdown",
        }

        try:
            resp = requests.post(PUSHPLUS_URL, json=payload, timeout=20)
            data = resp.json()
            if resp.status_code != 200 or data.get("code") != 200:
                logger.error(f"微信推送失败 HTTP={resp.status_code} 响应={data}")
            else:
                logger.info(f"微信推送成功，共 {len(grouped)} 个策略")
        except requests.RequestException as exc:
            logger.error(f"微信推送请求异常：{exc}")
