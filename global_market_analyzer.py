"""해외 시장 분석 모듈

네이버 증권 글로벌 페이지에서 주요지표 + 글로벌 시장
(중국 상해/심천, 홍콩, 일본, 대만) 거래대금 상위 종목을 수집하고,
시장별 주도 섹터·주요 종목 주가흐름·배경을 분석한다.

API: https://stock.naver.com/api/foreign/market/stock/global
"""

import requests
import pandas as pd
from collections import Counter
from datetime import datetime
from io import StringIO

from config import NAVER_BASE, NAVER_HEADERS
from naver_scraper import fetch_global_indicators, fetch_exchange_rates


# ═══════════════════════════════════════════════════════════
# 시장 정의
# ═══════════════════════════════════════════════════════════

ASIAN_MARKETS = {
    "상해(후강통)": {"nation": "CHN", "tradeType": "SHH", "currency": "CNY"},
    "심천(선강통)": {"nation": "CHN", "tradeType": "SHZ", "currency": "CNY"},
    "홍콩":        {"nation": "HKG", "tradeType": "ALL", "currency": "HKD"},
    "일본":        {"nation": "JPN", "tradeType": "ALL", "currency": "JPY"},
}

SECTOR_KOR_MAP = {
    "반도체 및 반도체 장비": "반도체",
    "건설 및 엔지니어링": "건설",
    "은행": "은행",
    "보험": "보험",
    "증권": "증권",
    "자동차": "자동차",
    "전자장비 및 기기": "전자장비",
    "소프트웨어 및 IT서비스": "IT/SW",
    "통신서비스": "통신",
    "제약": "제약/바이오",
    "의료장비 및 서비스": "의료",
    "석유 및 가스": "에너지",
    "전기 유틸리티": "유틸리티",
    "금속 및 광업": "금속/광업",
    "기계": "기계",
    "화학": "화학",
    "식품 및 음료": "식품",
    "부동산": "부동산",
    "운송 인프라": "운송",
    "항공": "항공",
    "소매": "소매/유통",
}


def _shorten_sector(name: str) -> str:
    for key, val in SECTOR_KOR_MAP.items():
        if key in name:
            return val
    return name[:8] if len(name) > 8 else name


# ═══════════════════════════════════════════════════════════
# 데이터 수집
# ═══════════════════════════════════════════════════════════

