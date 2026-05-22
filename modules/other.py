"""Non-Korea, non-US market data collection."""

from __future__ import annotations

import pandas as pd

from global_market_analyzer import fetch_all_global_markets
from naver_scraper import fetch_global_indicators
from modules.formatting import format_index_item, format_prompt_dataframe


OTHER_NEWS_TOPICS = {
    "china_market": "China A-shares Shanghai Shenzhen market today sector",
    "hongkong_market": "Hong Kong Hang Seng Tech market today China stocks",
    "japan_market": "Japan Nikkei market today yen semiconductor stocks",
    "taiwan_market": "Taiwan stock market TAIEX TSMC semiconductor today",
    "china_policy": "China stimulus policy property consumer technology regulation",
    "supply_chain": "Asia supply chain semiconductor AI data center power",
    "commodities_fx": "yuan yen dollar oil copper gold Asia market",
}

COUNTRY_MARKETS = {
    "중국": ["상해(후강통)", "심천(선강통)"],
    "홍콩": ["홍콩"],
    "일본": ["일본"],
    "대만": ["대만"],
}

COUNTRY_NEWS = {
    "중국": ["china_market", "china_policy", "supply_chain", "commodities_fx"],
    "홍콩": ["hongkong_market", "china_policy", "supply_chain"],
    "일본": ["japan_market", "supply_chain", "commodities_fx"],
    "대만": ["taiwan_market", "supply_chain", "commodities_fx"],
}

COUNTRY_INDEX_KEYWORDS = {
    "중국": ["상해", "심천", "CSI"],
    "홍콩": ["항셍"],
    "일본": ["니케이"],
    "대만": ["TAIEX"],
}


TAIWAN_ENGLISH_NAMES = {
    "台積電": "TSMC",
    "南亞科": "Nanya Technology",
    "聯發科": "MediaTek",
    "聯電": "UMC",
    "華邦電": "Winbond",
    "群創": "Innolux",
    "台達電": "Delta Electronics",
    "欣興": "Unimicron",
    "國巨*": "Yageo",
    "國巨": "Yageo",
    "華通": "Compeq",
    "鴻海": "Hon Hai",
    "廣達": "Quanta Computer",
    "緯穎": "Wiwynn",
    "奇鋐": "Asia Vital Components",
    "緯創": "Wistron",
    "日月光投控": "ASE Technology",
    "智邦": "Accton Technology",
    "技嘉": "Gigabyte",
    "世芯-KY": "Alchip",
    "聯亞": "LandMark Optoelectronics",
}


def _display_name(name) -> str:
    text = str(name or "").strip()
    return TAIWAN_ENGLISH_NAMES.get(text, text)


def _to_numeric(value) -> float:
    return pd.to_numeric(str(value).replace(",", ""), errors="coerce")


def _format_change(value, close=None, is_rate: bool = True) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return "N/A"
    if "%" in text:
        return text.replace("▲", "").replace("▼", "").strip()
    try:
        number = float(text)
    except Exception:
        return text
    if not is_rate and close is not None:
        close_value = _to_numeric(close)
        previous = close_value - number
        if pd.notna(close_value) and previous:
            rate = number / previous * 100
            sign = "+" if rate > 0 else ""
            return f"{sign}{rate:.2f}%"
    sign = "+" if number > 0 else ""
    suffix = "%" if is_rate else ""
    return f"{sign}{number:.2f}{suffix}"


def _format_level(value) -> str:
    number = _to_numeric(value)
    if pd.isna(number):
        return "" if value is None else str(value).strip()
    return f"{number:,.2f}"


def _top_value_line(frames: list[pd.DataFrame], count: int = 10) -> str:
    valid = []
    for df in frames:
        if not isinstance(df, pd.DataFrame) or df.empty or "종목명" not in df.columns:
            continue
        value_col = next((col for col in ["거래대금", "거래대금(TWD)"] if col in df.columns), None)
        change_col = next((col for col in ["등락률", "등락"] if col in df.columns), None)
        if value_col is None or change_col is None:
            continue
        cols = ["종목명", value_col, change_col]
        if "종가" in df.columns:
            cols.append("종가")
        compact = df[cols].copy()
        compact.columns = ["종목명", "거래대금", "등락률"] + (["종가"] if "종가" in cols else [])
        compact["등락률여부"] = change_col == "등락률"
        valid.append(compact)
    if not valid:
        return ""
    ranked = pd.concat(valid, ignore_index=True)
    ranked["_거래대금"] = ranked["거래대금"].map(_to_numeric)
    ranked = ranked.dropna(subset=["_거래대금"]).sort_values("_거래대금", ascending=False)
    items = []
    for _, row in ranked.iterrows():
        change = _format_change(row["등락률"], row.get("종가"), bool(row.get("등락률여부", True)))
        if change == "N/A":
            continue
        items.append(f"{_display_name(row['종목명'])}({change})")
        if len(items) >= count:
            break
    return ", ".join(items)


