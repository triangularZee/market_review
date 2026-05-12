"""Gemini report generation for compact Telegram market reviews."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import requests


_ENV_PATH = Path(__file__).resolve().parent / ".env"
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
GEMINI_API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "")


def build_prompt(context: str, region: str = "all") -> str:
    date_title = datetime.now().strftime("%y.%m.%d")
    other_instruction = ""
    if region == "other":
        other_instruction = """
그외 시장 리포트는 반드시 국가/지역별로 나누세요:
[중국], [홍콩], [일본], [대만]
각 국가/지역 아래에 주요 지수, 상승/하락 섹터, 거래대금, Daily Review를 2~4개 bullet로 압축하세요.
중국은 상해와 심천 데이터를 함께 묶고, 홍콩/일본/대만은 각각 독립 섹션으로 유지하세요.
"""
    korea_instruction = ""
    if region in {"all", "korea"}:
        korea_instruction = """
국내 리포트에는 아래 수급 정보를 반드시 포함하세요:
- 개인/기관/외국인 주체별 순매수 TOP3와 순매도 TOP3. 종목명, 거래대금/순매수금액, 등락률을 함께 표기하세요.
- 지수/시장별 주체별 순매매대금: 코스피, 코스닥, 선물, 주식선물, 달러선물.
- 데이터가 없는 선물/주식선물/달러선물은 수치를 만들지 말고 "데이터 없음"이라고 적으세요.
"""
    return f"""당신은 텔레그램용 글로벌 시장 데일리 브리프를 쓰는 한국어 애널리스트입니다.
아래 수집 데이터를 바탕으로 3,500자 이내의 매우 컴팩트한 메시지를 작성하세요.

대상 범위: {region}
기준일: {date_title}
{other_instruction}
{korea_instruction}

수집 데이터:
{context}

출력 형식은 아래 포맷을 상황에 맞게 활용하세요.

1) 글로벌 밸류체인 데일리
{date_title} 글로벌 밸류체인 데일리

<한 줄 평>
- 핵심 투자 함의 1문장

주요 지수: 지수 등락률 | 지수 등락률

주요 지수 줄 아래에는 raw data와 뉴스 플로우를 함께 반영해 아래처럼 "•" bullet만 작성하세요.
• CSI300 -0.1%, HSCEI +0.1%로 본토·홍콩 증시 혼조 마감하며 AI 성장주 독주와 전통 경제 섹터 부진이 뚜렷한 K자형 차별화 장세 연출.
• 통신서비스(+4.00%) 섹터는 AI 데이터 트래픽 증가 수혜 기대로 급등하며 시장을 주도, 반면 필수소비재(-1.13%), 산업재(-1.26%) 등 내수 관련주는 약세.
• 인노라이트(+8.28%)와 캠브리콘(+6.49%)은 AI 수요 기반 실적 성장으로 시장 상승을 견인, 하락은 CATL(-3.33%)과 중국농업은행(-0.44%) 주도.

국내 수급 섹션 예시:
수급
• 코스피: 개인 +000억원, 기관 -000억원, 외국인 +000억원. 코스닥: 개인 ..., 기관 ..., 외국인 ...
• 개인 순매수 TOP3: 종목(거래대금, 등락률), 종목(...), 종목(...). 순매도 TOP3: ...
• 기관 순매수 TOP3: ... / 외국인 순매수 TOP3: ...
• 선물: 데이터 없음 | 주식선물: 데이터 없음 | 달러선물: 데이터 없음

Daily Review
• 시장 방향성과 주도/부진 섹터
• 주체별 순매수/순매도 동향
• 환율/ETF/원자재/수급 중 중요한 보조 신호

작성 규칙:
- 텔레그램 메시지로 바로 보낼 수 있게 불필요한 표, 구분선, 출처 목록, 면책문구를 쓰지 마세요.
- 수치는 원자료에 있는 것만 쓰고 만들지 마세요.
- 섹션별 업데이트가 없으면 그 섹션은 생략해도 됩니다.
- "주요 지수:" 아래 설명은 반드시 "•" bullet 형식으로 쓰고, 한 bullet은 한 줄로 짧게 쓰세요.
- "AI 시장 종합 분석 리포트", "Powered by Google Gemini" 같은 시스템 헤더를 절대 쓰지 마세요.
"""


def _clean_response(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if set(stripped) <= {"="}:
            continue
        if stripped == "AI 시장 종합 분석 리포트":
            continue
        if "Powered by Google Gemini" in stripped:
            continue
        lines.append(line.rstrip())
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:3900].rstrip()


def generate_report(context: str, region: str = "all") -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GOOGLE_AI_API_KEY 환경변수가 필요합니다.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": build_prompt(context, region)}]}],
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 4096,
        },
    }
    resp = requests.post(
        url,
        json=payload,
        headers={"x-goog-api-key": GEMINI_API_KEY},
        timeout=120,
    )
    resp.raise_for_status()

    result = resp.json()
    candidates = result.get("candidates") or []
    if not candidates:
        raise ValueError(f"Gemini 응답 없음: {result}")
    parts = candidates[0].get("content", {}).get("parts", [])
    return _clean_response("\n".join(part.get("text", "") for part in parts))
