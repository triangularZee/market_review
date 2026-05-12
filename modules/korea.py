"""Korea market data collection."""

from __future__ import annotations

import pandas as pd

from naver_scraper import (
    fetch_exchange_rates,
    fetch_global_indicators,
    fetch_index_investor_flows,
    fetch_sector_top10,
)


INVESTORS = {"개인": "개인", "기관": "기관", "외인": "외국인"}


def _has_market_flow(investor: dict) -> bool:
    for key in ["0780_kospi", "0780_kosdaq"]:
        value = investor.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            return True
    return False


def _apply_naver_investor_fallback(data: dict) -> None:
    investor = data.setdefault("investor", {})
    if _has_market_flow(investor):
        return
    try:
        fallback = fetch_index_investor_flows()
        for key, value in fallback.items():
            if isinstance(value, pd.DataFrame) and not value.empty:
                investor[key] = value
        if _has_market_flow(investor):
            data["investor_fallback"] = "네이버 지수 투자정보"
    except Exception as exc:
        data["investor_fallback_error"] = str(exc)


def _fmt_krw(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "N/A"
    sign = "+" if value > 0 else ""
    eok = value / 1e8
    if abs(eok) >= 10000:
        return f"{sign}{eok / 10000:,.2f}조원"
    return f"{sign}{eok:,.0f}억원"


def _latest_market_flow(investor: dict) -> list[str]:
    lines = ["\n<korea_investor_flow_by_market>"]
    market_map = {
        "코스피": "0780_kospi",
        "코스닥": "0780_kosdaq",
    }
    for market, key in market_map.items():
        df = investor.get(key)
        if not isinstance(df, pd.DataFrame) or df.empty:
            lines.append(f"- {market}: 데이터 없음")
            continue
        row = df.iloc[0]
        lines.append(
            f"- {market}: 개인 {_fmt_krw(row.get('개인_순매수'))}, "
            f"기관 {_fmt_krw(row.get('기관_순매수'))}, "
            f"외국인 {_fmt_krw(row.get('외인_순매수'))}"
        )

    return lines


def _top3_by_investor(investor: dict) -> list[str]:
    lines = []
    market_map = {
        "코스피": ("0795_kospi_buy", "0795_kospi_sell"),
        "코스닥": ("0795_kosdaq_buy", "0795_kosdaq_sell"),
    }
    for market, (buy_key, sell_key) in market_map.items():
        buy_df = investor.get(buy_key, pd.DataFrame())
        sell_df = investor.get(sell_key, pd.DataFrame())
        market_lines = [f"[{market}]"]
        for subject, label in INVESTORS.items():
            subject_buy = (
                buy_df[buy_df["투자자"] == subject].head(3)
                if isinstance(buy_df, pd.DataFrame)
                and not buy_df.empty
                and "투자자" in buy_df.columns
                else pd.DataFrame()
            )
            subject_sell = (
                sell_df[sell_df["투자자"] == subject].head(3)
                if isinstance(sell_df, pd.DataFrame)
                and not sell_df.empty
                and "투자자" in sell_df.columns
                else pd.DataFrame()
            )

            def fmt_rows(df: pd.DataFrame) -> str:
                return ", ".join(
                    f"{r.get('종목명')}({_fmt_krw(r.get('순매수금액'))}, {r.get('등락률')}%)"
                    for _, r in df.iterrows()
                )

            if not subject_buy.empty:
                market_lines.append(f"- {label} 순매수 TOP3: {fmt_rows(subject_buy)}")
            if not subject_sell.empty:
                market_lines.append(f"- {label} 순매도 TOP3: {fmt_rows(subject_sell)}")

        if len(market_lines) > 1:
            if not lines:
                lines.append("\n<korea_investor_top3_by_subject>")
            lines.extend(market_lines)
    return lines


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
        finally:
            _apply_naver_investor_fallback(data)

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
    if investor:
        lines.extend(_latest_market_flow(investor))
        lines.extend(_top3_by_investor(investor))

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
    if data.get("investor_fallback"):
        lines.append(f"\n<investor_fallback> {data['investor_fallback']}")
    if data.get("investor_fallback_error"):
        lines.append(f"\n<investor_fallback_error> {data['investor_fallback_error']}")

    return "\n".join(lines)