def _market_top_value_line(df: pd.DataFrame, count: int = 10) -> str:
    return _top_value_line([df], count)


def _country_index_line(country: str, indicators: pd.DataFrame, taiex: dict | None = None) -> str:
    if country == "대만" and taiex:
        value = _format_level(taiex.get("value", ""))
        pct = _format_change(taiex.get("change_pct", ""))
        return f"- 주요 지수: TAIEX {pct}({value})"
    if not isinstance(indicators, pd.DataFrame) or indicators.empty:
        return ""
    keywords = COUNTRY_INDEX_KEYWORDS.get(country, [])
    if not keywords:
        return ""
    rows = []
    for _, row in indicators.iterrows():
        name = str(row.get("종목명", ""))
        code = str(row.get("코드", ""))
        if any(keyword in name or keyword in code for keyword in keywords):
            rows.append(format_index_item(row))
    if not rows:
        return ""
    return f"- 주요 지수: {' | '.join(rows)}"


def _collect_news() -> dict:
    from news_scraper import fetch_all_topic_news, generate_news_context

    topics = fetch_all_topic_news(OTHER_NEWS_TOPICS)
    return {
        "topics": topics,
        "context": generate_news_context(topics),
    }


def collect(
    include_news: bool = True,
    global_indicators: pd.DataFrame | None = None,
) -> dict:
    data = {
        "global_indicators": global_indicators
        if global_indicators is not None
        else fetch_global_indicators(),
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
    lines = ["[그외: 국가별 시장]"]
    indicators = data.get("global_indicators")
    if isinstance(indicators, pd.DataFrame) and not indicators.empty:
        cols = [col for col in ["종목명", "현재가", "전일대비", "등락률(%)", "분류"] if col in indicators.columns]
        compact = indicators[cols] if cols else indicators
        compact = format_prompt_dataframe(compact)
        lines.append(f"\n<global_indicators>\n{compact.head(max_rows).to_string(index=False)}")

    markets = data.get("markets") or {}
    news = data.get("news") or {}
    topics = news.get("topics") or {}

    for country, market_names in COUNTRY_MARKETS.items():
        lines.append(f"\n[{country}]")
        country_frames = []
        country_taiex = None
        for market in market_names:
            df = markets.get(market)
            if isinstance(df, pd.DataFrame) and not df.empty:
                country_frames.append(df)
                cols = [
                    col for col in ["종목명", "심볼", "등락률", "업종", "등락"]
                    if col in df.columns
                ]
                compact = df[cols] if cols else df
                compact = format_prompt_dataframe(compact)
                lines.append(f"\n<market:{market}>\n{compact.head(max_rows).to_string(index=False)}")
                taiex = getattr(df, "attrs", {}).get("taiex")
                if taiex:
                    country_taiex = taiex
                    lines.append(f"<taiex>{taiex}")
            else:
                lines.append(f"\n<market:{market}> 데이터 없음")

        index_line = _country_index_line(country, indicators, country_taiex)
        if index_line:
            lines.append(f"\n<country_indices:{country}>\n{index_line}")

        if country == "중국":
            top_value_lines = []
            for market in market_names:
                top_value = _market_top_value_line(markets.get(market), 10)
                if top_value:
                    label = "상해" if "상해" in market else "심천"
                    top_value_lines.append(f"- {label} 거래대금 TOP10: {top_value}")
            if top_value_lines:
                lines.append(f"\n<top_value_stocks:{country}>\n" + "\n".join(top_value_lines))
        else:
            top_value = _top_value_line(country_frames, 10)
            if top_value:
                lines.append(f"\n<top_value_stocks:{country}>\n- 거래대금 TOP10: {top_value}")

        for topic in COUNTRY_NEWS.get(country, []):
            articles = topics.get(topic) or []
            if not articles:
                continue
            lines.append(f"\n<news:{country}:{topic}>")
            for article in articles[:4]:
                source = article.get("source", "")
                suffix = f" [{source}]" if source else ""
                lines.append(f"- {article.get('title', '')}{suffix}")

    if data.get("news_error"):
        lines.append(f"\n<news_error> {data['news_error']}")
    return "\n".join(lines)
