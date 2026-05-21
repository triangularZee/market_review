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


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "")
GEMINI_TEMPERATURE = float(os.environ.get("GEMINI_TEMPERATURE", "0.35"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "4096"))
GEMINI_THINKGLEVEL = os.environ.get(
    "GEMINI_THINKGLEVEL",
    os.environ.get("GEMINI_THINKING_LEVEL", "high"),
).strip()

REPORT_START_RE = re.compile(
    r"(?m)^\s*\d{2}\.\d{2}\.\d{2}\s+(?:한국|미국|아시아|글로벌)\s+마감시황\s*$"
)
SECTION_START_RE = re.compile(
    r"(?m)^\s*\[(?:한국|미국|아시아|중국|홍콩|일본|대만)\]\s*$"
)


def _format_report_date(report_date: str | None = None) -> str:
    if not report_date:
        return datetime.now().strftime("%y.%m.%d")

    value = report_date.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%y.%m.%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%y.%m.%d")
        except ValueError:
            continue
    raise ValueError("report_date must be YYYY-MM-DD, YYYYMMDD, or YY.MM.DD")


def build_prompt(
    context: str,
    region: str = "all",
    report_date: str | None = None,
) -> str:
    date_title = _format_report_date(report_date)
    title_map = {
        "korea": f"{date_title} 한국 마감시황",
        "us": f"{date_title} 미국 마감시황",
        "other": f"{date_title} 아시아 마감시황",
        "all": f"{date_title} 글로벌 마감시황",
    }
    report_title = title_map.get(region, f"{date_title} 글로벌 마감시황")
    all_instruction = ""
    if region == "all":
        all_instruction = """
전체 리포트는 실행 요약이 아니라 텔레그램 본문이어야 합니다.
반드시 아래 섹션 순서로 작성하세요:
[한국]
[미국]
[아시아]
각 섹션은 해당 지역의 정식 포맷을 유지하고, "Korea", "US", "Other" 같은 모듈명이나 "실행 완료" 문구를 쓰지 마세요.
미국 섹션을 생략하지 마세요. 한국, 미국, 아시아가 모두 있어야 합니다.
"""
    other_instruction = ""
    if region in {"all", "other"}:
        other_instruction = """
그외 시장 리포트는 반드시 국가/지역별로 나누세요:
[중국], [홍콩], [일본], [대만]
각 국가/지역 아래에 주요 지수, 상승/하락 섹터, Daily Review를 2~4개 bullet로 압축하세요.
각 국가/지역의 상승/하락 섹터 바로 아래에 "거래대금 TOP10: 기업명(+/-등락률), ..." 형식으로 <top_value_stocks:국가> 내용을 쓰세요.
중국은 [중국] 섹션 안에서 상해와 심천을 반드시 구분하세요. 거래대금 TOP10은 "상해 거래대금 TOP10", "심천 거래대금 TOP10"으로 나눠 쓰고, Daily Review도 상해 2줄과 심천 2줄을 각각 작성하세요.
중국 Daily Review는 각 시장별로 더 풍부하게 쓰세요. 상해는 대형 가치주·정책·전력/반도체/소재 흐름을, 심천은 성장주·AI 하드웨어·전기차/부품·중소형주 위험선호를 구분해 해석하세요.
홍콩/일본/대만은 각각 독립 섹션으로 유지하세요.
각 국가/지역 섹션마다 반드시 <한 줄 평>을 넣고, 바로 아래 "- ..." 한 문장으로 해당 국가의 핵심 장세를 요약하세요.
한 줄 평은 뉴스플로어와 raw data를 모두 반영해 "AI 반도체 랠리", "환율 부담", "정책 기대", "차익실현", "방어주/전통 섹터 부진"처럼 원인과 결과가 드러나게 쓰세요.
전체 시장을 묶은 한 줄 평이 아니라 국가별 한 줄 평을 각각 작성하세요.
개별 종목 거래대금은 쓰지 마세요. 예: "거래대금: TSMC(...), ..." 같은 줄은 금지합니다.
거래대금은 시장 전체 합계가 원자료에 명확히 있을 때만 1줄로 쓰고, 없으면 생략하세요.
Daily Review는 매 bullet마다 문장 구조를 다르게 쓰세요. 지수 방향, 섹터 확산/쏠림, 정책·매크로·환율·AI/반도체 모멘텀, 차익실현/방어주 흐름을 섞어 해석하세요.
세 bullet 모두 "A와 B가 강세/약세" 식의 종목 나열로 반복하지 마세요.
대만 기업명은 한자 원문 대신 영어명으로 쓰세요. 예: 台積電은 TSMC, 聯發科는 MediaTek, 聯電은 UMC.
"""
    us_instruction = ""
    if region in {"all", "us"}:
        us_instruction = """
미국 리포트도 아시아 리포트처럼 큰 구조를 맞추세요:
- 주요 지수에는 S&P 500, 나스닥, 다우, VIX를 우선 반영하세요.
- 상승/하락 섹터, 거래대금 TOP10, Daily Review를 분리해 쓰세요.
- 거래대금 TOP10은 NASDAQ, NYSE만 각각 나눠 쓰세요. ETF 거래대금 TOP10은 쓰지 마세요.
- Daily Review는 지수 방향, 섹터 확산/쏠림, 금리·달러·원자재·AI/반도체·실적/가이던스 중 중요한 보조 신호를 2~4개 bullet로 압축하세요.
미국 리포트에는 상승/하락 섹터 바로 아래에 "NASDAQ 거래대금 TOP10: 기업명(+/-등락률), ...", "NYSE 거래대금 TOP10: ..." 형식으로 <top_value_stocks:US> 내용을 쓰세요.
"""
    korea_instruction = ""
    if region in {"all", "korea"}:
        korea_instruction = """
국내 리포트에는 아래 수급 정보를 반드시 포함하세요:
- 한국 리포트의 주요 지수에는 코스피, 코스닥, 원/달러 환율 등 한국 관련 지표만 쓰세요. 다우, 나스닥, S&P 500, 니케이, 상해, 항셍 등 해외 지수는 한국 섹션 주요 지수에 쓰지 마세요.
- 코스피/코스닥 개인/기관/외국인 주체별 순매매대금과 선물 개인/기관/외국인 순매매 계약 수.
- 코스피/코스닥 프로그램 매매: 차익, 비차익 순매매대금. 전체 순매매대금은 쓰지 마세요.
- <korea_investor_top5_by_subject_combined> 원자료가 있을 때만 외국인 순매수 TOP5와 순매도 TOP5를 쓰세요. 이 태그가 없으면 TOP5를 절대 쓰지 마세요.
- 국내 통합 외국인 TOP5를 쓸 때는 반드시 "기업명(+1,000억원)" 또는 "기업명(-1,000억원)"처럼 기업명 뒤에 매매대금을 괄호로 적으세요.
- 개인/기관 TOP5는 쓰지 마세요.
- TOP5 원자료가 없으면 "데이터 없음" 줄을 만들지 말고 완전히 생략하세요. 뉴스, 과거 응답, 추정값으로 TOP5를 만들지 마세요.
- 선물/주식선물/달러선물 수급은 원자료에 있을 때만 쓰세요. 없으면 "데이터 없음" 줄을 만들지 말고 생략하세요.
"""
    return f"""당신은 텔레그램용 글로벌 시장 데일리 브리프를 쓰는 한국어 애널리스트입니다.
아래 수집 데이터를 바탕으로 3,500자 이내의 매우 컴팩트한 메시지를 작성하세요.

대상 범위: {region}
기준일: {date_title}
{all_instruction}
{other_instruction}
{us_instruction}
{korea_instruction}

수집 데이터:
{context}

출력 형식은 아래 포맷을 상황에 맞게 활용하세요.

{report_title}

<한 줄 평>
- 핵심 투자 함의 1문장
- 보조 장세 해석 1문장

주요 지수: 
• 지수 등락률
• 지수 등락률

주요 지수 줄 아래에는 raw data와 뉴스 플로우를 함께 반영해 아래처럼 "•" bullet만 작성하세요.
• CSI300 -0.1%, HSCEI +0.1%로 본토·홍콩 증시 혼조 마감하며 AI 성장주 독주와 전통 경제 섹터 부진이 뚜렷한 K자형 차별화 장세 연출.
• 통신서비스(+4.00%) 섹터는 AI 데이터 트래픽 증가 수혜 기대로 급등하며 시장을 주도, 반면 필수소비재(-1.13%), 산업재(-1.26%) 등 내수 관련주는 약세.
• 인노라이트(+8.28%)와 캠브리콘(+6.49%)은 AI 수요 기반 실적 성장으로 시장 상승을 견인, 하락은 CATL(-3.33%)과 중국농업은행(-0.44%) 주도.

국내 수급 섹션 예시:
수급
• 코스피: 개인 +000억원, 기관 -000억원, 외국인 +000억원. 
• 코스닥: 개인 ..., 기관 ..., 외국인 ... 
• 선물: 개인 +000계약, 기관 ..., 외국인 ...
• 프로그램:
- 코스피 차익/비차익 ...
- 코스닥 차익/비차익 ...
• 국내 통합 외국인 순매수 TOP5: 종목(거래대금), 종목(...). 순매도 TOP5: ...

Daily Review
• CSI300 -0.1%, HSCEI +0.1%로 본토·홍콩 증시 혼조 마감하며 AI 성장주 독주와 전통 경제 섹터 부진이 뚜렷한 K자형 차별화 장세 연출.
• 통신서비스(+4.00%) 섹터는 AI 데이터 트래픽 증가 수혜 기대로 급등하며 시장을 주도, 반면 필수소비재(-1.13%), 산업재(-1.26%) 등 내수 관련주는 약세.
• 인노라이트(+8.28%)와 캠브리콘(+6.49%)은 AI 수요 기반 실적 성장으로 시장 상승을 견인, 하락은 CATL(-3.33%)과 중국농업은행(-0.44%) 주도.

작성 규칙:
- 텔레그램 메시지로 바로 보낼 수 있게 불필요한 표, 구분선, 출처 목록, 면책문구를 쓰지 마세요.
- 첫 줄 제목은 반드시 "{report_title}"로 쓰세요.
- <한 줄 평> 아래 문장은 모두 "- "로 시작하세요. bullet 없이 평문으로 쓰지 마세요.
- 수치는 원자료에 있는 것만 쓰고 만들지 마세요.
- 수급 숫자나 TOP5를 뉴스 기반 추정값으로 만들지 마세요. 원자료가 없으면 해당 항목을 생략하세요.
- 사용자에게 "어떤 수치가 안 맞는지 알려달라", "원인 파악이 빠르다" 같은 질문이나 진단 문구를 쓰지 마세요. 리포트 본문만 쓰세요.
- Daily Review에 "시장 방향성과 주도/부진 섹터", "주체별 순매수/순매도 동향", "환율/ETF/원자재/수급 중 중요한 보조 신호" 같은 템플릿 문구를 그대로 쓰지 마세요.
- 특정 기업명을 언급할 때는 반드시 "기업명(+1.23%)" 또는 "기업명(-1.23%)"처럼 등락률을 괄호 안에 함께 쓰세요.
- 단, 국내 통합 외국인 순매수/순매도 TOP5는 등락률 대신 매매대금을 괄호 안에 쓰세요. 기업명만 나열하지 마세요.
- 등락률 원자료가 없는 기업은 개별 기업명 대신 섹터/테마로 표현하세요.
- 섹션별 업데이트가 없으면 그 섹션은 생략해도 됩니다.
- "주요 지수:" 아래 설명은 반드시 "•" bullet 형식으로 쓰고, 한 bullet은 한 줄로 짧게 쓰세요.
- "AI 시장 종합 분석 리포트", "Powered by Google Gemini" 같은 시스템 헤더를 절대 쓰지 마세요.
- "스크립트가 성공적으로 완료되었습니다", "아래는 오늘 시황 요약입니다", "텔레그램으로 전송되었습니다" 같은 실행 상태 안내문을 절대 쓰지 마세요.
- "실행 완료했습니다", "로그 일부 출력이 잘렸지만", "정상 수집되었습니다" 같은 작업 로그를 절대 쓰지 마세요.
- "**Korea**", "**US**", "**Other**" 같은 영어 모듈명으로 섹션을 만들지 마세요. 반드시 [한국], [미국], [아시아] 또는 [중국]처럼 한국어 섹션명을 쓰세요.
- "---" 같은 구분선, 마크다운 코드펜스, 완료/성공/전송 안내 문장은 리포트 본문이 아니므로 쓰지 마세요.
"""


