"""Deterministic fake Binance USD-M exchange with fault injection. Simulation only.

The real connector, engine and scanner run on top of this. It replaces only the transport
(urlopen and HTTPSConnection), so faults reach the bot as the exception types production sees.

Assumptions, none of them recorded from Binance:
  * Reusing a clientOrderId is rejected only while that order is open. Binance documents the
    id as unique among open orders, and a filled order's id has been reported as reusable.
    Set dup_mode="always" for the kinder alternative.
  * Conditional orders on /fapi/v1/order are refused with -4120 (tp_mode="reject").
  * Liquidation is simplified: isolated margin, 0.5% maintenance rate.
"""
from __future__ import annotations

import http.client
import io
import json
import socket
import time as _real_time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

_REAL = {
    "time": _real_time.time,
    "monotonic": _real_time.monotonic,
    "perf_counter": _real_time.perf_counter,
    "sleep": _real_time.sleep,
}


class SimCrash(BaseException):
    """Process death. BaseException, so the bot's own except blocks cannot absorb it."""


class VClock:
    """Virtual time. `true` is exchange time; the bot reads true + skew."""

    def __init__(self, start_epoch: float) -> None:
        self.true = float(start_epoch)
        self.skew = 0.0
        self.on_sleep: Callable[[], None] | None = None

    def time(self) -> float:
        return self.true + self.skew

    def monotonic(self) -> float:
        return self.true

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.true += float(seconds)
            if self.on_sleep:
                self.on_sleep()

    def install(self) -> None:
        _real_time.time = self.time
        _real_time.monotonic = self.monotonic
        _real_time.perf_counter = self.monotonic
        _real_time.sleep = self.sleep

    @staticmethod
    def uninstall() -> None:
        _real_time.time = _REAL["time"]
        _real_time.monotonic = _REAL["monotonic"]
        _real_time.perf_counter = _REAL["perf_counter"]
        _real_time.sleep = _REAL["sleep"]


@dataclass
class Fault:
    """One injected failure. Matches on method, path and optional order fields."""

    kind: str
    path: str = "/fapi/v1/order"
    method: str = "POST"
    count: int = 1
    skip: int = 0
    leg: str = ""  # substring of newClientOrderId
    status: int = 503
    code: int = -1000
    msg: str = "Internal error"
    delay_s: float = 0.0
    retry_after: float | None = None
    hits: int = 0

    def matches(self, method: str, path: str, params: dict[str, Any]) -> bool:
        if self.method != "*" and self.method != method:
            return False
        if self.path != "*" and self.path != path:
            return False
        if self.leg and self.leg not in str(params.get("newClientOrderId") or ""):
            return False
        return True


@dataclass
class Position:
    qty: float = 0.0
    entry: float = 0.0
    leverage: int = 20


