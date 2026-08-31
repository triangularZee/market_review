"""시장 뉴스 및 배경 정보 수집 모듈

소스:
  1. 네이버 증권 뉴스 (RSS + 페이지 스크래핑)
  2. 주요 경제 뉴스 헤드라인 (Google News RSS)
  3. 네이버 증권 시장 지표 (투자자 심리 보조)
"""

import re
import xml.etree.ElementTree as ET
from html import unescape
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests
import pandas as pd
from bs4 import BeautifulSoup

from config import NAVER_HEADERS


# ═══════════════════════════════════════════════════════════
# 1. 네이버 증권 뉴스
# ═══════════════════════════════════════════════════════════

def fetch_naver_finance_news(category: str = "market") -> list[dict]:
    """네이버 증권 시장 뉴스 헤드라인 수집

    category: "market" (시황), "stock" (종목), "world" (해외증시)
    """
    cat_map = {
        "market": "shg",
        "stock": "stk",
        "world": "wld",
    }
    cat_code = cat_map.get(category, "shg")
    url = f"https://finance.naver.com/news/news_list.naver?mode=LSS3D&section_id=101&section_id2=258&section_id3={cat_code}"

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articles = []
        for anchor in soup.select("dd.articleSubject a[href]"):
            link = anchor.get("href", "")
            title = anchor.get("title") or anchor.get_text(" ", strip=True)
            if not title:
                continue
            articles.append({
                "title": unescape(title).strip(),
                "link": f"https://finance.naver.com{link}" if link.startswith("/") else link,
                "source": "네이버증권",
                "category": category,
            })

        return articles[:15]
    except Exception:
        return []


def fetch_naver_stock_news_api() -> list[dict]:
    """네이버 증권 API 기반 뉴스 수집 (stock.naver.com)"""
    urls = [
        "https://stock.naver.com/api/news/domestic?page=1&pageSize=10",
        "https://stock.naver.com/api/news/world?page=1&pageSize=10",
    ]
    articles = []
    for url in urls:
        try:
            resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("items", data.get("news", []))
                for item in items[:10]:
                    articles.append({
                        "title": item.get("title", item.get("headline", "")),
                        "link": item.get("link", item.get("url", "")),
                        "source": "네이버증권API",
                        "category": "api",
                    })
        except Exception:
            continue
    return articles


# ═══════════════════════════════════════════════════════════
# 2. Google News RSS (한국 경제/증시 뉴스)
# ═══════════════════════════════════════════════════════════

def _parse_report_date(report_date: str | None) -> datetime | None:
    if not report_date:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%y.%m.%d"):
        try:
            return datetime.strptime(report_date.strip(), fmt)
        except ValueError:
            continue
    raise ValueError("report_date must be YYYY-MM-DD, YYYYMMDD, or YY.MM.DD")


def _dated_news_query(query: str, report_date: str | None = None) -> str:
    target = _parse_report_date(report_date)
    if target is None:
        return f"({query}) when:3d"
    start = (target - timedelta(days=1)).strftime("%Y-%m-%d")
    end = (target + timedelta(days=1)).strftime("%Y-%m-%d")
    return f"({query}) after:{start} before:{end}"


def fetch_google_news_rss(
    query: str,
    num: int = 10,
    report_date: str | None = None,
    locale: str = "ko-KR",
) -> list[dict]:
    """Google News RSS로 특정 주제 뉴스 수집"""
    encoded = quote(_dated_news_query(query, report_date))
    if locale == "en-US":
        locale_query = "hl=en-US&gl=US&ceid=US:en"
    else:
        locale_query = "hl=ko&gl=KR&ceid=KR:ko"
    url = f"https://news.google.com/rss/search?q={encoded}&{locale_query}"

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        articles = []
        for item in root.findall(".//item")[:num]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            try:
                published_date = parsedate_to_datetime(pub_date).date().isoformat()
            except (TypeError, ValueError):
                published_date = ""
            articles.append({
                "title": title,
                "link": link,
                "source": source,
                "date": pub_date,
                "published_date": published_date,
                "category": query,
            })
        return articles
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════
# 3. 주제별 배경 뉴스 수집
# ═══════════════════════════════════════════════════════════

SEARCH_TOPICS = {
    "시장_종합": "코스피 시황 오늘",
    "외국인_수급": "외국인 매매동향 코스피",
    "반도체": "반도체 삼성전자 SK하이닉스 주가",
    "미중_무역": "미중 무역 관세 협상",
    "FOMC_연준": "FOMC 금리 연준 통화정책",
    "환율": "원달러 환율 원화",
    "원자재": "유가 금값 원자재 시세",
    "업종_로테이션": "코스피 업종 섹터 주도주",
    "방산_조선": "방산주 조선주 동향",
    "정책_밸류업": "밸류업 상법개정 증시 정책",
    "AI_슈퍼사이클": "AI 반도체 HBM 슈퍼사이클",
    "글로벌_증시": "S&P500 나스닥 미국증시",
}


