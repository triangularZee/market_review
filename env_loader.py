"""Small .env loader used by runtime entrypoints.

Non-empty values in the repository .env intentionally override inherited
environment variables. This keeps cron jobs on shared EC2 hosts pointed at this
project's own Telegram bot and API keys.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_repo_env(override: bool = True) -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
