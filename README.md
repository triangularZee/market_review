# market_review

Compact Telegram-ready market review.

## Modules

1. `modules/korea.py` - Korea market, KRX public data, Naver data, news
2. `modules/us.py` - US stocks and ETFs
3. `modules/other.py` - China, Hong Kong, Japan, Taiwan

Kiwoom is intentionally excluded.

## Environment

Keep secrets in `.env` or environment variables:

```text
GOOGLE_AI_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Telegram variables are only required with `--send-telegram`.

Model and thinking defaults are managed in `gemini_reporter.py` and should flow
to EC2 through `git pull`. Only add these to `.env` when you intentionally need
a server-local override:

```text
GEMINI_MODEL=gemini-3.5-flash
GEMINI_TEMPERATURE=0.35
GEMINI_MAX_OUTPUT_TOKENS=4096
GEMINI_THINKGLEVEL=high
```

`GEMINI_THINKGLEVEL` supports `minimal`, `low`, `medium`, or `high`; leave it
blank to omit `thinkingConfig`. The previous `GEMINI_THINKING_LEVEL` name is
still accepted for backward compatibility.

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

## EC2 Sync Rule

Treat GitHub as the source of truth for code on EC2. Edit code locally, commit,
push, then let EC2 pull it. On EC2, edit only `.env`, crontab, and logs.

Use this sync helper before manual runs or in cron if the EC2 workspace may have
local tracked edits:

```bash
cd /home/ubuntu/market_review
bash scripts/ec2_sync.sh
```

If tracked files were edited on EC2, the helper saves a patch under
`.local_backups/`, restores tracked files to the GitHub version, then runs
`git pull --ff-only origin main`. Backup files and logs are ignored by git.
