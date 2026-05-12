"""US market data collection."""

from __future__ import annotations

import pandas as pd

from global_market_analyzer import fetch_market_top_stocks
from naver_scraper import fetch_global_indicators
from us_market_analyzer import fetch_us_etf_top


US_NEWS_TOPICS = {
    "US_market": "S&P 500 Nasdaq market today earnings guidance",
    "AI_semis": "Nvidia AMD Micron Broadcom AI data center semiconductor news",
    "mega_tech": "Apple Microsoft Amazon Alphabet Meta earnings AI capex",
    "rates_macro": "Federal Reserve rate Treasury yield dollar market",
    "energy": "oil price energy stocks OPEC geopolitical risk",
    "healthcare": "US healthcare biotech pharma FDA earnings",
    "consumer": "US consumer spending retail restaurants travel earnings",
}


def _collect_news() -> dict:
    from news_scraper import fetch_all_topic_news, generate_news_context

    topics = fetch_all_topic_news(US_NEWS_TOPICS)
    return {
        "topics": topics,
        "context": generate_news_context(topics),
    }


def collect(include_news: bool = True) -> dict:
    data = {
        "global_indicators": fetch_global_indicators(),
        "stock_all": fetch_market_top_stocks("USA", "ALL", "priceTop", 100),
        "stock_nyse": fetch_market_top_stocks("USA", "NYS", "priceTop", 100),
        "stock_nasdaq": fetch_market_top_stocks("USA", "NSQ", "priceTop", 100),
        "etf": fetch_us_etf_top("priceTop", 100),
        "news": {},
    }
    if include_news:
        try:
            data["news"] = _collect_news()
        except Exception as exc:
            data["news_error"] = str(exc)
    return data


def summarize_for_prompt(data: dict, max_rows: int = 18) -> str:
    lines = ["[미국]"]
    column_map = {
        "global_indicators": ["종목명", "현재가", "전일대비", "등락률(%)", "분류"],
        "stock_all": ["종목명", "심볼", "등락률", "거래대금", "업종"],
        "stock_nyse": ["종목명", "심볼", "등락률", "거래대금", "업종"],
        "stock_nasdaq": ["종목명", "심볼", "등락률", "거래대금", "업종"],
        "etf": ["종목명", "심볼", "등락률", "거래대금", "1개월수익률", "3개월수익률", "주요보유"],
    }
    for key in ["global_indicators", "stock_all", "stock_nyse", "stock_nasdaq", "etf"]:
        value = data.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            cols = [col for col in column_map[key] if col in value.columns]
            compact = value[cols] if cols else value
            lines.append(f"\n<{key}>\n{compact.head(max_rows).to_string(index=False)}")

    news = data.get("news") or {}
    for topic, articles in list((news.get("topics") or {}).items())[:8]:
        if not articles:
            continue
        lines.append(f"\n<news:{topic}>")
        for article in articles[:5]:
            source = article.get("source", "")
            suffix = f" [{source}]" if source else ""
            lines.append(f"- {article.get('title', '')}{suffix}")

    if data.get("news_error"):
        lines.append(f"\n<news_error> {data['news_error']}")
    return "\n".join(lines)