class FakeExchange:
    def __init__(
        self,
        clock: VClock,
        symbols: list[str],
        *,
        wallet: float = 5000.0,
        taker_fee: float = 0.0004,
        spread_bps: float = 2.0,
        slip_bps: float = 0.0,
        depth_usd: float = 0.0,
        funding_rate: float = 0.0001,
        tp_mode: str = "reject",
        dup_mode: str = "open_only",
        step: float = 0.1,
        tick: float = 0.0001,
    ) -> None:
        self.clock = clock
        self.symbols = list(symbols)
        self.px: dict[str, float] = {s: 1.0 for s in symbols}
        self.spread_bps = spread_bps
        self.slip_bps = slip_bps
        self.depth_usd = depth_usd  # 0 means unlimited
        self.taker_fee = taker_fee
        self.funding_rate = funding_rate
        self.tp_mode = tp_mode
        self.dup_mode = dup_mode
        self.step = step
        self.tick = tick
        self.step_of: dict[str, float] = {}
        self.tick_of: dict[str, float] = {}
        self.wallet = wallet
        self.start_wallet = wallet
        self.hedge = True
        self.pos: dict[tuple[str, str], Position] = {}
        self.leverage: dict[str, int] = {s: 20 for s in symbols}
        self.requests_total = 0
        self.orders: dict[int, dict[str, Any]] = {}
        self.by_cid: dict[str, list[int]] = {}
        self.open_ids: list[int] = []
        self.next_id = 1000
        self.faults: list[Fault] = []
        self.late: list[tuple[float, str, dict[str, Any]]] = []
        self.down_until = 0.0
        # Totals for the report.
        self.fills: list[dict[str, Any]] = []
        self.requests: dict[str, int] = {}
        self.rejects: list[dict[str, Any]] = []
        self.fees = 0.0
        self.funding_paid = 0.0
        self.slippage_cost = 0.0
        self.realized = 0.0
        self.liquidations: list[dict[str, Any]] = []
        self.fault_hits: list[str] = []
        self.order_log: list[dict[str, Any]] = []
        self.t0 = clock.true
        self._weight_minute = -1
        self._weight = 0
        self._last_funding_slot = int(clock.true // 28800)

    # ---- market ----
    def set_price(self, sym: str, price: float) -> None:
        self.px[sym] = float(price)
        self._run_late()
        self._trigger_conditionals(sym)
        self._check_liquidation(sym)
        self._apply_funding()

    def bid_ask(self, sym: str) -> tuple[float, float]:
        p = self.px[sym]
        h = p * self.spread_bps / 20000.0
        return p - h, p + h

    def _run_late(self) -> None:
        due = [x for x in self.late if x[0] <= self.clock.true]
        if due:
            self.late = [x for x in self.late if x[0] > self.clock.true]
            for _, _path, params in due:
                self._new_order(params, late=True)

    def _apply_funding(self) -> None:
        slot = int(self.clock.true // 28800)
        if slot == self._last_funding_slot:
            return
        self._last_funding_slot = slot
        for (sym, side), p in self.pos.items():
            if p.qty <= 0:
                continue
            pay = p.qty * self.px[sym] * self.funding_rate * (1 if side == "LONG" else -1)
            self.wallet -= pay
            self.funding_paid += pay

    def _liq_price(self, side: str, p: Position) -> float:
        lev = max(p.leverage, 1)
        return p.entry * (1 + 1 / lev - 0.005) if side == "SHORT" else p.entry * (1 - 1 / lev + 0.005)

    def _check_liquidation(self, sym: str) -> None:
        for side in ("LONG", "SHORT"):
            p = self.pos.get((sym, side))
            if not p or p.qty <= 0:
                continue
            liq = self._liq_price(side, p)
            px = self.px[sym]
            if (side == "SHORT" and px >= liq) or (side == "LONG" and px <= liq):
                self.liquidations.append(
                    {"t": self.clock.true, "symbol": sym, "side": side, "qty": p.qty, "px": px}
                )
                self._book_close(sym, side, p.qty, liq, source="LIQUIDATION", cid="LIQ")

    def _trigger_conditionals(self, sym: str) -> None:
        for oid in list(self.open_ids):
            o = self.orders[oid]
            if o["symbol"] != sym or o["type"] != "TAKE_PROFIT_MARKET":
                continue
            px = self.px[sym]
            stop = float(o["stopPrice"])
            hit = px <= stop if o["side"] == "BUY" else px >= stop
            if not hit:
                continue
            self.open_ids.remove(oid)
            side = o["positionSide"]
            p = self.pos.get((sym, side))
            qty = min(float(o["origQty"]), p.qty if p else 0.0)
            if qty > 0:
                self._book_close(sym, side, qty, px, source="TP", cid=o["clientOrderId"])
            o["status"] = "FILLED" if qty > 0 else "EXPIRED"

    # ---- ledger ----
    def _fill_px(self, sym: str, side: str) -> float:
        bid, ask = self.bid_ask(sym)
        slip = self.slip_bps / 10000.0
        return ask * (1 + slip) if side == "BUY" else bid * (1 - slip)

    def _book_open(self, sym: str, ps: str, qty: float, px: float, cid: str) -> None:
        p = self.pos.setdefault((sym, ps), Position(leverage=self.leverage[sym]))
        total = p.qty + qty
        p.entry = (p.entry * p.qty + px * qty) / total if total > 0 else 0.0
        p.qty = round(total, 8)  # Binance reports exact decimals.
        p.leverage = self.leverage[sym]
        fee = px * qty * self.taker_fee
        self.wallet -= fee
        self.fees += fee
        self.slippage_cost += abs(px - self.px[sym]) * qty
        self.fills.append(
            {
                "t": self.clock.true, "symbol": sym, "ps": ps, "action": "OPEN", "qty": qty,
                "px": px, "cid": cid, "leverage": self.leverage[sym], "pnl": 0.0,
            }
        )

    def _book_close(self, sym: str, ps: str, qty: float, px: float, *, source: str, cid: str) -> None:
        p = self.pos[(sym, ps)]
        qty = min(qty, p.qty)
        sign = 1 if ps == "LONG" else -1
        pnl = (px - p.entry) * qty * sign
        fee = px * qty * self.taker_fee
        self.wallet += pnl - fee
        self.realized += pnl
        self.fees += fee
        self.slippage_cost += abs(px - self.px[sym]) * qty
        p.qty = round(p.qty - qty, 8)
        if p.qty <= 1e-9:
            del self.pos[(sym, ps)]
        self.fills.append(
            {
                "t": self.clock.true, "symbol": sym, "ps": ps, "action": source, "qty": qty,
                "px": px, "cid": cid, "leverage": p.leverage, "pnl": pnl,
            }
        )

    def unrealized(self) -> float:
        out = 0.0
        for (sym, ps), p in self.pos.items():
            out += (self.px[sym] - p.entry) * p.qty * (1 if ps == "LONG" else -1)
        return out

    def equity(self) -> float:
        return self.wallet + self.unrealized()

    def margin_used(self) -> float:
        return sum(p.qty * p.entry / max(p.leverage, 1) for p in self.pos.values())

    def available(self) -> float:
        return self.wallet + min(0.0, self.unrealized()) - self.margin_used()

    # ---- REST ----
    def _err(self, status: int, code: int, msg: str, params: dict[str, Any] | None = None) -> tuple[int, dict, Any]:
        self.rejects.append(
            {"t": self.clock.true, "code": code, "msg": msg, "cid": (params or {}).get("newClientOrderId")}
        )
        return status, {}, {"code": code, "msg": msg}

    def handle(self, method: str, path: str, params: dict[str, Any]) -> tuple[int, dict, Any]:
        if "timestamp" in params:
            drift = abs(float(params["timestamp"]) - self.clock.true * 1000)
            if drift > float(params.get("recvWindow") or 5000):
                return self._err(400, -1021, "Timestamp for this request is outside of the recvWindow.", params)
        key = f"{method} {path}"
        self.requests[key] = self.requests.get(key, 0) + 1
        fn = getattr(self, "_h_" + path.replace("/fapi/", "").replace("/", "_"), None)
        if fn is None:
            return 200, {}, {}
        return fn(method, params)

    def _h_v1_time(self, m: str, q: dict) -> tuple:
        return 200, {}, {"serverTime": int(self.clock.true * 1000)}

    def _h_v1_ping(self, m: str, q: dict) -> tuple:
        return 200, {}, {}

    def _h_v1_exchangeInfo(self, m: str, q: dict) -> tuple:
        rows = []
        for s in self.symbols:
            step = self.step_of.get(s, self.step)
            tick = self.tick_of.get(s, self.tick)
            rows.append(
                {
                    "symbol": s, "status": "TRADING", "contractType": "PERPETUAL",
                    "pricePrecision": 8, "quantityPrecision": 8,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": f"{tick:.10f}"},
                        {"filterType": "LOT_SIZE", "stepSize": f"{step:.10f}", "minQty": f"{step:.10f}", "maxQty": "1000000000000"},
                        {"filterType": "MARKET_LOT_SIZE", "stepSize": f"{step:.10f}", "minQty": f"{step:.10f}", "maxQty": "100000000000"},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                        {"filterType": "PERCENT_PRICE", "multiplierUp": "1.15", "multiplierDown": "0.85"},
                    ],
                }
            )
        return 200, {}, {"symbols": rows}

    def _h_v1_positionSide_dual(self, m: str, q: dict) -> tuple:
        if m == "POST":
            if self.hedge:
                return 400, {}, {"code": -4059, "msg": "No need to change position side."}
            self.hedge = True
            return 200, {}, {"code": 200, "msg": "success"}
        return 200, {}, {"dualSidePosition": self.hedge}

    def _h_v1_leverage(self, m: str, q: dict) -> tuple:
        sym = q["symbol"]
        new = int(q["leverage"])
        open_legs = [p for (s, _), p in self.pos.items() if s == sym and p.qty > 0]
        if open_legs and new < self.leverage[sym]:
            return self._err(400, -4161, "Leverage reduction is not supported in Isolated Margin Mode with open positions", q)
        self.leverage[sym] = new
        return 200, {}, {"symbol": sym, "leverage": new, "maxNotionalValue": "1000000"}

    def _h_v1_marginType(self, m: str, q: dict) -> tuple:
        return 400, {}, {"code": -4046, "msg": "No need to change margin type."}

    def _position_rows(self, sym: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for (s, ps), p in self.pos.items():
            if sym and s != sym:
                continue
            sign = 1 if ps == "LONG" else -1
            rows.append(
                {
                    "symbol": s, "positionSide": ps, "positionAmt": str(sign * p.qty),
                    "entryPrice": str(p.entry), "markPrice": str(self.px[s]),
                    "unRealizedProfit": str((self.px[s] - p.entry) * p.qty * sign),
                    "unrealizedProfit": str((self.px[s] - p.entry) * p.qty * sign),
                    "leverage": str(self.leverage[s]), "marginType": "isolated", "isolated": True,
                    "liquidationPrice": str(self._liq_price(ps, p)),
                }
            )
        return rows

    def _h_v2_positionRisk(self, m: str, q: dict) -> tuple:
        return 200, {}, self._position_rows(q.get("symbol"))

    def _h_v2_account(self, m: str, q: dict) -> tuple:
        return 200, {}, {
            "totalWalletBalance": str(self.wallet),
            "availableBalance": str(self.available()),
            "totalUnrealizedProfit": str(self.unrealized()),
            "maxWithdrawAmount": str(max(0.0, self.available())),
            "totalMarginBalance": str(self.equity()),
            "assets": [{"asset": "USDT", "walletBalance": str(self.wallet), "availableBalance": str(self.available())}],
            "positions": self._position_rows(),
        }

    def _h_v2_balance(self, m: str, q: dict) -> tuple:
        return 200, {}, [{"asset": "USDT", "balance": str(self.wallet), "availableBalance": str(self.available())}]

    def _h_v1_ticker_bookTicker(self, m: str, q: dict) -> tuple:
        bid, ask = self.bid_ask(q["symbol"])
        return 200, {}, {"symbol": q["symbol"], "bidPrice": str(bid), "askPrice": str(ask)}

    def _h_v1_premiumIndex(self, m: str, q: dict) -> tuple:
        return 200, {}, {"symbol": q.get("symbol"), "markPrice": str(self.px.get(q.get("symbol"), 1.0)), "lastFundingRate": str(self.funding_rate)}

    def _h_v1_openOrders(self, m: str, q: dict) -> tuple:
        return 200, {}, [self.orders[i] for i in self.open_ids if self.orders[i]["symbol"] == q.get("symbol")]

    def _h_v1_allOpenOrders(self, m: str, q: dict) -> tuple:
        for oid in list(self.open_ids):
            if self.orders[oid]["symbol"] == q.get("symbol"):
                self.open_ids.remove(oid)
                self.orders[oid]["status"] = "CANCELED"
        return 200, {}, {"code": 200, "msg": "ok"}

    def _h_v1_order(self, m: str, q: dict) -> tuple:
        if m == "GET":
            ids = self.by_cid.get(str(q.get("origClientOrderId")), [])
            if not ids:
                return 400, {}, {"code": -2013, "msg": "Order does not exist."}
            return 200, {}, self.orders[ids[-1]]
        if m == "POST":
            return self._new_order(q)
        return 200, {}, {}

    def _new_order(self, q: dict, *, late: bool = False) -> tuple:
        sym = q["symbol"]
        self.order_log.append(
            {
                "t": round(self.clock.true - self.t0, 3), "symbol": sym, "side": q["side"],
                "ps": q.get("positionSide"), "type": q["type"], "qty": q.get("quantity"),
                "cid": q.get("newClientOrderId"), "late": late,
            }
        )
        side = q["side"]
        ps = q.get("positionSide") or ""
        cid = str(q.get("newClientOrderId") or f"auto{self.next_id}")
        typ = q["type"]
        if sym not in self.px:
            return self._err(400, -1121, "Invalid symbol.", q)
        if self.hedge and ps not in ("LONG", "SHORT"):
            return self._err(400, -4061, "Order's position side does not match user's setting.", q)
        if self.hedge and q.get("reduceOnly"):
            return self._err(400, -1106, "Parameter 'reduceonly' sent when not required.", q)
        prior = self.by_cid.get(cid, [])
        if prior and (self.dup_mode == "always" or any(i in self.open_ids for i in prior)):
            return self._err(400, -4116, "ClientOrderId is duplicated.", q)
        if typ in ("TAKE_PROFIT_MARKET", "STOP_MARKET"):
            if self.tp_mode == "reject":
                return self._err(400, -4120, "Order type not supported for this endpoint. Please use the Algo Order API endpoints instead.", q)
            return 200, {}, self._record(q, cid, "NEW", 0.0, 0.0, keep_open=True)
        qty = float(q.get("quantity") or 0)
        step = self.step_of.get(sym, self.step)
        if qty <= 0 or abs(qty / step - round(qty / step)) > 1e-6:
            return self._err(400, -1111, "Precision is over the maximum defined for this asset.", q)
        opening = (side == "BUY" and ps == "LONG") or (side == "SELL" and ps == "SHORT")
        px = self._fill_px(sym, side)
        if typ == "LIMIT":
            limit = float(q.get("price") or 0)
            if (side == "BUY" and limit < px) or (side == "SELL" and limit > px):
                return 200, {}, self._record(q, cid, "EXPIRED", 0.0, 0.0)
        if opening:
            if qty * px < 5.0:
                return self._err(400, -4164, "Order's notional must be no smaller than 5", q)
            if qty * px / max(self.leverage[sym], 1) > self.available():
                return self._err(400, -2019, "Margin is insufficient.", q)
        else:
            held = self.pos.get((sym, ps))
            if not held or qty > held.qty + 1e-9:
                return self._err(400, -2022, "ReduceOnly Order is rejected.", q)
        filled = qty
        status = "FILLED"
        if self.depth_usd > 0 and qty * px > self.depth_usd:
            filled = max(step, int(self.depth_usd / px / step) * step)
            filled = round(filled, 8)
            status = "EXPIRED"  # Remainder dropped, as a market order on a thin book.
        if opening:
            self._book_open(sym, ps, filled, px, cid)
        else:
            self._book_close(sym, ps, filled, px, source="CLOSE", cid=cid)
        order = self._record(q, cid, status, filled, px)
        if q.get("newOrderRespType") == "RESULT":
            return 200, {}, order
        ack = dict(order)
        ack.update({"status": "NEW", "executedQty": "0", "avgPrice": "0.00", "cumQuote": "0"})
        return 200, {}, ack

    def _record(self, q: dict, cid: str, status: str, filled: float, px: float, *, keep_open: bool = False) -> dict[str, Any]:
        self.next_id += 1
        o = {
            "orderId": self.next_id, "symbol": q["symbol"], "clientOrderId": cid, "status": status,
            "side": q["side"], "positionSide": q.get("positionSide") or "BOTH", "type": q["type"],
            "origQty": str(q.get("quantity") or 0), "executedQty": str(filled),
            "avgPrice": str(px), "cumQuote": str(filled * px), "stopPrice": str(q.get("stopPrice") or 0),
        }
        self.orders[self.next_id] = o
        self.by_cid.setdefault(cid, []).append(self.next_id)
        if keep_open:
            self.open_ids.append(self.next_id)
        return o

    # ---- transport ----
    def _weight_header(self, path: str) -> dict[str, str]:
        minute = int(self.clock.true // 60)
        if minute != self._weight_minute:
            self._weight_minute = minute
            self._weight = 0
        self._weight += 5 if ("account" in path or "positionRisk" in path) else 1
        return {"X-MBX-USED-WEIGHT-1M": str(self._weight)}

    def _next_fault(self, method: str, path: str, params: dict[str, Any]) -> Fault | None:
        for f in self.faults:
            if f.count != 0 and f.matches(method, path, params):
                if f.skip > 0:
                    f.skip -= 1
                    continue
                if f.count > 0:
                    f.count -= 1
                f.hits += 1
                self.fault_hits.append(f"{f.kind}:{method} {path}")
                return f
        return None

    def transport(self, method: str, url: str) -> tuple[int, dict, bytes]:
        """Returns (status, headers, body), or raises what the socket layer would raise."""
        parts = urllib.parse.urlsplit(url)
        path = parts.path
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        if self.clock.true < self.down_until:
            raise ConnectionRefusedError(111, "Connection refused")
        f = self._next_fault(method, path, params)
        headers = self._weight_header(path)
        if f:
            k = f.kind
            if k == "crash_before":
                raise SimCrash()
            if k == "timeout_before":
                raise socket.timeout("timed out")
            if k == "reset_before":
                raise ConnectionResetError(104, "Connection reset by peer")
            if k == "http":
                if f.retry_after is not None:
                    headers["Retry-After"] = str(f.retry_after)
                return f.status, headers, json.dumps({"code": f.code, "msg": f.msg}).encode()
            if k == "http_html":
                return f.status, headers, b"<html>Bad Gateway</html>"
            if k == "delay":
                self.clock.true += f.delay_s
            if k == "late_landing":
                # The request stalls in the network, times out here, and reaches the
                # matching engine later.
                self.late.append((self.clock.true + f.delay_s, path, dict(params)))
                raise socket.timeout("timed out")
            status, h, body = self.handle(method, path, params)
            headers.update(h)
            if k == "crash_after":
                raise SimCrash()
            if k == "timeout_after":
                raise socket.timeout("timed out")
            if k == "reset_after":
                raise ConnectionResetError(104, "Connection reset by peer")
            if k == "closed_after":
                raise http.client.RemoteDisconnected("Remote end closed connection without response")
            if k == "http_after":
                return f.status, headers, json.dumps({"code": f.code, "msg": f.msg}).encode()
            if k == "bad_json_after":
                return 200, headers, b"<html>gateway</html>"
            if k == "empty_after":
                return 200, headers, b""
            if k == "truncated_after":
                return 200, headers, json.dumps(body).encode()[:12]
            return status, headers, json.dumps(body).encode()
        status, h, body = self.handle(method, path, params)
        headers.update(h)
        return status, headers, json.dumps(body).encode()


class _Hdr(dict):
    def get(self, k: str, d: Any = None) -> Any:  # noqa: A003
        for key, v in self.items():
            if key.lower() == str(k).lower():
                return v
        return d


class _UrlResp:
    def __init__(self, body: bytes, headers: dict) -> None:
        self._b = body
        self.headers = _Hdr(headers)

    def read(self) -> bytes:
        return self._b

    def __enter__(self) -> "_UrlResp":
        return self

    def __exit__(self, *a: Any) -> None:
        return None


class _ConnResp:
    def __init__(self, status: int, headers: dict, body: bytes) -> None:
        self.status = status
        self._h = _Hdr(headers)
        self._b = body

    def read(self) -> bytes:
        return self._b

    def getheader(self, k: str, d: Any = None) -> Any:
        return self._h.get(k, d)


def install_transport(get_exchange: Callable[[], FakeExchange]) -> None:
    """Point urllib and http.client at the fake exchange."""

    def fake_urlopen(req: Any, timeout: float | None = None, **_: Any) -> _UrlResp:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        method = req.get_method() if hasattr(req, "get_method") else "GET"
        try:
            status, headers, body = get_exchange().transport(method, url)
        except ConnectionRefusedError as e:
            raise urllib.error.URLError(e) from e
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "error", _Hdr(headers), io.BytesIO(body))
        return _UrlResp(body, headers)

    class FakeHTTPS:
        def __init__(self, host: str, timeout: float | None = None, context: Any = None) -> None:
            self.host = host
            self._pending: _ConnResp | None = None
            self._exc: BaseException | None = None

        def request(self, method: str, path: str, headers: Any = None) -> None:
            try:
                status, h, body = get_exchange().transport(method, f"https://{self.host}{path}")
                self._pending = _ConnResp(status, h, body)
            except ConnectionRefusedError:
                raise
            except BaseException as e:  # noqa: BLE001
                self._exc = e  # Sent OK; the failure surfaces while reading the response.

        def getresponse(self) -> _ConnResp:
            if self._exc is not None:
                e, self._exc = self._exc, None
                raise e
            assert self._pending is not None
            return self._pending

        def close(self) -> None:
            self._pending = None

    urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
    http.client.HTTPSConnection = FakeHTTPS  # type: ignore[assignment,misc]
