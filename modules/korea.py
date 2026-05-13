"""Korea market data collection."""

from __future__ import annotations

import pandas as pd

from modules.formatting import format_prompt_dataframe
from naver_scraper import (
    fetch_exchange_rates,
    fetch_global_indicators,
    fetch_index_investor_flows,
    fetch_index_program_flows,
    fetch_sector_top10,
)


INVESTORS = {"개인": "개인", "기관": "기관", "외인": "외국인"}


def _has_market_flow(investor: dict) -> bool:
    for key in ["0780_kospi", "0780_kosdaq", "0780_fut"]:
        value = investor.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            return True
    return False


def _has_investor_top_stocks(investor: dict) -> bool:
    for key in [
        "0795_kospi_buy",
        "0795_kospi_sell",
        "0795_kosdaq_buy",
        "0795_kosdaq_sell",
    ]:
        value = investor.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            return True
    return False


def _has_program_flow(investor: dict) -> bool:
    for key in ["2780_kospi", "2780_kosdaq"]:
        value = investor.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            return True
    return False


def _apply_naver_investor_fallback(data: dict) -> None:
    investor = data.setdefault("investor", {})
    fallback_sources = []
    if not _has_market_flow(investor):
        try:
            fallback = fetch_index_investor_flows()
            for key, value in fallback.items():
                if isinstance(value, pd.DataFrame) and not value.empty:
                    investor[key] = value
            if _has_market_flow(investor):
                fallback_sources.append("네이버 지수 투자정보")
        except Exception as exc:
            data["investor_fallback_error"] = str(exc)

    if not _has_investor_top_stocks(investor):
        data["investor_top_fallback_error"] = (
            "네이버 금융 투자자별 매매상위는 기준일이 없어 생략"
        )

    if not _has_program_flow(investor):
        try:
            fallback = fetch_index_program_flows()
            for key, value in fallback.items():
                if isinstance(value, pd.DataFrame) and not value.empty:
                    investor[key] = value
            if _has_program_flow(investor):
                fallback_sources.append("네이버 프로그램 매매")
        except Exception as exc:
            data["program_fallback_error"] = str(exc)

    if fallback_sources:
        data["investor_fallback"] = ", ".join(fallback_sources)


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


def _fmt_flow_value(value, unit: str = "원") -> str:
    if unit == "계약":
        try:
            value = float(value)
        except Exception:
            return "N/A"
        sign = "+" if value > 0 else ""
        return f"{sign}{value:,.0f}계약"
    return _fmt_krw(value)


def _latest_market_flow(investor: dict) -> list[str]:
    lines = ["\n<korea_investor_flow_by_market>"]
    market_map = {
        "코스피": "0780_kospi",
        "코스닥": "0780_kosdaq",
        "선물": "0780_fut",
    }
    for market, key in market_map.items():
        df = investor.get(key)
        if not isinstance(df, pd.DataFrame) or df.empty:
            lines.append(f"- {market}: 데이터 없음")
            continue
        row = df.iloc[0]
        unit = row.get("단위", "원")
        lines.append(
            f"- {market}: 개인 {_fmt_flow_value(row.get('개인_순매수'), unit)}, "
            f"기관 {_fmt_flow_value(row.get('기관_순매수'), unit)}, "
            f"외국인 {_fmt_flow_value(row.get('외인_순매수'), unit)}"
        )

    return lines


def _latest_program_flow(investor: dict) -> list[str]:
    lines = ["\n<korea_program_flow_by_market>"]
    market_map = {
        "코스피 프로그램": "2780_kospi",
        "코스닥 프로그램": "2780_kosdaq",
    }
    has_data = False
    for market, key in market_map.items():
        df = investor.get(key)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        row = df.iloc[0]
        lines.append(
            f"- {market}: 차익 {_fmt_krw(row.get('차익_순매수'))}, "
            f"비차익 {_fmt_krw(row.get('비차익_순매수'))}"
        )
        has_data = True
    return lines if has_data else []


def _target_investor_date(investor: dict) -> str:
    for key in ["0780_kospi", "0780_kosdaq", "0780_fut"]:
        df = investor.get(key)
        if isinstance(df, pd.DataFrame) and not df.empty and "일자" in df.columns:
            return str(df.iloc[0].get("일자", "")).replace("-", "").replace("/", "")[:8]
    return ""


