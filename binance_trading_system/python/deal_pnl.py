"""Sanitize Binance userTrades — fix bad fill prices and phantom P&L on micro-cap alts."""
from __future__ import annotations

from typing import Any


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def effective_fill_price(
    qty: float,
    price: float,
    quote_qty: float,
    *,
    mark: float | None = None,
) -> float:
    """Prefer quoteQty/qty when reported price disagrees with notional or mark."""
    if qty <= 0:
        return price
    implied = quote_qty / qty if quote_qty > 0 else 0.0
    if implied <= 0:
        return price
    if price <= 0:
        return implied
    rel = abs(price - implied) / max(implied, 1e-12)
    if rel > 0.25:
        return implied
    if mark and mark > 0:
        if abs(price - mark) / mark > 0.5 and abs(implied - mark) / mark <= 0.5:
            return implied
    return price


def is_phantom_pnl(profit: float, qty: float, price: float, quote_qty: float) -> bool:
    """True when realized P&L is implausible vs trade notional (e.g. qty mistaken for USD)."""
    if abs(profit) < 1e-9:
        return False
    notional = quote_qty if quote_qty > 0 else qty * price
    if notional <= 0:
        return abs(profit) > 1000
    # Realized P&L on a single fill should not dwarf notional (leverage included).
    return abs(profit) > max(notional * 8.0, 2500.0)


def _leg_key(position_side: str, side: str) -> str:
    ps = (position_side or "").upper()
    if ps in ("SHORT", "LONG"):
        return ps
    return "LONG" if side.upper() == "BUY" else "SHORT"


def _open_leg(side: str, leg: str) -> bool:
    side_u = side.upper()
    if leg == "SHORT":
        return side_u == "SELL"
    return side_u == "BUY"


def _close_leg(side: str, leg: str) -> bool:
    return not _open_leg(side, leg)


def _fifo_pnl(
    stacks: dict[str, list[dict[str, float]]],
    leg: str,
    side: str,
    qty: float,
    price: float,
) -> float:
    """Return realized P&L for a closing fill using FIFO against prior opens."""
    if qty <= 0 or price <= 0 or not _close_leg(side, leg):
        return 0.0
    book = stacks.setdefault(leg, [])
    remaining = qty
    pnl = 0.0
    while remaining > 1e-12 and book:
        lot = book[0]
        take = min(remaining, lot["qty"])
        entry = lot["price"]
        if leg == "SHORT":
            pnl += (entry - price) * take
        else:
            pnl += (price - entry) * take
        lot["qty"] -= take
        remaining -= take
        if lot["qty"] <= 1e-12:
            book.pop(0)
    return pnl


def normalize_user_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Fix micro-cap bad fill prices (e.g. price=1.0, quoteQty/qty=0.002) and recompute
    phantom realizedPnl from paired opens/closes per symbol.
    """
    if not trades:
        return []

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in trades:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        by_symbol.setdefault(sym, []).append(dict(row))

    normalized: list[dict[str, Any]] = []
    for sym in sorted(by_symbol):
        rows = sorted(by_symbol[sym], key=lambda r: int(r.get("time") or 0))
        stacks: dict[str, list[dict[str, float]]] = {"SHORT": [], "LONG": []}

        for raw in rows:
            qty = _f(raw.get("volume", raw.get("qty")))
            quote_qty = _f(raw.get("quote_qty", raw.get("quoteQty")))
            reported_price = _f(raw.get("price"))
            price = effective_fill_price(qty, reported_price, quote_qty)
            side = str(raw.get("type", raw.get("side", ""))).upper()
            leg = _leg_key(str(raw.get("position_side", raw.get("positionSide", ""))), side)
            reported_pnl = _f(raw.get("profit", raw.get("realizedPnl")))

            if _open_leg(side, leg):
                stacks[leg].append({"qty": qty, "price": price})
                profit = 0.0
                corrected = reported_price > 0 and abs(price - reported_price) / max(price, 1e-12) > 0.25
            else:
                fifo = _fifo_pnl(stacks, leg, side, qty, price)
                phantom = is_phantom_pnl(reported_pnl, qty, reported_price, quote_qty)
                price_bad = reported_price > 0 and abs(price - reported_price) / max(price, 1e-12) > 0.25
                if phantom or price_bad or abs(reported_pnl - fifo) > max(abs(fifo) * 0.5, 50.0) and abs(
                    reported_pnl
                ) > max(quote_qty, qty * price):
                    profit = fifo
                    corrected = True
                else:
                    profit = reported_pnl
                    corrected = False

            out = dict(raw)
            out.update(
                {
                    "symbol": sym,
                    "type": side,
                    "volume": qty,
                    "price": price,
                    "quote_qty": quote_qty if quote_qty > 0 else round(qty * price, 8),
                    "profit": round(profit, 8),
                    "realized_pnl": round(profit, 8),
                    "is_close": not _open_leg(side, leg),
                    "position_side": leg,
                }
            )
            if corrected:
                out["pnl_corrected"] = True
                if reported_price > 0 and abs(price - reported_price) / max(price, 1e-12) > 0.25:
                    out["price_reported"] = reported_price
            normalized.append(out)

    normalized.sort(key=lambda r: int(r.get("time") or 0), reverse=True)
    return normalized
