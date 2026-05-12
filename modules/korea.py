"""Korea market data collection."""

from __future__ import annotations

import pandas as pd

from naver_scraper import (
    fetch_exchange_rates,
    fetch_global_indicators,
    fetch_sector_top10,
)


def collect(include_krx: bool = True, include_news: bool = True) -> dict:
    data = {
        "global_indicators": fetch_global_indicators(),
        "sector_top10": fetch_sector_top10(),
        "exchange": fetch_exchange_rates(),
        "investor": {},
        "news": {},
    }

    if include_krx:
        try:
            from krx_collector import collect_all_krx

            data["investor"] = collect_all_krx()
        except Exception as exc:
            data["investor_error"] = str(exc)

    if include_news:
        try:
            from news_scraper import collect_all_news

            data["news"] = collect_all_news()
        except Exception as exc:
            data["news_error"] = str(exc)

    return data


def summarize_for_prompt(data: dict, max_rows: int = 12) -> str:
    lines = ["[한국]"]
    column_map = {
        "global_indicators": ["종목명", "현재가", "전일대비", "등락률(%)", "분류"],
        "sector_top10": ["업종명", "등락률(%)", "시가총액(조)", "거래대금(억)", "주도주"],
        "exchange": ["통화", "매매기준율", "전일대비", "등락률(%)"],
    }
    for key in ["global_indicators", "sector_top10", "exchange"]:
        value = data.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            cols = [col for col in column_map[key] if col in value.columns]
            compact = value[cols] if cols else value
            lines.append(f"\n<{key}>\n{compact.head(max_rows).to_string(index=False)}")

    investor = data.get("investor") or {}
    for key, value in investor.items():
        if isinstance(value, pd.DataFrame) and not value.empty:
            lines.append(f"\n<investor:{key}>\n{value.head(5).to_string(index=False)}")

    news = data.get("news") or {}
    for section in ["naver_market", "naver_world", "naver_stock"]:
        articles = news.get(section) or []
        if articles:
            lines.append(f"\n<news:{section}>")
            for article in articles[:8]:
                source = article.get("source", "")
                suffix = f" [{source}]" if source else ""
                lines.append(f"- {article.get('title', '')}{suffix}")

    topics = news.get("topics") or {}
    for topic, articles in list(topics.items())[:8]:
        if not articles:
            continue
        lines.append(f"\n<topic:{topic}>")
        for article in articles[:4]:
            lines.append(f"- {article.get('title', '')}")

    for err_key in ["investor_error", "news_error"]:
        if data.get(err_key):
            lines.append(f"\n<{err_key}> {data[err_key]}")

    return "\n".join(lines)
