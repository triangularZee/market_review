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
    return f"""당신은 텔레그램용 글로벌 시장 데일리 브리프를 쓰는 한국어 애널리스트입니다.
아래 수집 데이터를 바탕으로 3,500자 이내의 매우 컴팩트한 메시지를 작성하세요.

대상 범위: {region}
기준일: {date_title}

수집 데이터:
{context}

출력 형식은 아래 두 포맷을 상황에 맞게 혼합하세요.

1) 글로벌 밸류체인 데일리
{date_title} 글로벌 밸류체인 데일리

<한 줄 평>
- 핵심 투자 함의 1문장

[소재/에너지]
- 기업/산업, 수치, 함의

[산업재]
- 기업/산업, 수치, 함의

[소비재]
- 기업/산업, 수치, 함의

[IT/커뮤니케이션]
- 기업/산업, 수치, 함의

[헬스케어]
- 기업/산업, 수치, 함의

2) 마감시황
SWHY 시장 마감시황
주요 지수: 지수 등락률 | 지수 등락률

주요 상승 섹터: 섹터(+/-%), 섹터(+/-%)
주요 하락 섹터: 섹터(+/-%), 섹터(+/-%)
거래대금: 확인 가능한 합계

Daily Review
* 시장 방향성과 주도/부진 섹터
* 강세 테마와 대표 종목
* 약세 테마와 대표 종목
* 환율/ETF/원자재/수급 중 중요한 보조 신호

작성 규칙:
- 텔레그램 메시지로 바로 보낼 수 있게 불필요한 표, 구분선, 출처 목록, 면책문구를 쓰지 마세요.
- 수치는 원자료에 있는 것만 쓰고 만들지 마세요.
- 섹션별 업데이트가 없으면 그 섹션은 생략해도 됩니다.
- 한 bullet은 한 줄로 짧게 쓰세요.
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
