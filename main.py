"""Market review runner.

Modules:
  1. Korea
  2. US
  3. Other markets
"""

from __future__ import annotations

import argparse

from gemini_reporter import generate_report
from modules import korea, other, us


def collect_context(region: str, include_krx: bool, include_news: bool) -> str:
    sections = []

    if region in {"all", "korea"}:
        print("[1/3] 한국 데이터 수집")
        sections.append(korea.summarize_for_prompt(korea.collect(include_krx, include_news)))

    if region in {"all", "us"}:
        print("[2/3] 미국 데이터 수집")
        sections.append(us.summarize_for_prompt(us.collect(include_news)))

    if region in {"all", "other"}:
        print("[3/3] 그외 시장 데이터 수집")
        sections.append(other.summarize_for_prompt(other.collect(include_news)))

    return "\n\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compact market review for Telegram")
    parser.add_argument(
        "--region",
        choices=["all", "korea", "us", "other"],
        default="all",
        help="수집/분석 대상",
    )
    parser.add_argument("--no-krx", action="store_true", help="한국 KRX 수급 수집 제외")
    parser.add_argument("--no-news", action="store_true", help="한국 뉴스 수집 제외")
    parser.add_argument("--send-telegram", action="store_true", help="Telegram으로 전송")
    parser.add_argument("--print-context", action="store_true", help="Gemini 입력 컨텍스트만 출력")
    args = parser.parse_args()

    context = collect_context(
        region=args.region,
        include_krx=not args.no_krx,
        include_news=not args.no_news,
    )

    if args.print_context:
        print(context)
        return

    report = generate_report(context, args.region)
    print("\n" + report)

    if args.send_telegram:
        from telegram_sender import send_telegram

        send_telegram(report)
        print("\n[telegram] sent")


if __name__ == "__main__":
    main()