def fetch_all_topic_news(
    topics: dict | None = None,
    report_date: str | None = None,
    locale: str = "ko-KR",
) -> dict[str, list[dict]]:
    """모든 주제에 대해 뉴스를 수집"""
    if topics is None:
        topics = SEARCH_TOPICS

    results = {}
    for key, query in topics.items():
        print(f"  뉴스 수집: [{key}] {query}...")
        articles = fetch_google_news_rss(
            query,
            num=8,
            report_date=report_date,
            locale=locale,
        )
        results[key] = articles

    return results


# ═══════════════════════════════════════════════════════════
# 4. 뉴스 요약 및 키워드 추출
# ═══════════════════════════════════════════════════════════

def extract_headline_keywords(articles: list[dict]) -> list[str]:
    """뉴스 헤드라인에서 핵심 키워드 추출"""
    all_text = " ".join(a.get("title", "") for a in articles)
    # 한글 단어 추출 (2글자 이상)
    words = re.findall(r"[가-힣]{2,}", all_text)

    # 빈도수 계산
    freq = {}
    stopwords = {"오늘", "내일", "이번", "지난", "것으로", "등이", "에서", "으로",
                 "대한", "관련", "위한", "통해", "이상", "이하", "중인"}
    for w in words:
        if w not in stopwords and len(w) >= 2:
            freq[w] = freq.get(w, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, c in sorted_words[:20]]


def generate_news_context(topic_news: dict) -> dict[str, str]:
    """주제별 뉴스를 분석하여 배경 컨텍스트 텍스트 생성"""
    context = {}

    for topic, articles in topic_news.items():
        if not articles:
            continue

        headlines = [a["title"] for a in articles[:5]]
        keywords = extract_headline_keywords(articles)

        lines = []
        lines.append(f"  최신 뉴스 ({len(articles)}건):")
        for i, h in enumerate(headlines[:5], 1):
            source = articles[i - 1].get("source", "")
            src_tag = f" [{source}]" if source else ""
            lines.append(f"    {i}. {h}{src_tag}")

        if keywords:
            lines.append(f"  핵심 키워드: {', '.join(keywords[:8])}")

        context[topic] = "\n".join(lines)

    return context


# ═══════════════════════════════════════════════════════════
# 5. 통합 수집
# ═══════════════════════════════════════════════════════════

def collect_all_news(report_date: str | None = None) -> dict:
    """전체 뉴스 및 배경 정보 수집"""
    print("\n[뉴스] 시장 동향 및 배경 정보 수집 중...")

    result = {
        "naver_market": [],
        "naver_stock": [],
        "naver_world": [],
        "naver_api": [],
        "topics": {},
        "context": {},
    }

    # 네이버 증권 뉴스
    print("  네이버 증권 뉴스 수집 중...")
    result["naver_market"] = fetch_naver_finance_news("market")
    result["naver_stock"] = fetch_naver_finance_news("stock")
    result["naver_world"] = fetch_naver_finance_news("world")
    result["naver_api"] = fetch_naver_stock_news_api()

    # 주제별 배경 뉴스 (Google News RSS)
    print("  주제별 배경 뉴스 수집 중...")
    result["topics"] = fetch_all_topic_news(report_date=report_date)

    # 컨텍스트 생성
    print("  배경 컨텍스트 생성 중...")
    result["context"] = generate_news_context(result["topics"])

    total = sum(len(v) for v in result["topics"].values())
    total += len(result["naver_market"]) + len(result["naver_stock"]) + len(result["naver_world"])
    print(f"[뉴스] 수집 완료 — 총 {total}건")

    return result


if __name__ == "__main__":
    data = collect_all_news()

    print("\n" + "=" * 60)
    print("  뉴스 수집 결과 요약")
    print("=" * 60)

    print(f"\n  네이버 시황: {len(data['naver_market'])}건")
    for a in data["naver_market"][:5]:
        print(f"    · {a['title']}")

    print(f"\n  네이버 종목: {len(data['naver_stock'])}건")
    for a in data["naver_stock"][:5]:
        print(f"    · {a['title']}")

    print(f"\n  네이버 해외: {len(data['naver_world'])}건")
    for a in data["naver_world"][:5]:
        print(f"    · {a['title']}")

    print("\n  ─── 주제별 배경 뉴스 ───")
    for topic, articles in data["topics"].items():
        print(f"\n  [{topic}] {len(articles)}건")
        for a in articles[:3]:
            print(f"    · {a['title']}")

    print("\n  ─── 배경 컨텍스트 ───")
    for topic, ctx in data["context"].items():
        print(f"\n  [{topic}]")
        print(ctx)
