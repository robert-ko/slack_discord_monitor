#!/usr/bin/env python3
"""
Get VWAP directly from TradingView's screener (unofficial API) for one or many symbols.

This uses the `tradingview_ta` library, which queries TradingView's
technical-analysis endpoint and exposes built-in indicators, including VWAP.

Usage examples
  # Single symbol
  python tv_vwap_scanner.py -s AAPL -e NASDAQ -r america
  # Multiple symbols (repeat -s)
  python tv_vwap_scanner.py -s AAPL -s MSFT -e NASDAQ --interval 1m
  # Multiple via comma-separated list
  python tv_vwap_scanner.py --symbols AAPL,MSFT,GOOGL -e NASDAQ -r america --json
  # CSV output to stdout
  python tv_vwap_scanner.py --symbols AAPL,MSFT -e NASDAQ -r america --format csv
  # Write CSV to file
  python tv_vwap_scanner.py --symbols AAPL,MSFT -e NASDAQ -r america --format csv --out vwap.csv

Notes
- `screener` is TradingView region/class (e.g., america, crypto, forex, cfd).
- `exchange` should be the TradingView exchange code (e.g., NASDAQ, NYSE).
- Interval defaults to 1 minute.

Dependencies
  pip install tradingview-ta
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Dict, List
import json
import requests

try:
    from tradingview_ta import TA_Handler, Interval
except Exception as exc:  # pragma: no cover
    print(
        "Error: tradingview-ta is required. Install with: pip install tradingview-ta",
        file=sys.stderr,
    )
    raise


INTERVAL_MAP = {
    "1m": Interval.INTERVAL_1_MINUTE,
    "5m": Interval.INTERVAL_5_MINUTES,
    "15m": Interval.INTERVAL_15_MINUTES,
    "30m": Interval.INTERVAL_30_MINUTES,
    "1h": Interval.INTERVAL_1_HOUR,
    "4h": Interval.INTERVAL_4_HOURS,
    "1d": Interval.INTERVAL_1_DAY,
}


def _get_vwap_via_tradingview_ta(symbol: str, exchange: str, screener: str, interval_key: str) -> Optional[float]:
    """Try TradingView TA library first; return float or None if not present."""
    if interval_key not in INTERVAL_MAP:
        raise ValueError(f"Unsupported interval '{interval_key}'. Choose one of {sorted(INTERVAL_MAP.keys())}")

    handler = TA_Handler(
        symbol=symbol,
        screener=screener,
        exchange=exchange,
        interval=INTERVAL_MAP[interval_key],
    )
    analysis = handler.get_analysis()
    indicators = analysis.indicators or {}
    if "VWAP" in indicators:
        return float(indicators["VWAP"])  # type: ignore[arg-type]

    # Some library versions may expose lowercase
    if "vwap" in indicators:
        return float(indicators["vwap"])  # type: ignore[arg-type]

    return None


def _get_vwap_price_via_tradingview_ta(symbol: str, exchange: str, screener: str, interval_key: str) -> Optional[tuple[float, float]]:
    """Try TradingView TA for both VWAP and last price; return None if missing."""
    if interval_key not in INTERVAL_MAP:
        raise ValueError(f"Unsupported interval '{interval_key}'. Choose one of {sorted(INTERVAL_MAP.keys())}")
    handler = TA_Handler(
        symbol=symbol,
        screener=screener,
        exchange=exchange,
        interval=INTERVAL_MAP[interval_key],
    )
    analysis = handler.get_analysis()
    ind = analysis.indicators or {}
    vwap_val = None
    if "VWAP" in ind:
        vwap_val = ind["VWAP"]
    elif "vwap" in ind:
        vwap_val = ind["vwap"]
    price_val = None
    # Common keys for last price
    for key in ("close", "Close", "price", "PRICE", "last"):
        if key in ind:
            price_val = ind[key]
            break
    if vwap_val is None or price_val is None:
        return None
    try:
        return float(vwap_val), float(price_val)
    except Exception:
        return None


def _get_vwap_via_raw_scanner(symbol: str, exchange: str, screener: str, interval_key: str) -> float:
    """Fallback: query TradingView scanner API directly for VWAP column.

    This hits the unofficial endpoint:
      POST https://scanner.tradingview.com/{screener}/scan
    and requests just the VWAP column for the specific symbol.
    """
    tf_map = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "4h": "240",
        "1d": "1D",
    }
    if interval_key not in tf_map:
        raise ValueError(f"Unsupported interval '{interval_key}'. Choose one of {sorted(tf_map.keys())}")

    url = f"https://scanner.tradingview.com/{screener}/scan"
    payload = {
        "symbols": {
            "tickers": [f"{exchange}:{symbol}"],
            "query": {"types": []},
        },
        "columns": ["VWAP", "close"],
        "range": [0, 1],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "options": {"lang": "en"},
        "timeframe": tf_map[interval_key],
    }

    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # Expected shape: {"data": [{"s": "EXCHANGE:SYMBOL", "d": [<VWAP>, <close>]}]}
    if not data or "data" not in data or not data["data"]:
        raise RuntimeError("Empty response from TradingView scanner.")
    row = data["data"][0]
    values = row.get("d", [])
    if not values or len(values) < 2:
        raise RuntimeError("VWAP/close columns missing in scanner response.")
    vwap_val = values[0]
    if vwap_val is None:
        raise RuntimeError("VWAP returned as null for this symbol/interval.")
    return float(vwap_val)


def _get_vwap_many_via_raw_scanner(symbols: List[str], exchange: str, screener: str, interval_key: str) -> Dict[str, Dict[str, Optional[float]]]:
    """Batch query VWAP and last price for many symbols using TradingView scanner.

    Returns mapping {symbol: {"vwap": v or None, "price": p or None}}.
    """
    tf_map = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "4h": "240",
        "1d": "1D",
    }
    if interval_key not in tf_map:
        raise ValueError(f"Unsupported interval '{interval_key}'. Choose one of {sorted(tf_map.keys())}")

    url = f"https://scanner.tradingview.com/{screener}/scan"
    tickers = [f"{exchange}:{s}" for s in symbols]
    payload = {
        "symbols": {"tickers": tickers, "query": {"types": []}},
        "columns": ["VWAP", "close"],
        "range": [0, len(tickers)],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "options": {"lang": "en"},
        "timeframe": tf_map[interval_key],
    }
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    result: Dict[str, Dict[str, Optional[float]]] = {s: {"vwap": None, "price": None} for s in symbols}
    for row in (data.get("data") or []):
        fullname = row.get("s")  # e.g., NASDAQ:AAPL
        vals = row.get("d") or []
        v = None
        p = None
        if len(vals) >= 1 and vals[0] is not None:
            try:
                v = float(vals[0])
            except Exception:
                v = None
        if len(vals) >= 2 and vals[1] is not None:
            try:
                p = float(vals[1])
            except Exception:
                p = None
        # Extract symbol suffix after ':'
        if isinstance(fullname, str) and ":" in fullname:
            sym = fullname.split(":", 1)[1]
            if sym in result:
                result[sym]["vwap"] = v
                result[sym]["price"] = p
    return result


def get_vwap(symbol: str, exchange: str, screener: str = "america", interval_key: str = "1m") -> float:
    """Return VWAP using built-in TradingView scanner; falls back if needed."""
    # Try tradingview_ta first
    v = _get_vwap_via_tradingview_ta(symbol, exchange, screener, interval_key)
    if v is not None:
        return v
    # Fallback to raw scanner query
    return _get_vwap_via_raw_scanner(symbol, exchange, screener, interval_key)

    raise RuntimeError("VWAP not found in TradingView TA indicators response.")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch VWAP via TradingView screener (single or batch)")
    p.add_argument("--symbol", "-s", action="append", help="Ticker symbol (repeat for multiple), e.g., AAPL")
    p.add_argument("--symbols", help="Comma-separated list of symbols, e.g., AAPL,MSFT,GOOGL")
    p.add_argument("--exchange", "-e", required=True, help="Exchange code, e.g., NASDAQ, NYSE")
    p.add_argument("--screener", "-r", default="america", help="TradingView screener region/class (default: america)")
    p.add_argument("--interval", "-i", default="1m", help="Interval key (default: 1m). Choices: 1m,5m,15m,30m,1h,4h,1d")
    p.add_argument("--json", action="store_true", help="Output JSON mapping {symbol: vwap} (deprecated; prefer --format json)")
    p.add_argument("--format", choices=["table", "csv", "json"], default=None, help="Output format. Defaults to 'table' unless --json is set")
    p.add_argument("--out", help="Write output to file path instead of stdout")
    p.add_argument("--precision", type=int, default=6, help="Decimal places for VWAP formatting (default: 6)")
    p.add_argument("--no-header", dest="header", action="store_false", help="When --format csv, suppress header row")
    p.set_defaults(header=True)
    args = p.parse_args(argv)

    # Consolidate symbols from -s and --symbols
    symbols: List[str] = []
    if args.symbol:
        symbols.extend([s.strip().upper() for s in args.symbol if s and s.strip()])
    if args.symbols:
        symbols.extend([s.strip().upper() for s in args.symbols.split(",") if s and s.strip()])
    # Deduplicate while keeping order
    seen = set()
    symbols = [s for s in symbols if not (s in seen or seen.add(s))]

    if not symbols:
        print("Error: provide at least one symbol via -s or --symbols", file=sys.stderr)
        return 2

    # Determine output format
    out_format = args.format
    if out_format is None:
        out_format = "json" if args.json else "table"

    if len(symbols) == 1:
        sym = symbols[0]
        try:
            # Try TA for both; if not available, use raw scanner for both
            pair = _get_vwap_price_via_tradingview_ta(sym, args.exchange, args.screener, args.interval)
            if pair is None:
                # Use single-symbol raw scanner, which returns only vwap; fetch price via batch for this symbol
                vwap = _get_vwap_via_raw_scanner(sym, args.exchange, args.screener, args.interval)
                batch = _get_vwap_many_via_raw_scanner([sym], args.exchange, args.screener, args.interval)
                price = batch.get(sym, {}).get("price")
                if price is None:
                    raise RuntimeError("Last price not available from scanner.")
                pair = (vwap, float(price))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        vwap, price = pair
        output = ""
        if out_format == "json":
            output = json.dumps({sym: {"vwap": vwap, "price": price}})
        elif out_format == "csv":
            lines = []
            if args.header:
                lines.append("symbol,exchange,interval,screener,vwap,price")
            lines.append(
                f"{sym},{args.exchange},{args.interval},{args.screener},{vwap:.{args.precision}f},{price:.{args.precision}f}"
            )
            output = "\n".join(lines)
        else:  # table
            output = (
                f"Symbol: {sym} ({args.exchange})\n"
                f"Interval: {args.interval} (screener: {args.screener})\n"
                f"VWAP: {vwap:.{args.precision}f}\n"
                f"Last: {price:.{args.precision}f}"
            )
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(output + ("\n" if not output.endswith("\n") else ""))
        else:
            print(output)
        return 0

    # Batch path: use raw scanner for efficiency
    try:
        results = _get_vwap_many_via_raw_scanner(symbols, args.exchange, args.screener, args.interval)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    out = ""
    if out_format == "json":
        out = json.dumps(results)
    elif out_format == "csv":
        lines = []
        if args.header:
            lines.append("symbol,exchange,interval,screener,vwap,price")
        for s in symbols:
            rec = results.get(s, {})
            v = rec.get("vwap")
            p = rec.get("price")
            v_str = "" if v is None else f"{v:.{args.precision}f}"
            p_str = "" if p is None else f"{p:.{args.precision}f}"
            lines.append(f"{s},{args.exchange},{args.interval},{args.screener},{v_str},{p_str}")
        out = "\n".join(lines)
    else:  # table
        lines = [f"Exchange: {args.exchange} | Interval: {args.interval} | Screener: {args.screener}"]
        for s in symbols:
            rec = results.get(s, {})
            v = rec.get("vwap")
            p = rec.get("price")
            if v is None and p is None:
                lines.append(f"{s}: (no data)")
            else:
                v_str = "" if v is None else f"{v:.{args.precision}f}"
                p_str = "" if p is None else f"{p:.{args.precision}f}"
                lines.append(f"{s}: VWAP {v_str} | Last {p_str}")
        out = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out + ("\n" if not out.endswith("\n") else ""))
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
