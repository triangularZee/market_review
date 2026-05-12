"""Non-Korea, non-US market data collection."""

from __future__ import annotations

import pandas as pd

from global_market_analyzer import fetch_all_global_markets
from naver_scraper import fetch_global_indicators


OTHER_NEWS_TOPICS = {
    "china_market": "China A-shares Shanghai Shenzhen market today sector",
    "hongkong_market": "Hong Kong Hang Seng Tech market today China stocks",
    "japan_market": "Japan Nikkei market today yen semiconductor stocks",
    "taiwan_market": "Taiwan stock market TAIEX TSMC semiconductor today",
    "china_policy": "China stimulus policy property consumer technology regulation",
    "supply_chain": "Asia supply chain semiconductor AI data center power",
    "commodities_fx": "yuan yen dollar oil copper gold Asia market",
}


def _collect_news() -> dict:
    from news_scraper import fetch_all_topic_news, generate_news_context

    topics = fetch_all_topic_news(OTHER_NEWS_TOPICS)
    return {
        "topics": topics,
        "context": generate_news_context(topics),
    }


def collect(include_news: bool = True) -> dict:
    data = {
        "global_indicators": fetch_global_indicators(),
        "markets": fetch_all_global_markets(),
        "news": {},
    }
    if include_news:
        try:
            data["news"] = _collect_news()
        except Exception as exc:
            data["news_error"] = str(exc)
    return data


def summarize_for_prompt(data: dict, max_rows: int = 18) -> str:
    lines = ["[그외: 중국/홍콩/일본/대만]"]
    indicators = data.get("global_indicators")
    if isinstance(indicators, pd.DataFrame) and not indicators.empty:
        cols = [col for col in ["종목명", "현재가", "전일대비", "등락률(%)", "분류"] if col in indicators.columns]
        compact = indicators[cols] if cols else indicators
        lines.append(f"\n<global_indicators>\n{compact.head(max_rows).to_string(index=False)}")

    markets = data.get("markets") or {}
    for market, df in markets.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            cols = [
                col for col in ["종목명", "심볼", "등락률", "거래대금", "거래대금(TWD)", "업종", "등락"]
                if col in df.columns
            ]
            compact = df[cols] if cols else df
            lines.append(f"\n<market:{market}>\n{compact.head(max_rows).to_string(index=False)}")
            taiex = getattr(df, "attrs", {}).get("taiex")
            if taiex:
                lines.append(f"<taiex>{taiex}")
        else:
            lines.append(f"\n<market:{market}> 데이터 없음")

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