def fetch_market_top_stocks(
    nation: str,
    trade_type: str = "ALL",
    order_type: str = "quantTop",
    page_size: int = 100,
) -> pd.DataFrame:
    """특정 시장의 거래량/거래대금 상위 종목 수집"""
    url = f"{NAVER_BASE}/foreign/market/stock/global"
    params = {
        "nation": nation,
        "tradeType": trade_type,
        "orderType": order_type,
        "startIdx": 0,
        "pageSize": page_size,
    }
    resp = requests.get(url, params=params, headers=NAVER_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for i, item in enumerate(data, 1):
        price = float(item.get("currentPrice", 0))
        prev_close = price - float(item.get("compareToPreviousClosePrice", 0))
        change_pct = float(item.get("fluctuationsRatio", 0))
        volume = int(item.get("accumulatedTradingVolume", 0))
        value = float(item.get("accumulatedTradingValue", 0))
        market_cap = float(item.get("marketValue", 0))

        direction = item.get("compareToPreviousPrice", "")
        if direction == "RISING":
            sign = "▲"
        elif direction == "FALLING":
            sign = "▼"
        else:
            sign = "-"

        exchange_info = item.get("stockExchangeType", {})
        currency_info = item.get("currencyType", {})

        rows.append({
            "순위": i,
            "종목명": item.get("koreanCodeName", ""),
            "영문명": item.get("englishCodeName", ""),
            "코드": item.get("reutersCode", ""),
            "심볼": item.get("symbolCode", ""),
            "현재가": price,
            "등락": f"{sign} {abs(change_pct):.2f}%",
            "등락률": change_pct,
            "거래량": volume,
            "거래대금": value,
            "시가총액": market_cap,
            "시가": float(item.get("openPrice", 0)),
            "고가": float(item.get("highPrice", 0)),
            "저가": float(item.get("lowPrice", 0)),
            "업종": item.get("reutersIndustryName", ""),
            "업종코드": item.get("reutersIndustryCode", ""),
            "거래소": exchange_info.get("nameKor", ""),
            "거래소코드": exchange_info.get("code", ""),
            "통화": currency_info.get("code", ""),
            "배당수익률": float(item.get("dividendYieldRatio", 0)),
        })

    return pd.DataFrame(rows)


def fetch_all_asian_markets() -> dict[str, pd.DataFrame]:
    """아시아 4개 시장 거래대금 상위 100종목 수집"""
    results = {}
    for market_name, market_config in ASIAN_MARKETS.items():
        print(f"  [{market_name}] 거래대금 상위 100 수집 중...")
        df = fetch_market_top_stocks(
            nation=market_config["nation"],
            trade_type=market_config["tradeType"],
            order_type="quantTop",
            page_size=100,
        )
        results[market_name] = df
    return results


def fetch_taiwan_market_data(top_n: int = 50) -> tuple[pd.DataFrame, dict]:
    """대만 TAIEX와 거래대금 상위 종목을 글로벌 모듈 내부에서 수집."""
    taiex = {}
    try:
        resp = requests.get(
            "https://www.twse.com.tw/exchangeReport/MI_INDEX",
            params={"response": "json", "type": "IND"},
            headers=NAVER_HEADERS,
            timeout=10,
        )
        data = resp.json()
        index_rows = []
        if "data1" in data:
            index_rows.extend(data.get("data1", []))
        for table in data.get("tables", []):
            title = str(table.get("title", ""))
            if "價格指數" in title:
                index_rows.extend(table.get("data", []))

        for row in index_rows:
            label = str(row[0]) if row else ""
            if "發行量加權" in label or "TAIEX" in label:
                sign = -1 if "-" in str(row[2]) or "green" in str(row[2]) else 1
                change = str(row[3]).replace(",", "")
                if sign < 0 and not change.startswith("-"):
                    change = f"-{change}"
                taiex = {
                    "name": "TAIEX",
                    "value": str(row[1]).replace(",", ""),
                    "change": change,
                    "change_pct": str(row[4]).replace("%", "").strip(),
                }
                break
    except Exception as e:
        print(f"  [대만] TAIEX 조회 실패: {e}")

    ranking = pd.DataFrame()
    try:
        resp = requests.get(
            "https://www.cnyes.com/twstock/ranking3.aspx",
            headers={**NAVER_HEADERS, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"},
            timeout=15,
        )
        resp.encoding = "utf-8"
        tables = pd.read_html(StringIO(resp.text), encoding="utf-8")
        if tables:
            ranking = max(tables, key=len).head(top_n).reset_index(drop=True)
            rename = {}
            normalized = ["종목코드", "종목명", "거래대금(TWD)", "거래량", "종가", "등락"]
            for idx, col in enumerate(ranking.columns[: len(normalized)]):
                rename[col] = normalized[idx]
            ranking = ranking.rename(columns=rename)
    except Exception as e:
        print(f"  [대만] 거래대금 순위 수집 실패: {e}")
        ranking = _fetch_taiwan_twse_ranking(top_n)

    ranking.attrs["taiex"] = taiex
    return ranking, taiex


def _fetch_taiwan_twse_ranking(top_n: int = 50) -> pd.DataFrame:
    """cnyes 장애 시 TWSE 공식 일일 전체 종목 데이터로 거래대금 순위를 대체."""
    try:
        resp = requests.get(
            "https://www.twse.com.tw/exchangeReport/MI_INDEX",
            params={"response": "json", "type": "ALLBUT0999"},
            headers=NAVER_HEADERS,
            timeout=20,
        )
        data = resp.json()
        target = None
        for table in data.get("tables", []):
            fields = table.get("fields") or []
            if "證券代號" in fields and "成交金額" in fields:
                target = table
                break
        if not target:
            return pd.DataFrame()

        fields = target["fields"]
        rows = target.get("data", [])
        df = pd.DataFrame(rows, columns=fields)
        rename = {
            "證券代號": "종목코드",
            "證券名稱": "종목명",
            "成交金額": "거래대금(TWD)",
            "成交股數": "거래량",
            "收盤價": "종가",
            "漲跌價差": "등락",
        }
        df = df.rename(columns=rename)
        if "거래대금(TWD)" in df.columns:
            df["_거래대금숫자"] = pd.to_numeric(
                df["거래대금(TWD)"].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            ).fillna(0)
            df = df.sort_values("_거래대금숫자", ascending=False).head(top_n)
            df = df.drop(columns=["_거래대금숫자"])
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"  [대만] TWSE 거래대금 대체 수집 실패: {e}")
        return pd.DataFrame()


def fetch_all_global_markets() -> dict[str, pd.DataFrame]:
    """글로벌 모듈용 시장 데이터 수집. 대만은 별도 모듈이 아니라 여기로 통합한다."""
    results = fetch_all_asian_markets()

    try:
        print("  [대만] TAIEX + 거래대금 상위 수집 중...")
        ranking, taiex = fetch_taiwan_market_data()
        ranking.attrs["taiex"] = taiex
        results["대만"] = ranking
    except Exception as e:
        print(f"  [대만] 데이터 수집 실패: {e}")
        results["대만"] = pd.DataFrame()

    return results


# ═══════════════════════════════════════════════════════════
# 분석: 주도 섹터
# ═══════════════════════════════════════════════════════════

def analyze_leading_sectors(df: pd.DataFrame, top_n: int = 5) -> list[dict]:
    """거래대금 상위 종목에서 주도 섹터 분석"""
    if df.empty:
        return []

    sector_stats = {}
    for _, row in df.iterrows():
        sector = row["업종"]
        if not sector:
            continue
        if sector not in sector_stats:
            sector_stats[sector] = {
                "종목수": 0,
                "총거래대금": 0,
                "총시총": 0,
                "상승": 0,
                "하락": 0,
                "대표종목": [],
                "평균등락률": [],
            }
        s = sector_stats[sector]
        s["종목수"] += 1
        s["총거래대금"] += row["거래대금"]
        s["총시총"] += row["시가총액"]
        s["평균등락률"].append(row["등락률"])
        if row["등락률"] > 0:
            s["상승"] += 1
        elif row["등락률"] < 0:
            s["하락"] += 1
        if len(s["대표종목"]) < 3:
            s["대표종목"].append(row["종목명"])

    result = []
    for sector, stats in sector_stats.items():
        avg_change = sum(stats["평균등락률"]) / len(stats["평균등락률"]) if stats["평균등락률"] else 0
        result.append({
            "업종": _shorten_sector(sector),
            "업종_원본": sector,
            "종목수": stats["종목수"],
            "총거래대금": stats["총거래대금"],
            "평균등락률": round(avg_change, 2),
            "상승": stats["상승"],
            "하락": stats["하락"],
            "대표종목": stats["대표종목"],
        })

    result.sort(key=lambda x: x["총거래대금"], reverse=True)
    return result[:top_n]


# ═══════════════════════════════════════════════════════════
# 분석: 주요 종목 주가흐름
# ═══════════════════════════════════════════════════════════

def analyze_top_movers(df: pd.DataFrame, top_n: int = 10) -> dict:
    """주요 종목 주가흐름 분석 — 상승/하락/거래대금 상위"""
    if df.empty:
        return {"상승": [], "하락": [], "거래대금": []}

    rising = df[df["등락률"] > 0].nlargest(top_n, "등락률")
    falling = df[df["등락률"] < 0].nsmallest(top_n, "등락률")
    by_value = df.nlargest(top_n, "거래대금")

    def to_list(sub_df):
        return [{
            "종목명": r["종목명"],
            "현재가": r["현재가"],
            "등락률": r["등락률"],
            "등락": r["등락"],
            "거래대금": r["거래대금"],
            "업종": _shorten_sector(r["업종"]),
            "시가총액": r["시가총액"],
        } for _, r in sub_df.iterrows()]

    return {
        "상승": to_list(rising),
        "하락": to_list(falling),
        "거래대금": to_list(by_value),
    }


# ═══════════════════════════════════════════════════════════
# 리포트 생성
# ═══════════════════════════════════════════════════════════

VALUE_CHAIN_BUCKETS = {
    "소재/에너지": ["에너지", "석유", "가스", "금속", "광업", "화학", "철강", "소재", "유틸리티", "전기"],
    "산업재": ["기계", "건설", "운송", "항공", "조선", "방산", "인프라", "엔지니어링"],
    "소비재": ["자동차", "소매", "유통", "식품", "음료", "부동산", "여행", "호텔"],
    "IT/커뮤니케이션": ["반도체", "IT", "소프트웨어", "전자", "통신", "인터넷", "AI", "장비"],
    "헬스케어": ["제약", "바이오", "의료", "헬스"],
}


def _fmt_pct(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "N/A"
    return f"{value:+.2f}%"


def _fmt_amount(value, currency: str = "") -> str:
    try:
        value = float(value)
    except Exception:
        return "N/A"
    unit = currency or ""
    if abs(value) >= 1e12:
        return f"{value / 1e12:,.1f}조{unit}"
    if abs(value) >= 1e8:
        return f"{value / 1e8:,.0f}억{unit}"
    return f"{value:,.0f}{unit}"


def _standard_market(df: pd.DataFrame) -> bool:
    return not df.empty and {"등락률", "거래대금", "업종", "종목명"}.issubset(df.columns)


def _market_summary(df: pd.DataFrame) -> dict:
    if not _standard_market(df):
        return {"avg": 0, "rising": 0, "falling": 0, "total": 0, "value": 0}
    return {
        "avg": float(df["등락률"].mean()),
        "rising": int((df["등락률"] > 0).sum()),
        "falling": int((df["등락률"] < 0).sum()),
        "total": len(df),
        "value": float(df["거래대금"].sum()),
    }


def _sector_line(sectors: list[dict], positive: bool) -> str:
    filtered = [
        s for s in sectors
        if (s["평균등락률"] > 0 if positive else s["평균등락률"] < 0)
    ]
    filtered = sorted(filtered, key=lambda s: s["평균등락률"], reverse=positive)[:5]
    if not filtered:
        return "없음"
    return ", ".join(f"{s['업종']}({_fmt_pct(s['평균등락률'])})" for s in filtered)


def _top_stock_phrase(stocks: list[dict], count: int = 3) -> str:
    if not stocks:
        return "특이 종목 없음"
    return ", ".join(f"{s['종목명']}({_fmt_pct(s['등락률'])})" for s in stocks[:count])


def _value_chain_bucket(sector: str) -> str | None:
    text = str(sector)
    for bucket, keywords in VALUE_CHAIN_BUCKETS.items():
        if any(keyword.lower() in text.lower() for keyword in keywords):
            return bucket
    return None


def _build_value_chain_review(market_data: dict[str, pd.DataFrame]) -> list[str]:
    buckets = {bucket: [] for bucket in VALUE_CHAIN_BUCKETS}
    for market_name, df in market_data.items():
        if not _standard_market(df):
            continue
        for _, row in df.nlargest(min(40, len(df)), "거래대금").iterrows():
            bucket = _value_chain_bucket(row.get("업종", ""))
            if not bucket or len(buckets[bucket]) >= 4:
                continue
            buckets[bucket].append(
                f"- {market_name} {row['종목명']}, {row['업종']} / 등락률 {_fmt_pct(row['등락률'])}"
            )

    lines = ["", "<글로벌 밸류체인 데일리>", ""]
    for bucket, bullets in buckets.items():
        lines.append(f"[{bucket}]")
        lines.extend(bullets or ["- 주요 업데이트 없음"])
        lines.append("")
    return lines[:-1]


def _taiwan_daily_review(df: pd.DataFrame) -> list[str]:
    lines = ["", "[대만]", "거래대금: N/A", "", "Daily Review", ""]
    taiex = df.attrs.get("taiex", {}) if isinstance(df, pd.DataFrame) else {}
    if taiex and taiex.get("value"):
        pct = taiex.get("change_pct", "0")
        lines[1] = f"TAIEX {_fmt_pct(pct)}"
    if df.empty:
        lines.append("* 대만 거래대금 순위 데이터 없음.")
        return lines

    name_col = next((c for c in df.columns if "종목명" in str(c)), None)
    value_col = next((c for c in df.columns if "거래대금" in str(c)), None)
    change_col = next((c for c in df.columns if "등락" in str(c)), None)

    if value_col:
        total = pd.to_numeric(
            df.head(20)[value_col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        ).sum()
        if total > 0:
            lines[2] = f"거래대금: {_fmt_amount(total, 'TWD')}"

    if name_col:
        top_names = ", ".join(str(v) for v in df[name_col].head(5).tolist())
        lines.append(f"* 거래대금 상위 종목은 {top_names} 중심으로 형성.")
        if change_col:
            movers = []
            for _, row in df.head(5).iterrows():
                movers.append(f"{row.get(name_col, '')}({row.get(change_col, '')})")
            lines.append(f"* 상위 거래 종목 등락: {', '.join(movers)}.")
    else:
        lines.append("* 대만 거래대금 상위 종목을 수집했으나 표준 종목명 컬럼을 찾지 못함.")
    return lines


def generate_global_close_report(
    market_data: dict[str, pd.DataFrame],
    global_indicators: pd.DataFrame = None,
) -> str:
    """마감시황 + 밸류체인 데일리 혼합 포맷."""
    now = datetime.now()
    parts = [f"SWHY 글로벌시장 마감시황 ({now.strftime('%y.%m.%d')})"]

    index_items = []
    if global_indicators is not None and not global_indicators.empty:
        wanted = ["상해", "심천", "항셍", "니케이", "S&P", "나스닥", "다우", "VIX"]
        for _, row in global_indicators.iterrows():
            name = str(row.get("종목명", ""))
            if any(key.lower() in name.lower() for key in wanted):
                index_items.append(f"{name} {row.get('등락률(%)', 'N/A')}%")
    parts.append(" | ".join(index_items[:8]) if index_items else "주요 지수 데이터 없음")
    parts.append("")

    for market_name, df in market_data.items():
        if market_name == "대만" or not _standard_market(df):
            parts.extend(_taiwan_daily_review(df))
            parts.append("")
            continue

        summary = _market_summary(df)
        sectors = analyze_leading_sectors(df)
        movers = analyze_top_movers(df, top_n=5)
        currency = str(df["통화"].dropna().iloc[0]) if "통화" in df and not df["통화"].dropna().empty else ""

        parts.append(f"[{market_name}]")
        parts.append(
            f"상위 {summary['total']}종목 평균 {_fmt_pct(summary['avg'])} | "
            f"상승 {summary['rising']} / 하락 {summary['falling']}"
        )
        parts.append(f"주요 상승 섹터: {_sector_line(sectors, True)}")
        parts.append(f"주요 하락 섹터: {_sector_line(sectors, False)}")
        parts.append(f"거래대금: {_fmt_amount(summary['value'], currency)}")
        parts.append("")
        parts.append("Daily Review")
        parts.append("")
        parts.append(
            f"* {market_name}은 거래대금 상위 종목 기준 평균 {_fmt_pct(summary['avg'])} 흐름. "
            f"상승 {summary['rising']}개, 하락 {summary['falling']}개로 수급 온도를 확인."
        )
        if sectors:
            top = sectors[0]
            reps = ", ".join(top["대표종목"][:3])
            parts.append(
                f"* {top['업종']} 섹터가 거래대금 기준 최상위. 대표 종목은 {reps}, "
                f"섹터 평균 등락률은 {_fmt_pct(top['평균등락률'])}."
            )
        parts.append(f"* 상승 주도 종목: {_top_stock_phrase(movers['상승'])}.")
        parts.append(f"* 하락/차익실현 종목: {_top_stock_phrase(movers['하락'])}.")
        parts.append("")

    parts.extend(_build_value_chain_review(market_data))
    return "\n".join(parts).strip()


def generate_global_market_report(
    market_data: dict[str, pd.DataFrame],
    global_indicators: pd.DataFrame = None,
) -> str:
    """해외 시장 종합 분석 리포트 생성"""
    return generate_global_close_report(market_data, global_indicators)

def save_global_report(report: str, filename: str = None) -> str:
    """리포트를 파일로 저장"""
    if filename is None:
        today = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"global_market_{today}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[리포트] 저장 완료: {filename}")
    return filename


# ═══════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="해외 시장 거래대금 상위 분석")
    parser.add_argument("--save", action="store_true", help="리포트를 텍스트 파일로 저장")
    parser.add_argument("--excel", action="store_true", help="Excel 파일로 저장")
    args = parser.parse_args()

    # 주요지표 수집
    print("\n[글로벌] 주요지표 수집 중...")
    global_indicators = fetch_global_indicators()

    # 글로벌 시장 수집
    print("[글로벌] 중국/홍콩/일본/대만 시장 데이터 수집 중...")
    market_data = fetch_all_global_markets()

    # 리포트 생성
    report = generate_global_market_report(market_data, global_indicators)
    print(report)

    if args.save:
        save_global_report(report)

    if args.excel:
        today = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"global_market_{today}.xlsx"
        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            global_indicators.to_excel(writer, sheet_name="주요지표", index=False)
            for name, df in market_data.items():
                sheet = name[:31]
                df.to_excel(writer, sheet_name=sheet, index=False)
        print(f"[Excel] 저장 완료: {filename}")


if __name__ == "__main__":
    main()