def _date_aligned(df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    if not target_date:
        return df
    if "일자" not in df.columns:
        return pd.DataFrame()
    dates = df["일자"].astype(str).str.replace("-", "", regex=False).str.replace("/", "", regex=False).str[:8]
    return df[dates == target_date].copy()


def _top5_by_investor(investor: dict) -> list[str]:
    lines = []
    target_date = _target_investor_date(investor)
    buy_frames = [
        _date_aligned(investor.get("0795_kospi_buy", pd.DataFrame()), target_date),
        _date_aligned(investor.get("0795_kosdaq_buy", pd.DataFrame()), target_date),
    ]
    sell_frames = [
        _date_aligned(investor.get("0795_kospi_sell", pd.DataFrame()), target_date),
        _date_aligned(investor.get("0795_kosdaq_sell", pd.DataFrame()), target_date),
    ]
    buy_df = pd.concat(
        [df for df in buy_frames if isinstance(df, pd.DataFrame) and not df.empty],
        ignore_index=True,
    ) if any(isinstance(df, pd.DataFrame) and not df.empty for df in buy_frames) else pd.DataFrame()
    sell_df = pd.concat(
        [df for df in sell_frames if isinstance(df, pd.DataFrame) and not df.empty],
        ignore_index=True,
    ) if any(isinstance(df, pd.DataFrame) and not df.empty for df in sell_frames) else pd.DataFrame()

    def pick_top(df: pd.DataFrame, subject: str, side: str) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty or "투자자" not in df.columns:
            return pd.DataFrame()
        subject_df = df[df["투자자"] == subject].copy()
        if subject_df.empty or "순매수금액" not in subject_df.columns:
            return pd.DataFrame()
        subject_df["순매수금액"] = pd.to_numeric(subject_df["순매수금액"], errors="coerce").fillna(0)
        ascending = side == "sell"
        return subject_df.sort_values("순매수금액", ascending=ascending).head(5)

    def fmt_rows(df: pd.DataFrame) -> str:
        items = []
        for _, r in df.iterrows():
            change = str(r.get("등락률", "") or "").strip()
            change_suffix = f", {change}%" if change else ""
            items.append(
                f"{r.get('종목명')}({_fmt_krw(r.get('순매수금액'))}{change_suffix})"
            )
        return ", ".join(items)

    top_lines = ["[국내 통합]"]
    for subject, label in {"외인": "외국인"}.items():
        subject_buy = pick_top(buy_df, subject, "buy")
        subject_sell = pick_top(sell_df, subject, "sell")
        if not subject_buy.empty:
            top_lines.append(f"- {label} 순매수 TOP5: {fmt_rows(subject_buy)}")
        if not subject_sell.empty:
            top_lines.append(f"- {label} 순매도 TOP5: {fmt_rows(subject_sell)}")

    if len(top_lines) > 1:
        lines.append("\n<korea_investor_top5_by_subject_combined>")
        lines.extend(top_lines)
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
            if key == "global_indicators" and "분류" in compact.columns:
                compact = compact[
                    compact["분류"].isin(["국내지수", "환율", "금속", "에너지"])
                ]
            compact = format_prompt_dataframe(compact)
            lines.append(f"\n<{key}>\n{compact.head(max_rows).to_string(index=False)}")

    investor = data.get("investor") or {}
    if investor:
        lines.extend(_latest_market_flow(investor))
        lines.extend(_latest_program_flow(investor))
        lines.extend(_top5_by_investor(investor))

    for key, value in investor.items():
        if isinstance(value, pd.DataFrame) and not value.empty:
            compact = value
            if key.startswith("0795_"):
                compact = _date_aligned(value, _target_investor_date(investor))
                if compact.empty:
                    continue
            if key.startswith("2780_"):
                compact = value.drop(columns=["전체_순매수"], errors="ignore")
            compact = format_prompt_dataframe(compact)
            lines.append(f"\n<investor:{key}>\n{compact.head(5).to_string(index=False)}")

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

    for err_key in ["news_error"]:
        if data.get(err_key):
            lines.append(f"\n<{err_key}> {data[err_key]}")
    if data.get("investor_fallback"):
        lines.append(f"\n<investor_fallback> {data['investor_fallback']}")

    return "\n".join(lines)