def _clean_response(text: str, allow_korea_top5: bool = True) -> str:
    start_match = REPORT_START_RE.search(text) or SECTION_START_RE.search(text)
    if start_match:
        text = text[start_match.start() :]

    lines = []
    banned_fragments = [
        "all numbers match",
        "let's structure",
        "raw data:",
        "스크립트가 성공적으로 완료",
        "아래는 오늘",
        "아래는 금일",
        "시황 요약입니다",
        "텔레그램으로",
        "전송되었습니다",
        "전송 완료",
        "성공적으로 완료",
        "실행 완료",
        "로그 일부",
        "정상 수집",
        "정상적으로 수집",
        "아래는",
        "뉴스 기반 추정",
        "추정값",
        "어떤 수치가 안 맞는지",
        "구체적으로 알려주시면",
        "원인 파악",
        "확인해드리겠습니다",
        "script completed",
        "successfully completed",
        "sent to telegram",
    ]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if set(stripped) <= {"=", "-", "_"}:
            continue
        if stripped.startswith("```"):
            continue
        if stripped == "AI 시장 종합 분석 리포트":
            continue
        if "Powered by Google Gemini" in stripped:
            continue
        if stripped.startswith(("**Korea", "**US", "**Other", "Korea (", "US (", "Other (")):
            continue
        if "국내 통합 외국인" in stripped and "TOP5" in stripped and not allow_korea_top5:
            continue
        lowered = stripped.lower()
        if any(fragment.lower() in lowered for fragment in banned_fragments):
            continue
        lines.append(line.rstrip())
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.rstrip()


def generate_report(
    context: str,
    region: str = "all",
    report_date: str | None = None,
) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GOOGLE_AI_API_KEY 환경변수가 필요합니다.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    generation_config = {
        "temperature": GEMINI_TEMPERATURE,
        "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
    }
    if GEMINI_THINKGLEVEL:
        generation_config["thinkingConfig"] = {
            "thinkingLevel": GEMINI_THINKGLEVEL,
        }

    payload = {
        "contents": [{"parts": [{"text": build_prompt(context, region, report_date)}]}],
        "generationConfig": generation_config,
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
    visible_text = "\n".join(
        part.get("text", "") for part in parts if not part.get("thought")
    )
    return _clean_response(
        visible_text,
        allow_korea_top5="<korea_investor_top5_by_subject_combined>" in context,
    )
