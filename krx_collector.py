"""KRX 데이터 수집 모듈 (pykrx 기반, 크로스 플랫폼)

KRX 공개 데이터를 수집하는 크로스 플랫폼 모듈.
모든 데이터는 금액(원) 기준으로 수집됩니다.

수집 항목:
  [0780] 투자자별매매종합 (거래대금 기준)
  [0789] 누적순매수금액
  [0795] 순매수/순매도 종목 (순매수거래대금 기준)
  [2780] 프로그램매매동향 (KRX 직접 수집)

사전 요구사항:
  pip install pykrx
"""

import sys
from io import StringIO
from datetime import datetime, timedelta

import requests
import pandas as pd
from pykrx import stock

from config import START_DATE, END_DATE


def _get_last_trading_date() -> str:
    """최근 거래일 조회 (삼성전자 OHLCV 기준)"""
    end = datetime.now()
    start = end - timedelta(days=10)
    try:
        df = stock.get_market_ohlcv_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "005930"
        )
        if not df.empty:
            return df.index[-1].strftime("%Y%m%d")
    except Exception:
        pass
    return end.strftime("%Y%m%d")


def _calc_start_date(num_days: int = 20) -> str:
    """num_days 영업일 전 시작일 (여유분 포함)"""
    dt = datetime.strptime(END_DATE, "%Y%m%d")
    start = dt - timedelta(days=int(num_days * 1.6))
    return start.strftime("%Y%m%d")


# ═══════════════════════════════════════════════════════════
# [0780] 투자자별매매종합 (거래대금)
# ═══════════════════════════════════════════════════════════

def get_investor_trading_value(market: str = "KOSPI", num_days: int = 20) -> pd.DataFrame:
    """투자자별 일별 순매수대금

    KRX 투자자별 거래대금 데이터를 기존 분석 스키마로 변환합니다.
    값은 원 단위 (거래대금).
    """
    start = _calc_start_date(num_days)
    df = stock.get_market_trading_value_by_date(start, END_DATE, market)

    if df.empty:
        return pd.DataFrame()

    df = df.tail(num_days)

    result = pd.DataFrame({
        "일자": df.index.strftime("%Y%m%d"),
        "개인_순매수": df["개인"].values,
        "외인_순매수": df["외국인합계"].values,
        "기관_순매수": df["기관합계"].values,
    })

    return result.sort_values("일자", ascending=False).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════
# [0789] 누적순매수금액
# ═══════════════════════════════════════════════════════════

def get_cumulative_net_value(market: str = "KOSPI") -> pd.DataFrame:
    """투자자별 누적순매수금액 (START_DATE ~ END_DATE)"""
    df = stock.get_market_trading_value_by_date(START_DATE, END_DATE, market)

    if df.empty:
        return pd.DataFrame()

    result = pd.DataFrame({
        "일자": df.index.strftime("%Y%m%d"),
        "개인_순매수금액": df["개인"].values,
        "외인_순매수금액": df["외국인합계"].values,
        "기관_순매수금액": df["기관합계"].values,
    })

    for col in ["개인_순매수금액", "외인_순매수금액", "기관_순매수금액"]:
        result[f"{col}_누적"] = result[col].cumsum()

    return result


# ═══════════════════════════════════════════════════════════
# [0795] 순매수/순매도 종목 (거래대금)
# ═══════════════════════════════════════════════════════════

