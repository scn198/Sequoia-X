"""用并行增量接口快速初始化近 N 天数据（绕过单线程 backfill）。

原理：
    sync_today_bulk() 会从每只股票的 MAX(date)+1 一直拉到今天，且是 8 进程并行。
    只要在库里给每只股票预置一条 N 天前的占位行，这个并行接口就会去拉这段时间，
    速度比单线程的 backfill() 快得多。

    拉取完成后，把占位行（close=0）删掉，避免污染策略计算。

用法：
    SEED_DAYS=60 python bootstrap.py
"""
import os
import sqlite3
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from sequoia_x.core.config import get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine

logger = get_logger(__name__)

SEED_DAYS = int(os.environ.get("SEED_DAYS", "60"))


def main() -> None:
    settings = get_settings()
    engine = DataEngine(settings)

    logger.info("获取全市场股票列表…")
    symbols = engine.get_all_symbols()
    if not symbols:
        raise SystemExit("股票列表为空，退出")
    logger.info(f"共 {len(symbols)} 只")

    seed_date = (date.today() - timedelta(days=SEED_DAYS)).strftime("%Y-%m-%d")
    logger.info(f"写入占位行 date={seed_date}，共 {len(symbols)} 条")

    with sqlite3.connect(settings.db_path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO stock_daily "
            "(symbol, date, open, high, low, close, volume, turnover) "
            "VALUES (?, ?, 0, 0, 0, 0, 0, 0)",
            [(s, seed_date) for s in symbols],
        )
        conn.commit()

    logger.info("开始 8 进程并行拉取（这是主要耗时，请耐心等待）…")
    count = engine.sync_today_bulk()
    logger.info(f"写入 {count} 条数据")

    with sqlite3.connect(settings.db_path) as conn:
        deleted = conn.execute("DELETE FROM stock_daily WHERE close = 0").rowcount
        conn.commit()
    logger.info(f"清理占位行 {deleted} 条")


if __name__ == "__main__":
    main()
