"""네이버 증권 데이터 스크래핑 모듈

1) 글로벌 주요지표 (stock.naver.com/market/stock/global)
2) 업종 시가총액 TOP 10 (stock.naver.com/market/stock/kr)
"""

import requests
import pandas as pd
from config import NAVER_BASE, NAVER_HEADERS, GLOBAL_INDICATOR_CODES


def fetch_global_indicators() -> pd.DataFrame:
    """글로벌 주요지표 조회 — S&P500, 나스닥, 환율, 원자재 등"""
    params = [("indicatorCodes[]", code) for code in GLOBAL_INDICATOR_CODES]
    url = f"{NAVER_BASE}/securityService/integration/indicators"
    resp = requests.get(url, params=params, headers=NAVER_HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for item in data:
        fluct_sign = "▲" if item.get("fluctuationsType") == "RISING" else (
            "▼" if item.get("fluctuationsType") == "FALLING" else "-"
        )
        rows.append({
            "종목명": item.get("stockName", ""),
            "코드": item.get("itemCode", ""),
            "현재가": item.get("currentPrice", ""),
            "전일대비": f'{fluct_sign} {item.get("fluctuations", "")}',
            "등락률(%)": item.get("fluctuationsRatio", ""),
            "시장상태": item.get("marketStatus", ""),
            "분류": _classify_indicator(item),
        })

    df = pd.DataFrame(rows)
    return df


def fetch_sector_top10() -> pd.DataFrame:
    """업종 시가총액 TOP 10 조회"""
    url = f"{NAVER_BASE}/domestic/market/home/upjongTheme/ranking"
    params = {"type": "upjong", "sortType": "totalMarketSum"}
    resp = requests.get(url, params=params, headers=NAVER_HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for item in data.get("upjongRankList", [])[:10]:
        market_sum = int(item.get("totalMarketSum", 0))
        trade_amount = int(item.get("totalTradeAmount", 0))
        rows.append({
            "순위": item.get("ranking", ""),
            "업종명": item.get("upjongThemeName", ""),
            "등락률(%)": item.get("prevChangeRate", ""),
            "시가총액(조)": round(market_sum / 1e12, 1),
            "거래대금(억)": round(trade_amount / 1e8, 0),
            "상승": item.get("riseCnt", ""),
            "하락": item.get("fallCnt", ""),
            "보합": item.get("steadyCnt", ""),
            "주도주": item.get("leadingItemName", ""),
        })

    df = pd.DataFrame(rows)
    return df


def fetch_exchange_rates() -> pd.DataFrame:
    """주요 환율 상세 조회 (은행 기준율)"""
    url = f"{NAVER_BASE}/stockDomestic/exchangeRates/list"
    params = {"currencies": "USD,JPY,EUR,CNY"}
    resp = requests.get(url, params=params, headers=NAVER_HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for item in data:
        info = item.get("currencyInfo", {})
        rows.append({
            "통화": f'{info.get("nationKoreanName", "")} {info.get("currencyKoreanName", "")}',
            "매매기준율": item.get("saleBaseRate", ""),
            "전일대비": item.get("changeVal", ""),
            "등락률(%)": item.get("changeRate", ""),
            "송금(보낼때)": item.get("ttSellingRate", ""),
            "송금(받을때)": item.get("ttBuyingRate", ""),
        })

    return pd.DataFrame(rows)


def _parse_eok_to_won(value) -> int:
    """네이버 지수 투자정보 값(억원 단위 문자열)을 원 단위 정수로 변환."""
    text = str(value or "").replace(",", "").strip()
    if not text:
        return 0
    return int(float(text) * 1e8)


def fetch_index_investor_flows() -> dict[str, pd.DataFrame]:
    """네이버 지수 페이지 투자정보에서 코스피/코스닥 투자자별 순매매를 조회."""
    markets = {
        "0780_kospi": "KOSPI",
        "0780_kosdaq": "KOSDAQ",
    }
    results = {}
    for key, code in markets.items():
        url = f"{NAVER_BASE}/securityFe/api/index/{code}/integration"
        resp = requests.get(
            url,
            headers={
                **NAVER_HEADERS,
                "Referer": f"https://stock.naver.com/domestic/index/{code}/price",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        trend = data.get("dealTrendInfo") or {}
        if not trend:
            results[key] = pd.DataFrame()
            continue

        results[key] = pd.DataFrame(
            [
                {
                    "일자": trend.get("bizdate", ""),
                    "개인_순매수": _parse_eok_to_won(trend.get("personalValue")),
                    "외인_순매수": _parse_eok_to_won(trend.get("foreignValue")),
                    "기관_순매수": _parse_eok_to_won(trend.get("institutionalValue")),
                    "출처": "네이버 투자정보",
                }
            ]
        )
    return results


def _classify_indicator(item: dict) -> str:
    stock_type = item.get("stockType", "")
    if stock_type == "worldstock":
        return f'해외지수({item.get("nationName", "")})'
    elif stock_type == "domestic":
        return "국내지수"
    elif stock_type == "marketindex":
        cat = item.get("marketIndexCategoryType", "")
        mapping = {"exchange": "환율", "metals": "금속", "energy": "에너지"}
        return mapping.get(cat, "시장지표")
    return stock_type


if __name__ == "__main__":
    from tabulate import tabulate

    print("\n" + "=" * 70)
    print("  [글로벌 주요지표]")
    print("=" * 70)
    df_global = fetch_global_indicators()
    print(tabulate(df_global, headers="keys", tablefmt="simple", showindex=False))

    print("\n" + "=" * 70)
    print("  [업종 시가총액 TOP 10]")
    print("=" * 70)
    df_sector = fetch_sector_top10()
    print(tabulate(df_sector, headers="keys", tablefmt="simple", showindex=False))

    print("\n" + "=" * 70)
    print("  [주요 환율 상세]")
    print("=" * 70)
    df_fx = fetch_exchange_rates()
    print(tabulate(df_fx, headers="keys", tablefmt="simple", showindex=False))
