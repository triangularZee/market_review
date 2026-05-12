"""Formatting helpers for prompt context."""

from __future__ import annotations

import pandas as pd


def _format_numeric(value, decimals: int = 0, signed: bool = False) -> str:
    try:
        number = float(str(value).replace(",", "").replace("%", "").strip())
    except Exception:
        return str(value)
    sign = "+" if signed and number > 0 else ""
    if decimals <= 0:
        return f"{sign}{number:,.0f}"
    return f"{sign}{number:,.{decimals}f}"


def _format_text_number(value, decimals: int = 2, signed: bool = False) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return text
    marker = ""
    body = text
    if body[0] in {"▲", "▼"}:
        marker = f"{body[0]} "
        body = body[1:].strip()
    if body.startswith(("+", "-")):
        signed = False
    return f"{marker}{_format_numeric(body, decimals=decimals, signed=signed)}"


def format_prompt_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a display-only copy with comma-formatted major scraped numbers."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    formatted = df.copy()
    for col in formatted.columns:
        name = str(col)
        if name in {"등락률", "등락률(%)", "1개월수익률", "3개월수익률"}:
            formatted[col] = formatted[col].map(lambda value: _format_text_number(value, decimals=2, signed=True))
        elif name in {"현재가", "전일대비", "시가", "고가", "저가", "종가", "매매기준율"}:
            formatted[col] = formatted[col].map(lambda value: _format_text_number(value, decimals=2))
        elif any(token in name for token in ["거래대금", "거래량", "시가총액", "순매수", "상승", "하락", "보합"]):
            formatted[col] = formatted[col].map(lambda value: _format_text_number(value, decimals=0))
    return formatted


def format_index_item(row: pd.Series) -> str:
    name = row.get("종목명", "")
    pct = _format_text_number(row.get("등락률(%)", ""), decimals=2, signed=True)
    price = _format_text_number(row.get("현재가", ""), decimals=2)
    return f"{name} {pct}%({price})"