def get_net_buy_sell_stocks(
    market: str = "KOSPI", date: str = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """투자자별 순매수/순매도 종목 TOP (거래대금 기준)

    Returns (buy_df, sell_df) — KRX 투자자별 순매수/순매도 종목 데이터.
    금액 컬럼: '순매수금액' (원 단위)
    """
    if date is None:
        date = _get_last_trading_date()

    ohlcv = pd.DataFrame()
    try:
        ohlcv = stock.get_market_ohlcv_by_ticker(date, market)
    except Exception:
        pass

    investors = {"개인": "개인", "외인": "외국인", "기관": "기관합계"}

    buy_rows = []
    sell_rows = []

    for inv_label, inv_code in investors.items():
        try:
            df = stock.get_market_net_purchases_of_equities_by_ticker(
                date, date, market, inv_code
            )
            if df.empty:
                continue

            if not ohlcv.empty and "종가" in ohlcv.columns:
                df = df.join(ohlcv[["종가", "등락률"]], how="left")

            # 순매수 TOP 20
            net_buy = df[df["순매수거래대금"] > 0].nlargest(20, "순매수거래대금")
            for rank, (ticker, row) in enumerate(net_buy.iterrows(), 1):
                buy_rows.append({
                    "일자": date,
                    "투자자": inv_label,
                    "매매구분": "순매수",
                    "순위": rank,
                    "종목명": row["종목명"],
                    "종목코드": ticker,
                    "현재가": int(row.get("종가", 0)),
                    "등락률": f"{row.get('등락률', 0):.2f}",
                    "순매수금액": int(row["순매수거래대금"]),
                })

            # 순매도 TOP 20
            net_sell = df[df["순매수거래대금"] < 0].nsmallest(20, "순매수거래대금")
            for rank, (ticker, row) in enumerate(net_sell.iterrows(), 1):
                sell_rows.append({
                    "일자": date,
                    "투자자": inv_label,
                    "매매구분": "순매도",
                    "순위": rank,
                    "종목명": row["종목명"],
                    "종목코드": ticker,
                    "현재가": int(row.get("종가", 0)),
                    "등락률": f"{row.get('등락률', 0):.2f}",
                    "순매수금액": int(row["순매수거래대금"]),
                })
        except Exception as e:
            print(f"  [경고] {inv_label} 종목별 데이터 수집 실패: {e}")
            continue

    return pd.DataFrame(buy_rows), pd.DataFrame(sell_rows)


# ═══════════════════════════════════════════════════════════
# [2780] 프로그램매매동향 (KRX 직접 수집)
# ═══════════════════════════════════════════════════════════

def _to_numeric(val) -> int:
    """KRX CSV 숫자 변환 (콤마, 하이픈 처리)"""
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).replace(",", "").strip()
    if s in ("", "-"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def get_program_trading(market: str = "KOSPI", num_days: int = 20) -> pd.DataFrame:
    """프로그램매매동향 (KRX data.krx.co.kr 직접 수집, 거래대금 기준)"""
    market_id = "STK" if market == "KOSPI" else "KSQ"
    start = _calc_start_date(num_days)

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader",
        }

        # OTP 생성
        gen_url = "https://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd"
        gen_data = {
            "locale": "ko_KR",
            "mktId": market_id,
            "strtDd": start,
            "endDd": END_DATE,
            "share": "2",
            "money": "1",
            "csvxls_isNo": "false",
            "name": "fileDown",
            "url": "dbms/MDC/STAT/standard/MDCSTAT00801",
        }

        resp = requests.post(gen_url, data=gen_data, headers=headers, timeout=10)
        otp = resp.text.strip()

        if not otp or "<" in otp:
            raise ValueError("OTP 생성 실패")

        # CSV 다운로드
        down_url = "https://data.krx.co.kr/comm/fileDn/download_csv/download.cmd"
        resp = requests.post(
            down_url, data={"code": otp}, headers=headers, timeout=15
        )

        try:
            content = resp.content.decode("euc-kr")
        except UnicodeDecodeError:
            content = resp.content.decode("cp949")

        raw = pd.read_csv(StringIO(content))

        if raw.empty:
            return pd.DataFrame()

        # KRX CSV 컬럼명 → 내부 컬럼명 매핑
        col_map = {}
        for col in raw.columns:
            c = col.strip()
            if "일자" in c or "날짜" in c:
                col_map[col] = "일자"
            elif "비차익" not in c and "차익" in c:
                if "순매수" in c or ("순" in c and "매" in c):
                    col_map[col] = "차익_순매수"
                elif "매수" in c:
                    col_map[col] = "차익_매수"
                elif "매도" in c:
                    col_map[col] = "차익_매도"
            elif "비차익" in c:
                if "순매수" in c or ("순" in c and "매" in c):
                    col_map[col] = "비차익_순매수"
                elif "매수" in c:
                    col_map[col] = "비차익_매수"
                elif "매도" in c:
                    col_map[col] = "비차익_매도"
            elif "전체" in c or "합계" in c:
                if "순매수" in c or ("순" in c and "매" in c):
                    col_map[col] = "전체_순매수"
                elif "매수" in c:
                    col_map[col] = "전체_매수"
                elif "매도" in c:
                    col_map[col] = "전체_매도"

        rows = []
        for _, raw_row in raw.iterrows():
            row = {}
            if "일자" in col_map.values():
                date_col = next(k for k, v in col_map.items() if v == "일자")
                d = str(raw_row[date_col]).replace("/", "").replace("-", "").strip()
                row["일자"] = d[:8]

            for target_col in ["차익_매수", "차익_매도", "차익_순매수",
                               "비차익_매수", "비차익_매도", "비차익_순매수",
                               "전체_매수", "전체_매도", "전체_순매수"]:
                src_col = next((k for k, v in col_map.items() if v == target_col), None)
                if src_col is not None:
                    row[target_col] = _to_numeric(raw_row[src_col])

            # 순매수 컬럼이 없으면 매수-매도로 계산
            if "차익_순매수" not in row and "차익_매수" in row:
                row["차익_순매수"] = row["차익_매수"] - row["차익_매도"]
            if "비차익_순매수" not in row and "비차익_매수" in row:
                row["비차익_순매수"] = row["비차익_매수"] - row["비차익_매도"]
            if "전체_순매수" not in row and "전체_매수" in row:
                row["전체_순매수"] = row["전체_매수"] - row["전체_매도"]

            rows.append(row)

        df = pd.DataFrame(rows)
        if "일자" in df.columns:
            df = df.sort_values("일자", ascending=False).reset_index(drop=True)

        return df.head(num_days)

    except Exception as e:
        print(f"  [프로그램매매] KRX 수집 실패: {e}")
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════
# 통합 수집
# ═══════════════════════════════════════════════════════════

