"""미국 시장 분석 모듈

네이버 증권 미국 시장 페이지에서 수집·분석:
  1. 주요지표 (기존 naver_scraper 모듈 재사용)
  2. 뉴욕/나스닥 거래대금 상위 100종목 (기존 global_market_analyzer 모듈 재사용)
  3. ETF 거래대금 상위 100개
  → 섹터별 주도주 분석, 등락 코멘트, ETF 흐름 해석

API:
  주식: /api/foreign/market/stock/global?nation=USA&tradeType={ALL|NYS|NSQ}&orderType=priceTop
  ETF:  /api/foreign/market/etf/usa?orderType=priceTop
"""

import requests
import pandas as pd
from collections import defaultdict
from datetime import datetime

from config import NAVER_BASE, NAVER_HEADERS
from naver_scraper import fetch_global_indicators
from global_market_analyzer import (
    fetch_market_top_stocks,
    analyze_leading_sectors,
    analyze_top_movers,
    _shorten_sector,
    _comment_price_trend,
    _fmt_amount,
    _fmt_pct,
    _sector_line,
    _top_stock_phrase,
    _value_chain_bucket,
)


# ═══════════════════════════════════════════════════════════
# ETF 데이터 수집
# ═══════════════════════════════════════════════════════════

ETF_CATEGORY_MAP = {
    "레버리지": ["레버리지", "2X", "3X", "Ultra", "Bull"],
    "인버스": ["인버스", "Short", "Bear", "-1X", "-2X", "-3X"],
    "반도체": ["반도체", "Semiconductor", "SOX"],
    "AI/기술": ["AI", "Technology", "Tech", "QQQ", "나스닥"],
    "에너지": ["에너지", "Energy", "Oil", "원유"],
    "금융": ["금융", "Financial", "Bank"],
    "헬스케어": ["헬스", "Health", "Bio", "바이오"],
    "채권": ["채권", "Bond", "Treasury"],
    "금/원자재": ["Gold", "금", "Silver", "은", "Metal", "원자재", "Commodity"],
    "S&P500": ["S&P 500", "S&P500", "SPY", "VOO", "IVV"],
}


