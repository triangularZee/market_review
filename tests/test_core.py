import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import env_loader
import gemini_reporter
from global_market_analyzer import _signed_taiwan_change, _valid_taiwan_ranking
from gemini_reporter import _clean_response, _format_report_date
from news_scraper import _dated_news_query, select_market_news
from modules.korea import _korea_market_date
from modules.us import _us_market_date
from modules.other import (
    _intraday_index_facts,
    _is_close_report,
    _news_matches_market,
    _rank_country_news,
)
from modules.other import summarize_for_prompt as summarize_other
from telegram_sender import split_telegram


class FakeGeminiResponse:
    def __init__(self, status_code: int, text: str = "26.05.21 한국 마감시황"):
        self.status_code = status_code
        self._text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": self._text,
                            }
                        ]
                    }
                }
            ]
        }


class CoreHelpersTest(unittest.TestCase):
    def test_split_telegram_keeps_chunks_under_limit(self):
        chunks = split_telegram("a" * 5000 + "\n" + "b" * 10)

        self.assertEqual([len(chunk) for chunk in chunks], [3900, 1100, 10])
        self.assertTrue(all(len(chunk) <= 3900 for chunk in chunks))

    def test_clean_response_removes_gemini_preamble(self):
        text = """raw data: 1,899,300,000,000
All numbers match the raw data perfectly.
Let's structure the output exactly as requested.

26.05.21 한국 마감시황

<한 줄 평>
- 테스트 문장
"""

        self.assertEqual(
            _clean_response(text),
            "26.05.21 한국 마감시황\n\n<한 줄 평>\n- 테스트 문장",
        )

    def test_report_date_formats_supported_inputs(self):
        self.assertEqual(_format_report_date("2026-05-21"), "26.05.21")
        self.assertEqual(_format_report_date("20260521"), "26.05.21")
        self.assertEqual(_format_report_date("26.05.21"), "26.05.21")

    def test_env_loader_overrides_non_empty_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "SAMPLE_KEY=from_file\nEMPTY_VALUE=\n#COMMENT=ignored\n",
                encoding="utf-8",
            )
            with patch.object(env_loader.Path, "resolve", return_value=Path(tmp) / "env_loader.py"):
                os.environ["SAMPLE_KEY"] = "from_env"
                try:
                    env_loader.load_repo_env()
                    self.assertEqual(os.environ["SAMPLE_KEY"], "from_file")
                    self.assertNotIn("EMPTY_VALUE", os.environ)
                finally:
                    os.environ.pop("SAMPLE_KEY", None)
                    os.environ.pop("EMPTY_VALUE", None)

    def test_gemini_retries_retryable_status(self):
        with (
            patch.object(gemini_reporter, "GEMINI_API_KEY", "key"),
            patch.object(gemini_reporter, "GEMINI_MODEL", "gemini-3.8-flash"),
            patch.object(gemini_reporter, "GEMINI_FALLBACK_MODELS", []),
            patch.object(gemini_reporter, "GEMINI_MAX_RETRIES", 1),
            patch.object(gemini_reporter, "GEMINI_RETRY_SLEEP_SECONDS", 0),
            patch.object(
                gemini_reporter.requests,
                "post",
                side_effect=[
                    FakeGeminiResponse(503),
                    FakeGeminiResponse(200),
                ],
            ) as post,
            patch.object(gemini_reporter.time, "sleep"),
        ):
            report = gemini_reporter.generate_report("context", "korea", "2026-05-21")

        self.assertIn("26.05.21", report)
        self.assertEqual(post.call_count, 2)

    def test_gemini_falls_back_on_model_404(self):
        with (
            patch.object(gemini_reporter, "GEMINI_API_KEY", "key"),
            patch.object(gemini_reporter, "GEMINI_MODEL", "gemini-3.8-flash"),
            patch.object(gemini_reporter, "GEMINI_FALLBACK_MODELS", ["gemini-3.5-flash"]),
            patch.object(gemini_reporter, "GEMINI_MAX_RETRIES", 0),
            patch.object(
                gemini_reporter.requests,
                "post",
                side_effect=[
                    FakeGeminiResponse(404),
                    FakeGeminiResponse(200),
                ],
            ) as post,
        ):
            report = gemini_reporter.generate_report("context", "korea", "2026-05-21")

        self.assertIn("26.05.21", report)
        self.assertEqual(post.call_count, 2)
        fallback_payload = post.call_args_list[1].kwargs["json"]
        self.assertEqual(
            fallback_payload["generationConfig"]["thinkingConfig"],
            {"thinkingLevel": "medium"},
        )
        self.assertNotIn("temperature", fallback_payload["generationConfig"])

    def test_gemini_38_uses_medium_thinking_without_temperature(self):
        with patch.object(gemini_reporter, "GEMINI_THINKGLEVEL", "medium"):
            config = gemini_reporter._generation_config_for_model("gemini-3.8-flash")

        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "medium"})
        self.assertNotIn("temperature", config)

    def test_invalid_cnyes_taiwan_ranking_triggers_fallback(self):
        import pandas as pd

        ranking = pd.DataFrame(
            {
                "종목명": [float("nan")],
                "거래대금(TWD)": [float("nan")],
                "등락": [float("nan")],
            }
        )

        self.assertFalse(_valid_taiwan_ranking(ranking))

    def test_taiwan_change_applies_twse_html_sign(self):
        self.assertEqual(_signed_taiwan_change("<p style= color:green>-</p>", "15.00"), "-15.00")
        self.assertEqual(_signed_taiwan_change("<p style= color:red>+</p>", "3.00"), "3.00")

    def test_news_query_uses_recent_window(self):
        self.assertEqual(_dated_news_query("Taiwan stocks"), "(Taiwan stocks) when:3d")

    def test_news_query_uses_report_date_window(self):
        self.assertEqual(
            _dated_news_query("Taiwan stocks", "2026-08-28"),
            "(Taiwan stocks) after:2026-08-27 before:2026-08-29",
        )

    def test_common_news_selector_requires_same_day(self):
        articles = [
            {
                "title": "Wall Street ends higher as chip shares rally",
                "source": "Reuters",
                "published_date": "2026-09-02",
            },
            {
                "title": "Wall Street ends lower as chip shares slide",
                "source": "Reuters",
                "published_date": "2026-09-03",
            },
        ]

        selected = select_market_news(
            articles,
            ["wall street"],
            ["Reuters"],
            "2026-09-03",
            direction=-1,
        )

        self.assertEqual(len(selected), 1)
        self.assertIn("ends lower", selected[0]["title"])

    def test_common_news_selector_rejects_untrusted_background_story(self):
        selected = select_market_news(
            [{
                "title": "Semiconductor stocks face a complicated outlook",
                "source": "Example Blog",
                "published_date": "2026-09-03",
            }],
            ["semiconductor"],
            ["Reuters"],
            "2026-09-03",
        )

        self.assertEqual(selected, [])

    def test_common_news_selector_does_not_partially_match_source(self):
        selected = select_market_news(
            [{
                "title": "Wall Street gains as yields ease",
                "source": "CNBC TV18",
                "published_date": "2026-09-03",
            }],
            ["wall street"],
            ["CNBC"],
            "2026-09-03",
        )

        self.assertEqual(selected, [])

    def test_common_news_selector_rejects_bare_stock_quote(self):
        selected = select_market_news(
            [{
                "title": "SK하이닉스(000660) - 매일경제 마켓",
                "source": "매일경제 마켓",
                "published_date": "2026-09-03",
            }],
            ["sk하이닉스"],
            ["매일경제 마켓"],
            "2026-09-03",
        )

        self.assertEqual(selected, [])

    def test_explicit_market_dates_are_normalized(self):
        self.assertEqual(_us_market_date("20260903"), "2026-09-03")
        self.assertEqual(_korea_market_date("26.09.03", {}), "2026-09-03")

    def test_market_news_rejects_opposite_direction(self):
        terms = ["taiwan", "taiex"]
        self.assertFalse(_news_matches_market("Taiwan stocks rise at close", terms, -1))
        self.assertTrue(_news_matches_market("Taiwan stocks fall at close", terms, -1))

    def test_market_news_rejects_low_signal_page(self):
        self.assertFalse(
            _news_matches_market("TSMC Stock Price — TSMC Chart", ["tsmc"], -1)
        )

    def test_market_news_rejects_wrong_trading_date(self):
        self.assertFalse(
            _news_matches_market(
                "Taiwan stocks fall at close",
                ["taiwan"],
                -1,
                published_date="2026-08-31",
                market_date="2026-08-28",
            )
        )

    def test_market_news_rejects_mismatched_taiex_change(self):
        self.assertFalse(
            _news_matches_market(
                "Taiwan Stocks Decline as TAIEX Slips 1.57% at Close",
                ["taiwan", "taiex"],
                -1,
                published_date="2026-09-03",
                market_date="2026-09-03",
                market_change_pct=-0.67,
            )
        )

    def test_market_news_rejects_cross_country_headline(self):
        self.assertFalse(
            _news_matches_market(
                "Mainland Chinese investors buy Hong Kong AI stocks",
                ["china", "chinese"],
                0,
                excluded_terms=["hong kong", "hang seng"],
            )
        )

    def test_other_context_marks_missing_news_evidence(self):
        import pandas as pd

        context = summarize_other(
            {"global_indicators": pd.DataFrame(), "markets": {}, "news": {}}
        )

        self.assertIn("<news_evidence:대만> 없음", context)

    def test_country_news_prioritizes_major_same_day_source(self):
        articles = [
            {
                "title": "Taiwan stocks fall at close",
                "source": "Example Blog",
                "published_date": "2026-09-03",
            },
            {
                "title": "TSMC weakness weighs on Taiwan shares at close",
                "source": "Reuters",
                "published_date": "2026-09-03",
            },
        ]

        ranked = _rank_country_news(articles, "대만", "2026-09-03")

        self.assertEqual(ranked[0]["source"], "Reuters")

    def test_intraday_facts_use_ohlc_without_inventing_timestamps(self):
        import pandas as pd

        indicators = pd.DataFrame([{
            "종목명": "상해종합",
            "코드": ".SSEC",
            "전일종가": "4,000.00",
            "시가": "4,020.00",
            "고가": "4,040.00",
            "저가": "3,920.00",
            "현재가": "4,000.00",
        }])

        facts = _intraday_index_facts("중국", indicators)

        self.assertEqual(len(facts), 1)
        self.assertIn("시가 4,020.00(+0.50%)", facts[0])
        self.assertIn("장중 저가 3,920.00(-2.00%)", facts[0])
        self.assertIn("저점 대비 종가 +2.04%", facts[0])
        self.assertNotIn("오전", facts[0])

    def test_close_report_does_not_match_business_closure(self):
        self.assertFalse(
            _is_close_report({"title": "China's biggest lithium mine closes again"})
        )
        self.assertTrue(
            _is_close_report({"title": "China stocks end flat after mixed session"})
        )


if __name__ == "__main__":
    unittest.main()
