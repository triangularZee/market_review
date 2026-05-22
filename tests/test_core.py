import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import env_loader
from gemini_reporter import _clean_response, _format_report_date
from telegram_sender import split_telegram


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


if __name__ == "__main__":
    unittest.main()
