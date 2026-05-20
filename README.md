# market_review

Compact Telegram-ready market review.

## Modules

1. `modules/korea.py` - Korea market, KRX public data, Naver data, news
2. `modules/us.py` - US stocks and ETFs
3. `modules/other.py` - China, Hong Kong, Japan, Taiwan

Kiwoom is intentionally excluded.

## Environment

Create `.env` or set environment variables:

```text
GOOGLE_AI_API_KEY=...
GEMINI_MODEL=gemini-3.5-flash
GEMINI_TEMPERATURE=0.35
GEMINI_MAX_OUTPUT_TOKENS=4096
GEMINI_THINKING_LEVEL=low
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Telegram variables are only required with `--send-telegram`.
`GEMINI_THINKING_LEVEL` is optional. For Gemini 3-series Flash models, use
`minimal`, `low`, `medium`, or `high`; leave it blank to omit
`thinkingConfig`.

## Run

```bash
pip install -r requirements.txt
python main.py --region all
python main.py --region korea
python main.py --region us
python main.py --region other
python main.py --region all --send-telegram
```

For cron on a host that runs multiple Telegram bots, run from this repository
directory and keep this repo's `.env` populated. Non-empty values in `.env`
override inherited cron/service environment variables, so the current bot token
is used even if the host has an older `TELEGRAM_BOT_TOKEN` exported.
