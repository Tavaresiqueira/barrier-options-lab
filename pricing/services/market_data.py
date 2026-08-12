import re
from dataclasses import dataclass

import requests


class MarketDataError(Exception):
    pass


def yahoo_symbol(identifier):
    value = str(identifier).strip().upper()
    bloomberg_match = re.fullmatch(r"([A-Z0-9]+)\s+BZ\s+EQUITY", value)
    if bloomberg_match:
        return f"{bloomberg_match.group(1)}.SA"
    if re.fullmatch(r"[A-Z0-9]+", value):
        return f"{value}.SA"
    if re.fullmatch(r"[A-Z0-9]+\.SA", value):
        return value
    raise MarketDataError(
        "Use a B3 ticker such as PETR4, PETR4.SA, or PETR4 BZ Equity."
    )


@dataclass
class YahooFinanceClient:
    base_url: str = "https://query1.finance.yahoo.com"
    timeout: int = 20

    def chart(self, symbol):
        try:
            response = requests.get(
                f"{self.base_url.rstrip('/')}/v8/finance/chart/{symbol}",
                params={"range": "5d", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise MarketDataError(f"Yahoo Finance request failed: {exc}") from None
        except ValueError:
            raise MarketDataError("Yahoo Finance returned invalid JSON.") from None

        chart = payload.get("chart", {})
        if chart.get("error"):
            description = chart["error"].get("description", "unknown error")
            raise MarketDataError(f"Yahoo Finance error: {description}")
        results = chart.get("result")
        if not results:
            raise MarketDataError(f"Yahoo Finance returned no data for {symbol}.")
        return results[0]


def option_chain(underlying):
    symbol = yahoo_symbol(underlying)
    result = YahooFinanceClient().chart(symbol)
    meta = result.get("meta", {})
    currency = str(meta.get("currency", "")).upper()
    if currency != "BRL":
        raise MarketDataError("Version one supports only BRL underlyings.")
    spot = meta.get("regularMarketPrice")
    if spot is None:
        raise MarketDataError(f"Yahoo Finance returned no current price for {symbol}.")

    return {
        "identifier": str(underlying).strip(),
        "yahoo_symbol": symbol,
        "security_name": meta.get("longName") or meta.get("shortName") or symbol,
        "data": [],
        "underlying_px_last": float(spot),
        "currency": currency,
        "currency_px_last": 1.0,
        "px_pos_mult_factor": 1.0,
        "dividend_yield": None,
        "source": {
            "provider": "Yahoo Finance",
            "endpoint": "chart",
            "note": "Listed option chains are intentionally not loaded; structure parameters remain user-defined.",
        },
    }


def option_quotes(tickers):
    rows = []
    for ticker in tickers:
        symbol = yahoo_symbol(ticker)
        meta = YahooFinanceClient().chart(symbol).get("meta", {})
        if meta.get("regularMarketPrice") is None:
            raise MarketDataError(f"Yahoo Finance returned no current price for {symbol}.")
        rows.append({
            "ticker": str(ticker).strip(),
            "yahoo_symbol": symbol,
            "px_last": float(meta["regularMarketPrice"]),
            "currency": meta.get("currency"),
        })
    return {"data": rows, "source": {"provider": "Yahoo Finance", "endpoint": "chart"}}