def fetch_us_etf_top(
    order_type: str = "priceTop",
    page_size: int = 100,
) -> pd.DataFrame:
    """미국 ETF 거래대금/거래량 상위 수집"""
    url = f"{NAVER_BASE}/foreign/market/etf/usa"
    params = {
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
        change_pct = float(item.get("fluctuationsRatio", 0))
        volume = int(item.get("accumulatedTradingVolume", 0))
        value = float(item.get("accumulatedTradingValue", 0))
        market_cap = float(item.get("marketValue", 0))

        direction = item.get("compareToPreviousPrice", "")
        sign = "▲" if direction == "RISING" else ("▼" if direction == "FALLING" else "-")

        portfolio = item.get("portFolio", []) or []
        holdings = [p.get("componentName", "") for p in portfolio[:3]]

        exchange_info = item.get("stockExchangeType", {})

        rows.append({
            "순위": i,
            "종목명": item.get("koreanCodeName", ""),
            "영문명": item.get("englishCodeName", ""),
            "심볼": item.get("symbolCode", item.get("reutersCode", "")),
            "현재가": price,
            "등락": f"{sign} {abs(change_pct):.2f}%",
            "등락률": change_pct,
            "거래량": volume,
            "거래대금": value,
            "시가총액": market_cap,
            "1개월수익률": float(item.get("return1Month", 0)),
            "3개월수익률": float(item.get("return3Month", 0)),
            "6개월수익률": float(item.get("return6Month", 0)),
            "1년수익률": float(item.get("return1year", 0)),
            "NAV": float(item.get("nav", 0)),
            "배당수익률": float(item.get("dividendYieldRatio", 0)),
            "대분류": item.get("largeCodeNameKor", ""),
            "중분류": item.get("middleCodeNameKor", ""),
            "주요보유": ", ".join(holdings),
            "거래소": exchange_info.get("nameKor", ""),
        })

    return pd.DataFrame(rows)


def _classify_etf(name: str, symbol: str) -> str:
    """ETF 카테고리 자동 분류"""
    text = f"{name} {symbol}".upper()
    for category, keywords in ETF_CATEGORY_MAP.items():
        for kw in keywords:
            if kw.upper() in text:
                return category
    return "기타"


# ═══════════════════════════════════════════════════════════
# 섹터 심층 분석
# ═══════════════════════════════════════════════════════════

SECTOR_NEWS_CONTEXT = {
    "반도체": (
        "AI 데이터센터 투자 확대와 HBM/DRAM 슈퍼사이클이 지속되며 "
        "빅테크의 자본지출(CapEx) 증가가 핵심 동력입니다."
    ),
    "IT/SW": (
        "클라우드·SaaS 기업의 AI 기능 통합 가속화와 "
        "기업용 AI 솔루션 수요가 성장을 견인하고 있습니다."
    ),
    "전자장비": (
        "AI 서버·네트워킹 장비 수요 급증과 "
        "데이터센터 인프라 확장이 업종 전반을 밀어올리고 있습니다."
    ),
    "자동차": (
        "EV 전환 가속화와 자율주행 기술 경쟁, "
        "관세 이슈에 따른 공급망 재편이 주요 변수입니다."
    ),
    "은행": (
        "Fed 금리 동결 장기화 속에서 NIM 방어와 "
        "자산건전성 우려가 상존하고 있습니다."
    ),
    "증권": (
        "IPO 시장 회복과 트레이딩 수익 증가, "
        "자본시장 활성화가 실적 호조를 이끌고 있습니다."
    ),
    "제약/바이오": (
        "AI 신약 개발 가속화와 GLP-1 비만 치료제 시장 확대, "
        "바이오시밀러 경쟁 심화가 업종 내 차별화를 만들고 있습니다."
    ),
    "에너지": (
        "OPEC+ 감산 정책과 지정학적 리스크, "
        "에너지 전환 정책 간 균형이 유가 방향성을 결정합니다."
    ),
    "소매/유통": (
        "소비자 심리 지표와 고용 데이터, "
        "이커머스 대 오프라인 채널 경쟁 구도가 핵심입니다."
    ),
    "통신": (
        "5G 인프라 투자 성숙기 진입과 "
        "AI 데이터 트래픽 증가에 따른 네트워크 수요가 부각됩니다."
    ),
    "금속/광업": (
        "금·은 등 안전자산 수요와 희토류 공급망 이슈, "
        "전기차 배터리 소재 수요가 가격을 견인합니다."
    ),
    "유틸리티": (
        "AI 데이터센터의 막대한 전력 수요 증가로 "
        "전력 인프라 투자 기대감이 높아지고 있습니다."
    ),
    "건설": (
        "인프라 법안 수혜와 데이터센터 건설 붐이 "
        "건설·엔지니어링 섹터를 지지하고 있습니다."
    ),
    "보험": (
        "기후변화에 따른 보험 리스크 재평가와 "
        "투자수익률 변동이 밸류에이션에 영향을 줍니다."
    ),
    "기계": (
        "제조업 리쇼어링과 자동화·로봇 투자 확대가 "
        "기계 섹터의 구조적 성장을 이끌고 있습니다."
    ),
    "부동산": (
        "상업용 부동산 우려와 금리 방향에 민감하며, "
        "데이터센터 REITs는 AI 수혜 기대로 차별화됩니다."
    ),
}


def analyze_sectors_deep(df: pd.DataFrame) -> list[dict]:
    """섹터별 심층 분석 — 종목 수, 평균 등락률, 대표 상승/하락주, 배경 코멘트"""
    if df.empty:
        return []

    sectors = defaultdict(lambda: {
        "stocks": [],
        "total_value": 0,
        "changes": [],
    })

    for _, row in df.iterrows():
        sector = _shorten_sector(row.get("업종", ""))
        if not sector:
            continue
        s = sectors[sector]
        s["stocks"].append(row)
        s["total_value"] += row.get("거래대금", 0)
        s["changes"].append(row.get("등락률", 0))

    result = []
    for sector, data in sectors.items():
        changes = data["changes"]
        avg = sum(changes) / len(changes) if changes else 0
        rising = [s for s in data["stocks"] if s["등락률"] > 0]
        falling = [s for s in data["stocks"] if s["등락률"] < 0]
        rising.sort(key=lambda x: x["등락률"], reverse=True)
        falling.sort(key=lambda x: x["등락률"])

        result.append({
            "섹터": sector,
            "종목수": len(data["stocks"]),
            "평균등락률": round(avg, 2),
            "총거래대금": data["total_value"],
            "상승수": len(rising),
            "하락수": len(falling),
            "상승TOP": [
                {"종목명": s["종목명"], "등락률": s["등락률"], "현재가": s["현재가"]}
                for s in rising[:3]
            ],
            "하락TOP": [
                {"종목명": s["종목명"], "등락률": s["등락률"], "현재가": s["현재가"]}
                for s in falling[:3]
            ],
            "배경": SECTOR_NEWS_CONTEXT.get(sector, "시장 전반의 수급 흐름에 연동됩니다."),
        })

    result.sort(key=lambda x: abs(x["평균등락률"]), reverse=True)
    return result


# ═══════════════════════════════════════════════════════════
# ETF 흐름 분석
# ═══════════════════════════════════════════════════════════

def analyze_etf_flows(df: pd.DataFrame) -> dict:
    """ETF 카테고리별 흐름 분석"""
    if df.empty:
        return {}

    categories = defaultdict(list)
    for _, row in df.iterrows():
        cat = _classify_etf(row["종목명"], row["심볼"])
        categories[cat].append(row)

    result = {}
    for cat, etfs in categories.items():
        changes = [e["등락률"] for e in etfs]
        avg = sum(changes) / len(changes) if changes else 0
        etfs_sorted = sorted(etfs, key=lambda x: abs(x["등락률"]), reverse=True)

        result[cat] = {
            "종목수": len(etfs),
            "평균등락률": round(avg, 2),
            "대표ETF": [
                {
                    "종목명": e["종목명"],
                    "심볼": e["심볼"],
                    "등락률": e["등락률"],
                    "거래대금": e["거래대금"],
                    "1개월": e.get("1개월수익률", 0),
                    "3개월": e.get("3개월수익률", 0),
                    "주요보유": e.get("주요보유", ""),
                }
                for e in etfs_sorted[:5]
            ],
        }

    return dict(sorted(result.items(), key=lambda x: abs(x[1]["평균등락률"]), reverse=True))


# ═══════════════════════════════════════════════════════════
# 리포트 생성
# ═══════════════════════════════════════════════════════════

def _us_index_line(global_indicators: pd.DataFrame = None) -> str:
    if global_indicators is None or global_indicators.empty:
        return "미국 주요 지수 데이터 없음"
    wanted_codes = {".INX", ".IXIC", ".DJI", ".VIX"}
    if "코드" in global_indicators.columns:
        rows = global_indicators[global_indicators["코드"].isin(wanted_codes)]
    else:
        rows = pd.DataFrame()
    if rows.empty:
        rows = global_indicators[
            global_indicators["종목명"].str.contains("S&P|NASDAQ|나스닥|DOW|다우|VIX", case=False, na=False)
        ]
    return " | ".join(
        f"{row['종목명']} {row.get('등락률(%)', 'N/A')}%"
        for _, row in rows.iterrows()
    )


def _us_value_chain_review(stock_df: pd.DataFrame) -> list[str]:
    buckets = {
        "소재/에너지": [],
        "산업재": [],
        "소비재": [],
        "IT/커뮤니케이션": [],
        "헬스케어": [],
    }
    if not stock_df.empty:
        for _, row in stock_df.nlargest(min(50, len(stock_df)), "거래대금").iterrows():
            bucket = _value_chain_bucket(row.get("업종", ""))
            if not bucket or len(buckets[bucket]) >= 4:
                continue
            buckets[bucket].append(
                f"- {row['종목명']}, {row['업종']} / 등락률 {_fmt_pct(row['등락률'])}"
            )

    lines = ["", "<글로벌 밸류체인 데일리>", ""]
    for bucket, bullets in buckets.items():
        lines.append(f"[{bucket}]")
        lines.extend(bullets or ["- 주요 업데이트 없음"])
        lines.append("")
    return lines[:-1]


def generate_us_close_report(
    stock_df: pd.DataFrame,
    etf_df: pd.DataFrame,
    global_indicators: pd.DataFrame = None,
    nyse_df: pd.DataFrame = None,
    nasdaq_df: pd.DataFrame = None,
) -> str:
    now = datetime.now()
    parts = [f"SWHY 미국시장 마감시황 ({now.strftime('%y.%m.%d')})"]
    parts.append(_us_index_line(global_indicators))
    parts.append("")

    for label, df in [("NYSE+NASDAQ", stock_df), ("NYSE", nyse_df), ("NASDAQ", nasdaq_df)]:
        if df is None or df.empty:
            continue
        rising = int((df["등락률"] > 0).sum())
        falling = int((df["등락률"] < 0).sum())
        avg = float(df["등락률"].mean())
        value = float(df["거래대금"].sum())
        parts.append(f"[{label}]")
        parts.append(f"상위 {len(df)}종목 평균 {_fmt_pct(avg)} | 상승 {rising} / 하락 {falling}")
        sectors = analyze_leading_sectors(df)
        parts.append(f"주요 상승 섹터: {_sector_line(sectors, True)}")
        parts.append(f"주요 하락 섹터: {_sector_line(sectors, False)}")
        parts.append(f"거래대금: {_fmt_amount(value, 'USD')}")
        parts.append("")

    parts.append("Daily Review")
    parts.append("")

    if not stock_df.empty:
        sectors_deep = analyze_sectors_deep(stock_df)
        movers = analyze_top_movers(stock_df, top_n=5)
        avg = float(stock_df["등락률"].mean())
        rising = int((stock_df["등락률"] > 0).sum())
        falling = int((stock_df["등락률"] < 0).sum())
        parts.append(
            f"* 미국 거래대금 상위 종목은 평균 {_fmt_pct(avg)}. 상승 {rising}개, 하락 {falling}개로 시장 폭을 확인."
        )
        if sectors_deep:
            top = sectors_deep[0]
            up = ", ".join(f"{s['종목명']}({_fmt_pct(s['등락률'])})" for s in top["상승TOP"][:3]) or "없음"
            down = ", ".join(f"{s['종목명']}({_fmt_pct(s['등락률'])})" for s in top["하락TOP"][:3]) or "없음"
            parts.append(
                f"* {top['섹터']} 섹터 변동성이 가장 두드러짐. 상승: {up}. 하락: {down}."
            )
            parts.append(f"* {top['섹터']} 배경: {top['배경']}")
        parts.append(f"* 상승 주도 종목: {_top_stock_phrase(movers['상승'])}.")
        parts.append(f"* 하락/차익실현 종목: {_top_stock_phrase(movers['하락'])}.")

    if etf_df is not None and not etf_df.empty:
        etf_flows = analyze_etf_flows(etf_df)
        etf_rising = int((etf_df["등락률"] > 0).sum())
        etf_falling = int((etf_df["등락률"] < 0).sum())
        parts.append(
            f"* ETF 상위 {len(etf_df)}개는 상승 {etf_rising} / 하락 {etf_falling}. "
            f"평균 등락률 {_fmt_pct(etf_df['등락률'].mean())}."
        )
        for cat, info in list(etf_flows.items())[:3]:
            reps = ", ".join(
                f"{e['심볼']}({_fmt_pct(e['등락률'])})"
                for e in info["대표ETF"][:3]
            )
            parts.append(f"* ETF {cat}: 평균 {_fmt_pct(info['평균등락률'])}. 대표 {reps}.")

    parts.extend(_us_value_chain_review(stock_df))
    return "\n".join(parts).strip()


def generate_us_market_report(
    stock_df: pd.DataFrame,
    etf_df: pd.DataFrame,
    global_indicators: pd.DataFrame = None,
    nyse_df: pd.DataFrame = None,
    nasdaq_df: pd.DataFrame = None,
) -> str:
    """미국 시장 종합 분석 리포트"""
    return generate_us_close_report(stock_df, etf_df, global_indicators, nyse_df, nasdaq_df)

    now = datetime.now()
    parts = []
    parts.append("=" * 68)
    parts.append(f"  🇺🇸 미국 시장 종합 분석 리포트")
    parts.append(f"  {now.strftime('%Y년 %m월 %d일 %H:%M')} 기준")
    parts.append("=" * 68)
    parts.append("")

    # ── 1. 주요지표 ──
    if global_indicators is not None and not global_indicators.empty:
        us_indicators = global_indicators[
            global_indicators["분류"].str.contains("미국|해외", na=False) |
            global_indicators["코드"].isin([".INX", ".IXIC", ".DJI", ".VIX"])
        ]
        if not us_indicators.empty:
            parts.append("■ 미국 주요지표")
            parts.append("-" * 68)
            for _, row in us_indicators.iterrows():
                parts.append(
                    f"  {row['종목명']:20s}  {row['현재가']:>12s}  "
                    f"{row['전일대비']:>12s}  ({row['등락률(%)']:>6s}%)"
                )
            parts.append("")

    # ── 2. 거래소별 개요 ──
    parts.append("■ 거래소별 종합")
    parts.append("-" * 68)
    for label, df in [("전체(NYSE+NASDAQ)", stock_df), ("NYSE", nyse_df), ("NASDAQ", nasdaq_df)]:
        if df is None or df.empty:
            continue
        rising = len(df[df["등락률"] > 0])
        falling = len(df[df["등락률"] < 0])
        avg = df["등락률"].mean()
        parts.append(
            f"  [{label}] 상위 {len(df)}종목  "
            f"상승 {rising} / 하락 {falling}  평균 {avg:+.2f}%"
        )
    parts.append("")

    # ── 3. 섹터별 심층 분석 ──
    parts.append("=" * 68)
    parts.append("  📊 섹터별 심층 분석 (등락 폭 순)")
    parts.append("=" * 68)
    parts.append("")

    deep_sectors = analyze_sectors_deep(stock_df)
    for sector_info in deep_sectors:
        if sector_info["종목수"] < 2:
            continue

        avg = sector_info["평균등락률"]
        sign = "+" if avg > 0 else ""
        if abs(avg) >= 5:
            intensity = "🔥 급등" if avg > 0 else "🧊 급락"
        elif abs(avg) >= 2:
            intensity = "📈 강세" if avg > 0 else "📉 약세"
        else:
            intensity = "➡️ 보합"

        parts.append(
            f"  ◆ [{sector_info['섹터']}] {intensity}  "
            f"평균 {sign}{avg:.2f}%  "
            f"({sector_info['종목수']}종목: "
            f"상승 {sector_info['상승수']}/하락 {sector_info['하락수']})"
        )

        # 상승 TOP
        if sector_info["상승TOP"]:
            names = ", ".join(
                f'{s["종목명"]}({s["등락률"]:+.2f}%)' for s in sector_info["상승TOP"]
            )
            parts.append(f"    ▲ 상승: {names}")

        # 하락 TOP
        if sector_info["하락TOP"]:
            names = ", ".join(
                f'{s["종목명"]}({s["등락률"]:+.2f}%)' for s in sector_info["하락TOP"]
            )
            parts.append(f"    ▼ 하락: {names}")

        # 배경 코멘트
        parts.append(f"    💬 {sector_info['배경']}")
        parts.append("")

    # ── 4. ETF 흐름 분석 ──
    parts.append("=" * 68)
    parts.append("  📊 ETF 거래대금 상위 흐름 분석")
    parts.append("=" * 68)
    parts.append("")

    if not etf_df.empty:
        # ETF 전체 개요
        etf_rising = len(etf_df[etf_df["등락률"] > 0])
        etf_falling = len(etf_df[etf_df["등락률"] < 0])
        parts.append(
            f"  ETF TOP {len(etf_df)}: "
            f"상승 {etf_rising} / 하락 {etf_falling}  "
            f"평균 {etf_df['등락률'].mean():+.2f}%"
        )
        parts.append("")

        # 카테고리별 분석
        etf_flows = analyze_etf_flows(etf_df)
        for cat, info in etf_flows.items():
            avg = info["평균등락률"]
            sign = "+" if avg > 0 else ""
            parts.append(
                f"  ◆ [{cat}] 평균 {sign}{avg:.2f}%  "
                f"({info['종목수']}종목)"
            )

            for etf in info["대표ETF"][:3]:
                ret_1m = etf.get("1개월", 0)
                ret_3m = etf.get("3개월", 0)
                holdings = etf.get("주요보유", "")
                holdings_tag = f"  보유: {holdings}" if holdings else ""
                parts.append(
                    f"    {etf['심볼']:8s} {etf['종목명'][:30]:30s}  "
                    f"{etf['등락률']:+6.2f}%  "
                    f"(1M: {ret_1m:+.1f}% / 3M: {ret_3m:+.1f}%)"
                    f"{holdings_tag}"
                )

            # ETF 카테고리별 코멘트
            parts.append(f"    💬 {_etf_category_comment(cat, avg, info)}")
            parts.append("")

    # ── 5. 거래대금 TOP 10 ──
    parts.append("=" * 68)
    parts.append("  📊 주식 거래대금 TOP 10")
    parts.append("=" * 68)
    parts.append("")

    movers = analyze_top_movers(stock_df, top_n=10)
    for stock in movers["거래대금"][:10]:
        comment = _comment_price_trend(stock)
        parts.append(f"  {stock['순위'] if '순위' in stock else ''}. {comment}")
    parts.append("")

    parts.append("=" * 68)
    return "\n".join(parts)


def _etf_category_comment(category: str, avg_change: float, info: dict) -> str:
    """ETF 카테고리별 동향 코멘트"""
    comments = {
        "반도체": "AI/HBM 수요에 따른 반도체 기업 실적 기대가 ETF 흐름에 직접 반영됩니다.",
        "AI/기술": "빅테크 실적과 AI CapEx 증가가 기술주 ETF의 방향을 결정합니다.",
        "S&P500": "미국 경제 펀더멘털과 기업 실적 시즌 결과가 광범위 지수 ETF에 반영됩니다.",
        "레버리지": (
            f"레버리지 ETF {'매수세 유입으로 강세 추격 심리가 확산' if avg_change > 0 else '하락 시 손실 배가 위험에 주의'}됩니다."
        ),
        "인버스": (
            f"인버스 ETF {'하락에 따른 수익 실현 국면' if avg_change > 0 else '시장 하락 베팅 수요 증가 신호'}입니다."
        ),
        "에너지": "유가 방향성과 OPEC+ 정책, 지정학적 리스크가 에너지 ETF를 좌우합니다.",
        "금융": "Fed 금리 정책과 은행 실적이 금융 ETF의 핵심 변수입니다.",
        "헬스케어": "GLP-1·바이오텍 파이프라인과 FDA 승인 이슈가 헬스케어 ETF에 영향을 줍니다.",
        "채권": "Fed 금리 전망과 인플레이션 데이터가 채권 ETF 가격을 결정합니다.",
        "금/원자재": "달러 강약과 인플레이션 기대, 지정학적 불안이 안전자산 ETF를 움직입니다.",
    }
    return comments.get(category, "시장 전반의 리스크 온/오프 심리에 연동됩니다.")


def save_us_report(report: str, filename: str = None) -> str:
    if filename is None:
        today = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"us_market_{today}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[리포트] 저장 완료: {filename}")
    return filename


