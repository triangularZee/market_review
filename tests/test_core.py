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
from news_scraper import _dated_news_query
from modules.other import _news_matches_market
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
            patch.object(gemini_reporter, "GEMINI_MODEL", "gemini-3.5-flash"),
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
            patch.object(gemini_reporter, "GEMINI_MODEL", "gemini-3.5-flash"),
            patch.object(gemini_reporter, "GEMINI_FALLBACK_MODELS", ["gemini-2.5-flash"]),
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
        self.assertNotIn("thinkingConfig", fallback_payload["generationConfig"])

    def test_gemini_35_uses_medium_thinking(self):
        with patch.object(gemini_reporter, "GEMINI_THINKGLEVEL", "medium"):
            config = gemini_reporter._generation_config_for_model("gemini-3.5-flash")

        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "medium"})

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

    def test_other_context_marks_missing_news_evidence(self):
        import pandas as pd

        context = summarize_other(
            {"global_indicators": pd.DataFrame(), "markets": {}, "news": {}}
        )

        self.assertIn("<news_evidence:대만> 없음", context)


if __name__ == "__main__":
    unittest.main()
