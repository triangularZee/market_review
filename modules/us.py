"""US market data collection."""

from __future__ import annotations

import pandas as pd

from global_market_analyzer import fetch_market_top_stocks
from modules.formatting import format_index_item, format_prompt_dataframe
from naver_scraper import fetch_global_indicators
from us_market_analyzer import fetch_us_etf_top


US_NEWS_TOPICS = {
    "US_market": '("US stocks" OR "S&P 500" OR Nasdaq OR Dow) (close OR rises OR falls)',
    "AI_semis": '(Nvidia OR AMD OR Micron OR Broadcom) (stocks OR earnings OR guidance)',
    "mega_tech": '(Apple OR Microsoft OR Amazon OR Alphabet OR Meta) (stocks OR earnings OR guidance)',
    "rates_macro": '("US stocks" OR "S&P 500") (Federal Reserve OR Treasury OR dollar)',
    "energy": '("US energy stocks" OR Exxon OR Chevron) (oil OR OPEC OR earnings)',
    "healthcare": '("US healthcare stocks" OR biotech OR pharma) (FDA OR earnings)',
    "consumer": '("US consumer stocks" OR retail OR restaurants OR travel) earnings',
}


US_INDEX_KEYWORDS = ["S&P 500", "나스닥", "다우존스", "VIX"]


def _to_numeric(value) -> float:
    return pd.to_numeric(str(value).replace(",", ""), errors="coerce")


def _format_change(value) -> str:
    try:
        number = float(value)
    except Exception:
        text = "" if value is None else str(value).strip()
        return text if text else "N/A"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}%"


def _top_value_line(df: pd.DataFrame, count: int = 10) -> str:
    required = {"종목명", "등락률", "거래대금"}
    if not isinstance(df, pd.DataFrame) or df.empty or not required.issubset(df.columns):
        return ""
    ranked = df.copy()
    ranked["_거래대금"] = ranked["거래대금"].map(_to_numeric)
    ranked = ranked.dropna(subset=["_거래대금"]).sort_values("_거래대금", ascending=False)
    items = [
        f"{row['종목명']}({_format_change(row['등락률'])})"
        for _, row in ranked.head(count).iterrows()
    ]
    return ", ".join(items)


def _index_line(indicators: pd.DataFrame) -> str:
    if not isinstance(indicators, pd.DataFrame) or indicators.empty:
        return ""
    rows = []
    for _, row in indicators.iterrows():
        name = str(row.get("종목명", ""))
        if any(keyword in name for keyword in US_INDEX_KEYWORDS):
            rows.append(format_index_item(row))
    if not rows:
        return ""
    return f"- 주요 지수: {' | '.join(rows)}"


def _collect_news(report_date: str | None = None) -> dict:
    from news_scraper import fetch_all_topic_news, generate_news_context

    topics = fetch_all_topic_news(US_NEWS_TOPICS, report_date, locale="en-US")
    return {
        "topics": topics,
        "context": generate_news_context(topics),
    }


def collect(
    include_news: bool = True,
    global_indicators: pd.DataFrame | None = None,
    report_date: str | None = None,
) -> dict:
    data = {
        "global_indicators": global_indicators
        if global_indicators is not None
        else fetch_global_indicators(),
        "stock_all": fetch_market_top_stocks("USA", "ALL", "priceTop", 100),
        "stock_nyse": fetch_market_top_stocks("USA", "NYS", "priceTop", 100),
        "stock_nasdaq": fetch_market_top_stocks("USA", "NSQ", "priceTop", 100),
        "etf": fetch_us_etf_top("priceTop", 100),
        "news": {},
    }
    if include_news:
        try:
            data["news"] = _collect_news(report_date)
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
    indicators = data.get("global_indicators")
    if isinstance(indicators, pd.DataFrame) and not indicators.empty:
        cols = [col for col in column_map["global_indicators"] if col in indicators.columns]
        compact = indicators[cols] if cols else indicators
        compact = format_prompt_dataframe(compact)
        lines.append(f"\n<global_indicators>\n{compact.head(max_rows).to_string(index=False)}")
        index_line = _index_line(indicators)
        if index_line:
            lines.append(f"\n<country_indices:미국>\n{index_line}")

    for key in ["stock_all", "stock_nyse", "stock_nasdaq", "etf"]:
        value = data.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            cols = [col for col in column_map[key] if col in value.columns]
            compact = value[cols] if cols else value
            compact = format_prompt_dataframe(compact)
            label = {
                "stock_all": "market:미국 전체",
                "stock_nyse": "market:NYSE",
                "stock_nasdaq": "market:NASDAQ",
                "etf": "etf:US",
            }.get(key, key)
            lines.append(f"\n<{label}>\n{compact.head(max_rows).to_string(index=False)}")

    top_value_sections = [
        ("NASDAQ", _top_value_line(data.get("stock_nasdaq"), 10)),
        ("NYSE", _top_value_line(data.get("stock_nyse"), 10)),
    ]
    top_value_lines = [
        f"- {label} 거래대금 TOP10: {value}"
        for label, value in top_value_sections
        if value
    ]
    if top_value_lines:
        lines.append("\n<top_value_stocks:US>\n" + "\n".join(top_value_lines))

    news = data.get("news") or {}
    for topic, articles in list((news.get("topics") or {}).items())[:8]:
        if not articles:
            continue
        lines.append(f"\n<news:{topic}>")
        for article in articles[:5]:
            source = article.get("source", "")
            published = article.get("published_date", "")
            metadata = ", ".join(value for value in [published, source] if value)
            suffix = f" [{metadata}]" if metadata else ""
            lines.append(f"- {article.get('title', '')}{suffix}")

    if data.get("news_error"):
        lines.append(f"\n<news_error> {data['news_error']}")
    return "\n".join(lines)