# ═══════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="미국 시장 종합 분석")
    parser.add_argument("--save", action="store_true", help="리포트를 파일로 저장")
    parser.add_argument("--excel", action="store_true", help="Excel로 저장")
    args = parser.parse_args()

    # 주요지표
    print("\n[미국] 주요지표 수집 중...")
    global_indicators = fetch_global_indicators()

    # 주식 TOP 100 (전체 / NYSE / NASDAQ)
    print("[미국] 거래대금 상위 주식 수집 중...")
    stock_all = fetch_market_top_stocks("USA", "ALL", "priceTop", 100)
    stock_nyse = fetch_market_top_stocks("USA", "NYS", "priceTop", 100)
    stock_nasdaq = fetch_market_top_stocks("USA", "NSQ", "priceTop", 100)

    # ETF TOP 100
    print("[미국] 거래대금 상위 ETF 수집 중...")
    etf_df = fetch_us_etf_top("priceTop", 100)

    # 리포트
    report = generate_us_market_report(
        stock_all, etf_df, global_indicators, stock_nyse, stock_nasdaq
    )
    print(report)

    if args.save:
        save_us_report(report)

    if args.excel:
        today = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"us_market_{today}.xlsx"
        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            global_indicators.to_excel(writer, sheet_name="주요지표", index=False)
            stock_all.to_excel(writer, sheet_name="주식_전체TOP100", index=False)
            stock_nyse.to_excel(writer, sheet_name="NYSE_TOP100", index=False)
            stock_nasdaq.to_excel(writer, sheet_name="NASDAQ_TOP100", index=False)
            etf_df.to_excel(writer, sheet_name="ETF_TOP100", index=False)
        print(f"[Excel] 저장 완료: {filename}")


if __name__ == "__main__":
    main()