def collect_all_krx() -> dict:
    """KRX 데이터 전체 수집

    report_generator, analyzer와 호환되는 dict[str, DataFrame] 반환.
    키 이름이 같아 report_generator, analyzer와 호환됩니다.
    """
    print("\n[KRX/pykrx] 데이터 수집 중...")
    results = {}

    print("  [0780] 투자자별매매종합 (거래대금)...")
    results["0780_kospi"] = get_investor_trading_value("KOSPI")
    results["0780_kosdaq"] = get_investor_trading_value("KOSDAQ")

    print("  [0789] 누적순매수금액...")
    results["0789_kospi"] = get_cumulative_net_value("KOSPI")
    results["0789_kosdaq"] = get_cumulative_net_value("KOSDAQ")

    print("  [0795] 순매수/순매도 종목 (거래대금)...")
    for market, mkey in [("KOSPI", "kospi"), ("KOSDAQ", "kosdaq")]:
        buy_df, sell_df = get_net_buy_sell_stocks(market)
        results[f"0795_{mkey}_buy"] = buy_df
        results[f"0795_{mkey}_sell"] = sell_df

    print("  [2780] 프로그램매매동향...")
    results["2780_kospi"] = get_program_trading("KOSPI")
    results["2780_kosdaq"] = get_program_trading("KOSDAQ")

    total_rows = sum(len(df) for df in results.values())
    print(f"[KRX/pykrx] 수집 완료 — 총 {total_rows} 행")
    return results


if __name__ == "__main__":
    data = collect_all_krx()
    for key, df in data.items():
        print(f"\n{'=' * 50}")
        print(f"  [{key}]  rows={len(df)}")
        print("=" * 50)
        if not df.empty:
            print(df.head(10).to_string(index=False))
