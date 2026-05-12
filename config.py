"""설정값 모음"""
from datetime import date

# ── 기간 설정 ──
START_DATE = "20251229"
END_DATE = date.today().strftime("%Y%m%d")

# ── 네이버 증권 API ──
NAVER_BASE = "https://stock.naver.com/api"
NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 글로벌 주요지표 코드
GLOBAL_INDICATOR_CODES = [
    # 미국
    ".INX", ".IXIC", ".DJI",
    # 아시아
    ".N225", ".HSI", ".SSEC",
    # 유럽
    ".STOXX50E", ".GDAXI", ".FTSE",
    # 국내
    "KOSPI", "KOSDAQ",
    # 환율
    "FX_USDKRW", "FX_JPYKRW", "FX_EURKRW", "FX_CNYKRW", ".DXY",
    # 원자재
    "GCcv1", "CLcv1",
    # 변동성
    ".VIX",
]

