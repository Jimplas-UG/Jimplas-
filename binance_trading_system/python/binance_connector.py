"""
Binance USD-M Futures REST bridge for BSV3.2.
Mirrors mt5_connector.py surface: status, bars, tick, order, positions.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import logging
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("binance_connector")

MAINNET = "https://fapi.binance.com"
TESTNET = "https://testnet.binancefuture.com"
CLIENT_ID_PREFIX = "BSV32"
DEFAULT_MAGIC = 77002002


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class BinanceConfig:
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    symbol: str = ""
    leverage: int = 5
    margin_type: str = "ISOLATED"
    paper: bool = False
    min_margin_ratio: float = 0.05
    be_trigger_pips: float = 18.0
    be_offset_pips: float = 12.0
    trail_start_pips: float = 25.0
    trail_step_pips: float = 15.0
    pip_size: float = 0.1


def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    precision = max(0, int(round(-math.log10(step)))) if step < 1 else 0
    rounded = math.floor(value / step + 1e-9) * step
    return round(rounded, precision)


def round_to_tick(price: float, tick: float) -> float:
    return round_to_step(price, tick)


class BinanceConnector:
    """Signed REST client for Binance USD-M Futures."""

    def __init__(self, cfg: BinanceConfig | None = None):
        self.cfg = cfg or BinanceConfig()
        self._symbol_info: dict[str, Any] | None = None
        self._connected = False
        self._time_offset_ms = 0
        self._time_synced_at = 0.0
        self._hedge_mode: bool | None = None
        self._all_specs_cache: dict[str, dict[str, Any]] = {}
        self._all_specs_loaded_at = 0.0
        self._prepared_cache: dict[tuple[str, int, str], float] = {}
        self._http_conn: http.client.HTTPSConnection | None = None
        self._http_host: str = ""
        self._positions_cache: list[dict[str, Any]] | None = None
        self._positions_cache_ts = 0.0
        self._positions_cache_ttl = 1.5
        if self.cfg.api_key and self.cfg.api_secret and not self.cfg.paper:
            self.sync_server_time(force=True)

    @property
    def base_url(self) -> str:
        return TESTNET if self.cfg.testnet else MAINNET

    def configure(self, api_key: str, api_secret: str, testnet: bool | None = None) -> None:
        new_key = (api_key or "").strip()
        new_secret = (api_secret or "").strip()
        new_testnet = self.cfg.testnet if testnet is None else testnet
        same_creds = (
            self.cfg.api_key == new_key
            and self.cfg.api_secret == new_secret
            and self.cfg.testnet == new_testnet
            and self._time_synced_at
            and time.time() - self._time_synced_at < 300
        )
        self.cfg.api_key = new_key
        self.cfg.api_secret = new_secret
        if testnet is not None:
            self.cfg.testnet = testnet
        if not same_creds:
            self._symbol_info = None
            self._all_specs_cache = {}
            self._all_specs_loaded_at = 0.0
            self._prepared_cache = {}
            self._close_http()
        self._connected = bool(self.cfg.api_key and self.cfg.api_secret) or self.cfg.paper
        if self.cfg.api_key and self.cfg.api_secret and not self.cfg.paper and not same_creds:
            self.sync_server_time(force=True)

    def sync_server_time(self, force: bool = False) -> None:
        if not force and self._time_synced_at and time.time() - self._time_synced_at < 300:
            return
        try:
            data = self._request("GET", "/fapi/v1/time", signed=False)
            server_ms = int(data.get("serverTime", 0))
            local_ms = int(time.time() * 1000)
            self._time_offset_ms = server_ms - local_ms
            self._time_synced_at = time.time()
            log.info("Binance time sync offset_ms=%s", self._time_offset_ms)
        except Exception as e:
            log.warning("Binance time sync failed: %s", e)

    def _server_timestamp_ms(self) -> int:
        if not self._time_synced_at:
            self.sync_server_time(force=True)
        return int(time.time() * 1000) + self._time_offset_ms

    def _headers(self, signed: bool = False) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if signed and self.cfg.api_key:
            h["X-MBX-APIKEY"] = self.cfg.api_key
        return h

    def _close_http(self) -> None:
        if self._http_conn is not None:
            try:
                self._http_conn.close()
            except Exception:
                pass
        self._http_conn = None
        self._http_host = ""

    def _http_host_name(self) -> str:
        return urllib.parse.urlparse(self.base_url).netloc

    def _request_keepalive(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        timeout: float = 10.0,
    ) -> Any:
        """Signed/unsigned REST via persistent HTTPS connection (order hot path)."""
        params = dict(params or {})
        host = self._http_host_name()
        if self._http_conn is None or self._http_host != host:
            self._close_http()
            ctx = ssl.create_default_context()
            self._http_conn = http.client.HTTPSConnection(host, timeout=timeout, context=ctx)
            self._http_host = host

        if signed:
            params["timestamp"] = self._server_timestamp_ms()
            params["recvWindow"] = 60000
            query = urllib.parse.urlencode(params)
            sig = hmac.new(
                self.cfg.api_secret.encode("utf-8"),
                query.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            req_path = f"{path}?{query}&signature={sig}"
        else:
            qs = urllib.parse.urlencode(params) if params else ""
            req_path = f"{path}" + (f"?{qs}" if qs else "")

        headers = self._headers(signed)
        try:
            self._http_conn.request(method, req_path, headers=headers)
            resp = self._http_conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                try:
                    detail = json.loads(body)
                except json.JSONDecodeError:
                    detail = {"msg": body}
                msg = detail.get("msg") or detail.get("detail") or body
                code = detail.get("code")
                raise RuntimeError(f"{msg} (code={code}, http={resp.status})")
            return json.loads(body) if body else {}
        except Exception:
            self._close_http()
            raise

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        timeout: float = 10.0,
        base_url: str | None = None,
    ) -> Any:
        params = dict(params or {})
        root = (base_url or self.base_url).rstrip("/")
        last_err: Exception | None = None
        for attempt in range(5):
            if signed:
                params["timestamp"] = self._server_timestamp_ms()
                params["recvWindow"] = 60000
                query = urllib.parse.urlencode(params)
                sig = hmac.new(
                    self.cfg.api_secret.encode("utf-8"),
                    query.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                url = f"{root}{path}?{query}&signature={sig}"
            else:
                qs = urllib.parse.urlencode(params) if params else ""
                url = f"{root}{path}" + (f"?{qs}" if qs else "")

            req = urllib.request.Request(url, method=method, headers=self._headers(signed))
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                try:
                    detail = json.loads(body)
                except json.JSONDecodeError:
                    detail = {"msg": body}
                msg = detail.get("msg") or detail.get("detail") or body
                if signed and attempt < 2 and ("Timestamp" in str(msg) or "-1021" in str(body)):
                    self.sync_server_time(force=True)
                    last_err = RuntimeError(msg)
                    continue
                if e.code == 429 and attempt < 4:
                    retry_after = 1.0
                    try:
                        retry_after = float(e.headers.get("Retry-After", "1"))
                    except (TypeError, ValueError):
                        pass
                    wait = min(max(retry_after, 0.5), 30.0)
                    log.warning("Binance 429 rate limit — retry in %.1fs", wait)
                    time.sleep(wait)
                    last_err = RuntimeError(detail.get("msg") or detail.get("detail") or body)
                    continue
                if e.code == 418 and attempt < 4:
                    wait = min(60.0 * (attempt + 1), 300.0)
                    log.error("Binance 418 IP ban — backing off %.0fs", wait)
                    time.sleep(wait)
                    last_err = RuntimeError("IP banned by Binance (418) — reduce request rate")
                    continue
                raise RuntimeError(detail.get("msg") or detail.get("detail") or body) from e
            except urllib.error.URLError as e:
                last_err = e
                if attempt < 4:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(str(e)) from e
        if last_err:
            raise RuntimeError(str(last_err))
        raise RuntimeError("request failed")

    def ping(self) -> bool:
        try:
            self._request("GET", "/fapi/v1/ping")
            return True
        except Exception:
            return False

    def exchange_info(self, force: bool = False) -> dict[str, Any]:
        if self._symbol_info and not force:
            return self._symbol_info
        data = self._request("GET", "/fapi/v1/exchangeInfo")
        sym = self.cfg.symbol.upper()
        for s in data.get("symbols", []):
            if s.get("symbol") == sym:
                filters = {f["filterType"]: f for f in s.get("filters", [])}
                lot = filters.get("LOT_SIZE", {})
                price_f = filters.get("PRICE_FILTER", {})
                min_notional_f = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL", {})
                min_notional = float(min_notional_f.get("notional", min_notional_f.get("minNotional", "5")))
                self._symbol_info = {
                    "symbol": sym,
                    "status": s.get("status"),
                    "pricePrecision": s.get("pricePrecision", 2),
                    "quantityPrecision": s.get("quantityPrecision", 3),
                    "tickSize": float(price_f.get("tickSize", "0.01")),
                    "stepSize": float(lot.get("stepSize", "0.001")),
                    "minQty": float(lot.get("minQty", "0.001")),
                    "maxQty": float(lot.get("maxQty", "1000")),
                    "minNotional": min_notional,
                    "contractType": s.get("contractType"),
                }
                return self._symbol_info
        raise RuntimeError(f"Symbol {sym} not found on Binance Futures")

    def _parse_symbol_filters(self, s: dict[str, Any]) -> dict[str, Any]:
        sym = str(s.get("symbol", "")).upper()
        filters = {f["filterType"]: f for f in s.get("filters", [])}
        lot = filters.get("LOT_SIZE", {})
        price_f = filters.get("PRICE_FILTER", {})
        min_notional_f = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL", {})
        min_notional = float(min_notional_f.get("notional", min_notional_f.get("minNotional", "5")))
        return {
            "symbol": sym,
            "status": s.get("status"),
            "pricePrecision": s.get("pricePrecision", 2),
            "quantityPrecision": s.get("quantityPrecision", 3),
            "tickSize": float(price_f.get("tickSize", "0.01")),
            "stepSize": float(lot.get("stepSize", "0.001")),
            "minQty": float(lot.get("minQty", "0.001")),
            "maxQty": float(lot.get("maxQty", "1000")),
            "minNotional": min_notional,
            "contractType": s.get("contractType"),
        }

    def load_all_symbol_specs(self, force: bool = False) -> dict[str, dict[str, Any]]:
        if self._all_specs_cache and not force and time.time() - self._all_specs_loaded_at < 3600:
            return self._all_specs_cache
        data = self._request("GET", "/fapi/v1/exchangeInfo", timeout=45.0)
        cache: dict[str, dict[str, Any]] = {}
        for s in data.get("symbols", []):
            if s.get("status") != "TRADING":
                continue
            parsed = self._parse_symbol_filters(s)
            cache[parsed["symbol"]] = parsed
        self._all_specs_cache = cache
        self._all_specs_loaded_at = time.time()
        log.info("Cached %s Binance Futures symbol specs", len(cache))
        return cache

    def get_symbol_spec(self, symbol: str) -> dict[str, Any]:
        sym = symbol.upper()
        cache = self.load_all_symbol_specs()
        if sym not in cache:
            raise RuntimeError(f"Symbol {sym} not found on Binance Futures")
        return dict(cache[sym])

    def prepare_symbol_cached(self, symbol: str, leverage: int, margin_type: str = "ISOLATED") -> None:
        sym = symbol.upper()
        mt = "ISOLATED"
        from leverage_policy import exchange_leverage

        exchange_lev = exchange_leverage()
        if int(leverage) != exchange_lev:
            log.warning(
                "prepare_symbol_cached %s: requested %sx ignored — exchange locked at %sx",
                sym,
                leverage,
                exchange_lev,
            )
        leverage = exchange_lev
        key = (sym, int(leverage), mt)
        if key in self._prepared_cache and time.time() - self._prepared_cache[key] < 3600:
            self.cfg.symbol = sym
            self.cfg.leverage = int(leverage)
            self.cfg.margin_type = mt
            return
        self.prepare_symbol(sym, leverage, mt)
        self._prepared_cache[key] = time.time()

    def _parse_order_error(self, exc: Exception) -> dict[str, Any]:
        msg = str(exc)
        http_m = re.search(r"http=(\d+)", msg)
        code_m = re.search(r"code=(-?\d+)", msg)
        http_code = int(http_m.group(1)) if http_m else None
        binance_code = int(code_m.group(1)) if code_m else None
        retryable = (
            http_code in (408, 429, 500, 502, 503, 504)
            or binance_code in (-1001, -1003, -1021)
            or "timeout" in msg.lower()
            or "timed out" in msg.lower()
        )
        return {
            "error": msg,
            "http_code": http_code,
            "binance_code": binance_code,
            "retryable": retryable,
        }

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        *,
        client_order_id: str,
        reference_price: float | None = None,
        leverage: int = 5,
        leg: str = "",
    ) -> dict[str, Any]:
        """Fast MARKET order — uses cached filters + optional WS reference price."""
        import time as _time

        if _truthy(os.environ.get("FORWARD_DRY_RUN")):
            return {"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True, "retryable": False}
        sym = symbol.upper()
        side_u = side.upper()
        if self.cfg.paper:
            from paper_simulator import paper_store

            r = paper_store.order_market_leg(sym, side_u, quantity, None, None, 88001)
            return {
                "ok": bool(r.get("ok")),
                "fill_price": r.get("fill_price"),
                "quantity": r.get("volume"),
                "order_id": r.get("order"),
                "error": r.get("error"),
                "retryable": False,
            }
        if not self.cfg.api_key:
            return {"ok": False, "error": "api_key_missing", "retryable": False}

        leg_u = (leg or "").upper()
        if leg_u in ("SHORT", "LONG1", "LONG2"):
            ok_hedge, hedge_err = self.ensure_hedge_mode()
            if not ok_hedge:
                return {
                    "ok": False,
                    "error": f"hedge_mode_required: {hedge_err}",
                    "retryable": False,
                }

        info = self.get_symbol_spec(sym)
        price = float(reference_price or 0)
        if price <= 0:
            tick = self.book_ticker(sym)
            if not tick:
                return {"ok": False, "error": f"no tick for {sym}", "retryable": True}
            price = tick["ask"] if side_u == "BUY" else tick["bid"]
        qty = round_to_step(float(quantity), info["stepSize"])
        qty, qty_err = self._validate_order_qty(qty, price, info)
        if qty_err:
            return {"ok": False, "error": qty_err, "retryable": False}

        self.cfg.symbol = sym
        params: dict[str, Any] = {
            "symbol": sym,
            "side": side_u,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": client_order_id[:36],
        }
        params.update(self._position_side_param_for_leg(side_u, leg_u))
        t0 = _time.perf_counter()
        try:
            entry_resp = self._request_keepalive("POST", "/fapi/v1/order", params, signed=True, timeout=8.0)
        except Exception as e:
            parsed = self._parse_order_error(e)
            parsed["ok"] = False
            parsed["latency_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
            return parsed
        fill = float(entry_resp.get("avgPrice") or price)
        return {
            "ok": True,
            "symbol": sym,
            "side": side_u,
            "quantity": qty,
            "fill_price": fill,
            "order_id": entry_resp.get("orderId"),
            "latency_ms": round((_time.perf_counter() - t0) * 1000, 1),
            "retryable": False,
        }

    def place_tp_market(
        self,
        symbol: str,
        entry_side: str,
        stop_price: float,
        quantity: float,
        *,
        client_id: str,
    ) -> dict[str, Any]:
        sym = symbol.upper()
        info = self.get_symbol_spec(sym)
        self.cfg.symbol = sym
        sp = round_to_tick(float(stop_price), info["tickSize"])
        qty = round_to_step(float(quantity), info["stepSize"])
        exit_side = "SELL" if entry_side.upper() == "BUY" else "BUY"
        params = self._conditional_close_params(
            symbol=sym,
            exit_side=exit_side,
            order_type="TAKE_PROFIT_MARKET",
            stop_price=sp,
            quantity=qty,
            client_order_id=client_id,
            entry_side=entry_side,
        )
        try:
            resp = self._request_keepalive("POST", "/fapi/v1/order", params, signed=True, timeout=8.0)
            return {"ok": True, "order_id": resp.get("orderId")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def symbol_spec(self, symbol: str | None = None, pip_size: float | None = None) -> dict[str, Any]:
        sym = (symbol or self.cfg.symbol).upper()
        if sym != self.cfg.symbol.upper():
            old = self.cfg.symbol
            self.cfg.symbol = sym
            self._symbol_info = None
            info = self.exchange_info(force=True)
            self.cfg.symbol = old
            self._symbol_info = None
        else:
            info = self.exchange_info()
        pip = pip_size if pip_size and pip_size > 0 else self.cfg.pip_size
        tick = info["tickSize"]
        return {
            "symbol": info["symbol"],
            "point": tick,
            "digits": info["pricePrecision"],
            "spread_points": 0,
            "spread_ticks": 0.0,
            "spread_pips": 0.0,
            "spread_price": 0.0,
            "tick_size": tick,
            "step_size": info["stepSize"],
            "min_qty": info["minQty"],
            "max_qty": info["maxQty"],
            "min_notional": info.get("minNotional", 5.0),
            "strategy_tick_size": pip,
            "pip_size": pip,
            "usd_per_tick_per_contract": None,
            "usd_per_pip_per_lot": None,
            "volume_min": info["minQty"],
            "volume_step": info["stepSize"],
            "volume_max": info["maxQty"],
        }

    def _ensure_margin_setup(self) -> None:
        sym = self.cfg.symbol.upper()
        try:
            self._request(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": sym, "marginType": self.cfg.margin_type},
                signed=True,
            )
        except RuntimeError as e:
            if "No need to change" not in str(e):
                log.warning("marginType: %s", e)
        try:
            self._request(
                "POST",
                "/fapi/v1/leverage",
                {"symbol": sym, "leverage": int(self.cfg.leverage)},
                signed=True,
            )
        except RuntimeError as e:
            log.warning("leverage: %s", e)

    def warm_order_cache(self) -> None:
        """Background prep after login — margin + symbol filters for first market order."""
        if self.cfg.paper or not self.cfg.api_key:
            return
        self._ensure_margin_setup()
        try:
            self.load_all_symbol_specs(force=True)
            self.ensure_hedge_mode()
            self.sync_server_time(force=True)
            self.align_isolated_margin_open_symbols()
        except Exception as e:
            log.warning("warm_order_cache: %s", e)

    def is_hedge_mode(self) -> bool:
        """True when account uses dual-side (hedge) position mode."""
        if self.cfg.paper:
            return False
        if self._hedge_mode is not None:
            return self._hedge_mode
        try:
            data = self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
            self._hedge_mode = bool(data.get("dualSidePosition"))
        except RuntimeError as e:
            log.warning("positionSide/dual: %s", e)
            self._hedge_mode = False
        return bool(self._hedge_mode)

    def ensure_hedge_mode(self) -> tuple[bool, str]:
        """Multi-leg scanner requires hedge mode — enable dual-side positions if needed."""
        if self.cfg.paper:
            return True, ""
        if self.is_hedge_mode():
            return True, ""
        try:
            self._request(
                "POST",
                "/fapi/v1/positionSide/dual",
                {"dualSidePosition": "true"},
                signed=True,
            )
            self._hedge_mode = True
            log.info("enabled Binance hedge (dual-side) position mode")
            return True, ""
        except RuntimeError as e:
            msg = str(e)
            if "No need to change" in msg:
                self._hedge_mode = True
                return True, ""
            log.warning("ensure_hedge_mode: %s", msg)
            return False, msg

    def exchange_short_qty(self, symbol: str | None = None) -> float:
        """Open short leg size on symbol (hedge SHORT or one-way SELL)."""
        sym = (symbol or self.cfg.symbol).upper()
        total = 0.0
        for p in self.positions(sym, force=True):
            if str(p.get("symbol") or "").upper() != sym:
                continue
            pos_side = str(p.get("positionSide") or "").upper()
            side = str(p.get("type") or p.get("side") or "").upper()
            if pos_side == "LONG":
                continue
            if side == "SELL" or pos_side == "SHORT":
                total += float(p.get("volume") or 0)
        return total

    def exchange_long_qty(self, symbol: str | None = None) -> float:
        """Open long leg size on symbol (hedge LONG or one-way BUY)."""
        sym = (symbol or self.cfg.symbol).upper()
        total = 0.0
        for p in self.positions(sym, force=True):
            if str(p.get("symbol") or "").upper() != sym:
                continue
            pos_side = str(p.get("positionSide") or "").upper()
            side = str(p.get("type") or p.get("side") or "").upper()
            if pos_side == "SHORT":
                continue
            if side == "BUY" or pos_side == "LONG":
                total += float(p.get("volume") or 0)
        return total

    def _position_side_param_for_leg(self, side: str, leg: str) -> dict[str, str]:
        """Map scanner leg to hedge positionSide — keeps short + long legs separate."""
        if not self.is_hedge_mode():
            return {}
        leg_u = (leg or "").upper()
        if leg_u == "SHORT":
            return {"positionSide": "SHORT"}
        if leg_u in ("LONG1", "LONG2"):
            return {"positionSide": "LONG"}
        return self._position_side_param(side)

    def _position_side_param(self, side: str, *, reduce: bool = False) -> dict[str, str]:
        """Hedge mode requires positionSide on orders; one-way mode omits it."""
        if not self.is_hedge_mode():
            return {}
        side_u = side.upper()
        if reduce:
            # Closing LONG → SELL + LONG; closing SHORT → BUY + SHORT
            pos = "LONG" if side_u == "SELL" else "SHORT"
        else:
            pos = "LONG" if side_u == "BUY" else "SHORT"
        return {"positionSide": pos}

    def _market_close_params(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
        hedge_position_side: str | None = None,
        entry_side_for_reduce: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a reduce/close MARKET order.
        Hedge mode: positionSide only (reduceOnly rejected with -1106).
        One-way mode: reduceOnly only.
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": quantity,
            "newClientOrderId": client_order_id[:36],
        }
        hedge = hedge_position_side.upper() if hedge_position_side else ""
        if self.is_hedge_mode():
            if hedge in ("LONG", "SHORT"):
                params["positionSide"] = hedge
            else:
                params.update(self._position_side_param(side.upper(), reduce=True))
        else:
            params["reduceOnly"] = "true"
        return params

    def _conditional_close_params(
        self,
        *,
        symbol: str,
        exit_side: str,
        order_type: str,
        stop_price: float,
        quantity: float,
        client_order_id: str,
        entry_side: str,
    ) -> dict[str, Any]:
        """TP/SL reduce orders — hedge mode must not include reduceOnly."""
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": exit_side.upper(),
            "type": order_type,
            "stopPrice": stop_price,
            "quantity": quantity,
            "workingType": "MARK_PRICE",
            "newClientOrderId": client_order_id[:36],
        }
        if self.is_hedge_mode():
            params.update(self._position_side_param(exit_side, reduce=True))
        else:
            params["reduceOnly"] = "true"
        return params

    def _validate_order_qty(self, qty: float, price: float, info: dict[str, Any]) -> tuple[float, str | None]:
        qty = round_to_step(qty, info["stepSize"])
        if qty < info["minQty"]:
            qty = info["minQty"]
        notional = qty * price
        min_n = float(info.get("minNotional", info.get("min_notional", 5.0)))
        if notional < min_n:
            return qty, f"notional {notional:.4f} below min {min_n} USDT"
        return qty, None

    def symbol_margin_type(self, symbol: str | None = None) -> str:
        sym = (symbol or self.cfg.symbol).upper()
        if self.cfg.paper:
            return self.cfg.margin_type.upper()
        try:
            rows = self._request("GET", "/fapi/v2/positionRisk", {"symbol": sym}, signed=True)
            if rows:
                mt = str(rows[0].get("marginType", self.cfg.margin_type)).upper()
                if mt in ("ISOLATED", "CROSS"):
                    return mt
        except RuntimeError as e:
            log.warning("symbol_margin_type: %s", e)
        return self.cfg.margin_type.upper()

    def set_margin_type(self, margin_type: str, symbol: str | None = None) -> dict[str, Any]:
        """Scanner always uses ISOLATED — align with Binance per-position margin."""
        sym = (symbol or self.cfg.symbol).upper()
        mt = "ISOLATED"
        if self.cfg.paper:
            self.cfg.margin_type = mt
            return {"ok": True, "margin_type": mt, "symbol": sym}
        if not self.cfg.api_key:
            return {"ok": False, "error": "not connected"}
        try:
            self._request(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": sym, "marginType": mt},
                signed=True,
            )
            self.cfg.margin_type = mt
            return {"ok": True, "margin_type": mt, "symbol": sym}
        except RuntimeError as e:
            msg = str(e)
            if "No need to change" in msg:
                self.cfg.margin_type = mt
                return {"ok": True, "margin_type": mt, "symbol": sym, "note": "already_set"}
            return {"ok": False, "error": msg}

    def symbol_leverage(self, symbol: str | None = None) -> int:
        sym = (symbol or self.cfg.symbol).upper()
        if self.cfg.paper:
            return int(self.cfg.leverage)
        try:
            rows = self._request("GET", "/fapi/v2/positionRisk", {"symbol": sym}, signed=True)
            if rows:
                lev = int(float(rows[0].get("leverage", self.cfg.leverage)))
                if lev > 0:
                    return lev
        except RuntimeError as e:
            log.warning("symbol_leverage: %s", e)
        return int(self.cfg.leverage)

    def status_snapshot(self, *, skip_ping: bool = False) -> dict[str, Any]:
        if self.cfg.paper:
            return {
                "connected": True,
                "mode": "paper",
                "testnet": self.cfg.testnet,
                "account": self.account_info(),
            }
        if not self.cfg.api_key or not self.cfg.api_secret:
            return {"connected": False, "mode": "unconfigured", "testnet": self.cfg.testnet}
        try:
            if not skip_ping and not self.ping():
                env = "testnet.binancefuture.com" if self.cfg.testnet else "fapi.binance.com"
                return {
                    "connected": False,
                    "mode": "testnet" if self.cfg.testnet else "live",
                    "testnet": self.cfg.testnet,
                    "error": f"Cannot reach Binance {env} — check network or VPN",
                }
            acct = self.account_info()
            self._connected = acct is not None
            return {
                "connected": self._connected,
                "mode": "testnet" if self.cfg.testnet else "live",
                "account": acct,
                "testnet": self.cfg.testnet,
            }
        except Exception as e:
            log.error("status_snapshot: %s", e)
            msg = str(e)
            if self.cfg.testnet and re.search(r"invalid api-key|api-key format|signature", msg, re.I):
                msg = (
                    f"{msg} — use Futures keys from testnet.binancefuture.com "
                    "(not mainnet binance.com keys)"
                )
            elif not self.cfg.testnet and re.search(r"invalid api-key|api-key format|signature", msg, re.I):
                msg = f"{msg} — use mainnet Futures keys from binance.com (not testnet keys)"
            return {
                "connected": False,
                "mode": "testnet" if self.cfg.testnet else "live",
                "testnet": self.cfg.testnet,
                "error": msg,
            }

    def account_info(self) -> dict[str, Any] | None:
        if self.cfg.paper:
            return {
                "login": "PAPER",
                "server": "binance-paper",
                "balance": 50000.0,
                "equity": 50000.0,
                "margin": 0.0,
                "margin_free": 50000.0,
                "profit": 0.0,
                "currency": "USDT",
                "trade_allowed": True,
                "leverage": int(self.cfg.leverage),
                "margin_type": self.cfg.margin_type,
            }
        data = self._request("GET", "/fapi/v2/account", signed=True)
        total = float(data.get("totalWalletBalance", 0))
        upnl = float(data.get("totalUnrealizedProfit", 0))
        margin = float(data.get("totalPositionInitialMargin", 0))
        free = float(data.get("availableBalance", 0))
        margin_type = self._account_margin_type_from_positions()
        return {
            "login": self.cfg.api_key[:8] + "…",
            "server": "testnet" if self.cfg.testnet else "mainnet",
            "balance": total,
            "equity": total + upnl,
            "margin": margin,
            "margin_free": free,
            "profit": upnl,
            "currency": "USDT",
            "trade_allowed": True,
            "leverage": self.symbol_leverage(),
            "margin_type": margin_type,
        }

    def _account_margin_type_from_positions(self) -> str:
        """Reflect Binance — ISOLATED unless any open position is CROSS."""
        open_pos = self.positions(force=True)
        if not open_pos:
            return self.symbol_margin_type()
        for p in open_pos:
            mt = str(p.get("margin_type") or "ISOLATED").upper()
            if mt == "CROSS":
                return "CROSS"
        return "ISOLATED"

    def align_isolated_margin_open_symbols(self) -> dict[str, Any]:
        """Set ISOLATED on every symbol with an open position."""
        if self.cfg.paper or not self.cfg.api_key:
            return {"ok": True, "aligned": []}
        aligned: list[str] = []
        errors: list[dict[str, str]] = []
        for p in self.positions(force=True):
            sym = str(p.get("symbol") or "").upper()
            if not sym:
                continue
            mt = str(p.get("margin_type") or "").upper()
            if mt == "ISOLATED":
                aligned.append(sym)
                continue
            r = self.set_margin_type("ISOLATED", sym)
            if r.get("ok"):
                aligned.append(sym)
            else:
                errors.append({"symbol": sym, "error": str(r.get("error") or "margin_failed")})
        self.invalidate_positions_cache()
        return {"ok": len(errors) == 0, "aligned": aligned, "errors": errors or None}

    def book_ticker(self, symbol: str | None = None) -> dict[str, Any] | None:
        sym = (symbol or self.cfg.symbol).upper()
        data = self._request("GET", "/fapi/v1/ticker/bookTicker", {"symbol": sym})
        bid = float(data.get("bidPrice", 0))
        ask = float(data.get("askPrice", 0))
        if bid <= 0 or ask <= 0:
            return None
        return {"symbol": sym, "bid": bid, "ask": ask, "time": int(time.time() * 1000)}

    def tick(self, symbol: str | None = None) -> dict[str, Any] | None:
        return self.book_ticker(symbol)

    def _klines_base_url(self) -> str:
        """Public klines — mainnet has full XAUUSDT history; testnet is too shallow for backtests."""
        if _truthy(os.environ.get("BINANCE_KLINES_TESTNET", "0")):
            return self.base_url
        return MAINNET

    def bars_interval(self, symbol: str | None = None, interval: str = "1m", count: int = 20) -> list[dict[str, Any]]:
        """Public klines for any interval (used to seed scanner rolling windows)."""
        sym = (symbol or self.cfg.symbol).upper()
        n = max(2, min(1500, int(count)))
        iv = (interval or "1m").strip() or "1m"
        data = self._request(
            "GET",
            "/fapi/v1/klines",
            {"symbol": sym, "interval": iv, "limit": n},
            base_url=self._klines_base_url(),
            timeout=20.0,
        )
        return self._klines_to_bars(data)

    def bars_m30(self, symbol: str | None = None, count: int = 320) -> list[dict[str, Any]]:
        return self.bars_interval(symbol, interval="30m", count=max(50, min(1500, int(count))))

    def bars_m30_range(self, symbol: str | None = None, from_ms: int = 0, to_ms: int = 0) -> list[dict[str, Any]]:
        """M30 OHLC between UTC epoch ms (inclusive start). Paginates Binance klines."""
        sym = (symbol or self.cfg.symbol).upper()
        t0 = max(0, int(from_ms))
        t1 = max(t0 + 1, int(to_ms))
        out: list[dict[str, Any]] = []
        cursor = t0
        m30_ms = 30 * 60 * 1000
        klines_base = self._klines_base_url()
        while cursor < t1:
            data = self._request(
                "GET",
                "/fapi/v1/klines",
                {
                    "symbol": sym,
                    "interval": "30m",
                    "startTime": cursor,
                    "endTime": t1,
                    "limit": 1500,
                },
                base_url=klines_base,
            )
            if not data:
                break
            chunk = self._klines_to_bars(data)
            if not chunk:
                break
            for bar in chunk:
                if bar["t"] <= t1:
                    out.append(bar)
            last_t = chunk[-1]["t"]
            next_cursor = last_t + m30_ms
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(data) < 1500:
                break
        if not out:
            return []
        dedup: dict[int, dict[str, Any]] = {b["t"]: b for b in out}
        return sorted(dedup.values(), key=lambda b: b["t"])

    def _klines_to_bars(self, data: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for k in data or []:
            out.append(
                {
                    "t": int(k[0]),
                    "o": float(k[1]),
                    "h": float(k[2]),
                    "l": float(k[3]),
                    "c": float(k[4]),
                }
            )
        return out

    def realized_pnl_for_order(self, symbol: str, order_id: int | None) -> tuple[float, float]:
        """Sum realized PnL and commission from userTrades for a filled order."""
        if not order_id or not self.cfg.api_key:
            return 0.0, 0.0
        sym = symbol.upper()
        try:
            rows = self._request(
                "GET",
                "/fapi/v1/userTrades",
                {"symbol": sym, "orderId": int(order_id)},
                signed=True,
            )
        except Exception as e:
            log.warning("realized_pnl_for_order %s #%s: %s", sym, order_id, e)
            return 0.0, 0.0
        rpnl = 0.0
        comm = 0.0
        for t in rows or []:
            rpnl += float(t.get("realizedPnl", 0))
            comm += float(t.get("commission", 0))
        return rpnl, comm

    def _estimate_close_pnl(self, pos_side: str, entry: float, fill: float, qty: float) -> float:
        if entry <= 0 or fill <= 0 or qty <= 0:
            return 0.0
        if pos_side == "BUY":
            return (fill - entry) * qty
        return (entry - fill) * qty

    def _deal_symbols_for_logs(self, symbol: str | None = None) -> list[str]:
        sym_u = symbol.upper() if symbol else ""
        if sym_u:
            return [sym_u]
        symbols: set[str] = set()
        try:
            for p in self.positions(force=True):
                s = str(p.get("symbol") or "").upper()
                if s:
                    symbols.add(s)
        except Exception:
            pass
        try:
            income = self._request("GET", "/fapi/v1/income", {"limit": 100}, signed=True)
            for row in income or []:
                s = str(row.get("symbol") or "").upper()
                if s:
                    symbols.add(s)
        except Exception as e:
            log.debug("income symbols: %s", e)
        if not symbols:
            symbols.add(self.cfg.symbol.upper())
        return sorted(symbols)

    def recent_deals(self, limit: int = 50, symbol: str | None = None) -> list[dict[str, Any]]:
        """User trades across active/recent symbols — not only cfg.symbol."""
        if self.cfg.paper:
            from paper_simulator import paper_store

            return paper_store.recent_deals(limit)
        if not self.cfg.api_key:
            return []
        lim = max(1, min(200, int(limit)))
        symbols = self._deal_symbols_for_logs(symbol)
        per_sym = max(15, lim // max(len(symbols), 1) + 10)
        deals: list[dict[str, Any]] = []
        for sym in symbols:
            try:
                rows = self._request(
                    "GET",
                    "/fapi/v1/userTrades",
                    {"symbol": sym, "limit": per_sym},
                    signed=True,
                )
            except Exception as e:
                log.warning("userTrades %s: %s", sym, e)
                continue
            for t in rows or []:
                side = "BUY" if t.get("buyer") else "SELL"
                deals.append(
                    {
                        "ticket": t.get("id"),
                        "order_id": t.get("orderId"),
                        "symbol": t.get("symbol"),
                        "type": side,
                        "volume": float(t.get("qty", 0)),
                        "price": float(t.get("price", 0)),
                        "profit": float(t.get("realizedPnl", 0)),
                        "commission": float(t.get("commission", 0)),
                        "time": int(t.get("time", 0)),
                    }
                )
        deals.sort(key=lambda d: int(d.get("time") or 0), reverse=True)
        return deals[:lim]

    def ensure_exchange_leverage(self, symbol: str, leverage: int | None = None) -> bool:
        """Keep symbol leverage at policy exchange level (5x) — Binance is per-symbol."""
        from leverage_policy import SHORT_LEVERAGE

        target = int(leverage if leverage is not None else SHORT_LEVERAGE)
        sym = symbol.upper()
        if self.cfg.paper:
            self.cfg.leverage = target
            return True
        if not self.cfg.api_key:
            return False
        current = self.symbol_leverage(sym)
        if current == target:
            self.cfg.leverage = target
            return True
        try:
            self._request(
                "POST",
                "/fapi/v1/leverage",
                {"symbol": sym, "leverage": target},
                signed=True,
            )
            self.cfg.leverage = target
            self.cfg.symbol = sym
            self._prepared_cache = {k: v for k, v in self._prepared_cache.items() if k[0] != sym}
            log.info("exchange leverage %s restored %sx -> %sx", sym, current, target)
            return True
        except RuntimeError as e:
            log.warning("ensure_exchange_leverage %s: %s", sym, e)
            return False

    def invalidate_positions_cache(self) -> None:
        self._positions_cache = None
        self._positions_cache_ts = 0.0

    def positions(self, symbol: str | None = None, *, force: bool = False) -> list[dict[str, Any]]:
        if self.cfg.paper:
            from paper_simulator import paper_store

            return paper_store.positions(symbol)
        if not self.cfg.api_key or not self.cfg.api_secret:
            return []
        now = time.time()
        if (
            not force
            and symbol is None
            and self._positions_cache is not None
            and now - self._positions_cache_ts < self._positions_cache_ttl
        ):
            return list(self._positions_cache)
        try:
            params: dict[str, Any] = {}
            if symbol:
                params["symbol"] = symbol.upper()
            data = self._request("GET", "/fapi/v2/positionRisk", params or None, signed=True)
        except Exception as e:
            log.warning("positions: %s", e)
            if self._positions_cache is not None and symbol is None:
                return list(self._positions_cache)
            return []
        if not isinstance(data, list):
            data = [data] if data else []
        out: list[dict[str, Any]] = []
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if abs(amt) < 1e-12:
                continue
            side = "BUY" if amt > 0 else "SELL"
            pos_side = str(p.get("positionSide") or "").upper()
            if not pos_side or pos_side == "BOTH":
                pos_side = "LONG" if amt > 0 else "SHORT"
            from leverage_policy import policy_display_leverage

            policy_lev = policy_display_leverage(side=side, position_side=pos_side)
            leg_label = "SHORT" if pos_side == "SHORT" else "LONG"
            out.append(
                {
                    "ticket": p.get("symbol"),
                    "symbol": p.get("symbol"),
                    "type": side,
                    "positionSide": pos_side,
                    "leg": leg_label,
                    "volume": abs(amt),
                    "price_open": float(p.get("entryPrice", 0)),
                    "sl": 0.0,
                    "tp": 0.0,
                    "profit": float(p.get("unRealizedProfit", 0)),
                    "magic": DEFAULT_MAGIC,
                    "liquidationPrice": float(p.get("liquidationPrice", 0)),
                    "leverage": policy_lev,
                    "exchange_leverage": int(float(p.get("leverage", self.cfg.leverage))),
                    "margin_type": str(p.get("marginType") or "ISOLATED").upper(),
                }
            )
        if symbol is None:
            self._positions_cache = out
            self._positions_cache_ts = now
        return out

    def has_open_position(self, symbol: str | None = None) -> bool:
        return len(self.positions(symbol)) > 0

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        sym = (symbol or self.cfg.symbol).upper()
        return self._request("GET", "/fapi/v1/openOrders", {"symbol": sym}, signed=True)

    def cancel_all_orders(self, symbol: str | None = None) -> None:
        sym = (symbol or self.cfg.symbol).upper()
        try:
            self._request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": sym}, signed=True)
        except RuntimeError as e:
            log.warning("cancel_all: %s", e)

    def _liquidation_safe(self, side: str, entry: float, sl: float | None) -> tuple[bool, str]:
        if sl is None:
            return True, ""
        positions = self.positions()
        if not positions:
            return True, ""
        liq = float(positions[0].get("liquidationPrice") or 0)
        if liq <= 0:
            return True, ""
        if side == "BUY" and sl <= liq:
            return False, f"SL {sl} at/beyond liquidation {liq}"
        if side == "SELL" and sl >= liq:
            return False, f"SL {sl} at/beyond liquidation {liq}"
        return True, ""

    def _place_conditional(
        self,
        side: str,
        order_type: str,
        stop_price: float,
        quantity: float,
        client_id: str,
    ) -> dict[str, Any]:
        sym = self.cfg.symbol.upper()
        info = self.exchange_info()
        sp = round_to_tick(stop_price, info["tickSize"])
        qty = round_to_step(quantity, info["stepSize"])
        exit_side = "SELL" if side == "BUY" else "BUY"
        params = self._conditional_close_params(
            symbol=sym,
            exit_side=exit_side,
            order_type=order_type,
            stop_price=sp,
            quantity=qty,
            client_order_id=client_id,
            entry_side=side,
        )
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def order_market(
        self,
        symbol: str,
        side: str,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        magic: int = DEFAULT_MAGIC,
        client_suffix: str = "",
    ) -> dict[str, Any]:
        import time as _time

        if _truthy(os.environ.get("FORWARD_DRY_RUN")):
            return {"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True}

        if self.cfg.paper:
            from paper_simulator import paper_store

            return paper_store.order_market(symbol, side, volume, sl, tp, magic)

        side_u = side.upper()
        sym = symbol.upper()
        self.cfg.symbol = sym
        if not self.cfg.api_key:
            return {"ok": False, "error": "api_key_missing"}
        if self.has_open_position(sym):
            return {"ok": False, "error": "position_already_open"}

        tick = self.book_ticker(sym)
        if not tick:
            return {"ok": False, "error": f"no tick for {sym}"}
        intended = tick["ask"] if side_u == "BUY" else tick["bid"]
        spread_price = tick["ask"] - tick["bid"]
        info = self.exchange_info()
        pip = self.cfg.pip_size
        spread_pips = spread_price / pip if pip > 0 else 0.0
        qty = round_to_step(volume, info["stepSize"])
        qty, qty_err = self._validate_order_qty(qty, intended, info)
        if qty_err:
            return {"ok": False, "error": qty_err}

        safe, reason = self._liquidation_safe(side_u, intended, sl)
        if not safe:
            return {"ok": False, "error": reason}

        acct = self._request("GET", "/fapi/v2/account", signed=True)
        free = float(acct.get("availableBalance", 0))
        risk_usd = qty * abs(intended - (sl or intended))
        if sl and free < risk_usd * 1.5:
            return {"ok": False, "error": f"insufficient_margin free={free:.2f}"}

        self._ensure_margin_setup()
        cid = f"{CLIENT_ID_PREFIX}_{int(_time.time())}{client_suffix}"[:36]
        params = {
            "symbol": sym,
            "side": side_u,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": cid,
        }
        params.update(self._position_side_param(side_u))
        t0 = _time.perf_counter()
        try:
            entry_resp = self._request("POST", "/fapi/v1/order", params, signed=True)
        except RuntimeError as e:
            return {"ok": False, "error": str(e), "latency_ms": round((_time.perf_counter() - t0) * 1000, 1)}
        fill = float(entry_resp.get("avgPrice") or intended)
        slippage = abs(fill - intended)
        slippage_pips = slippage / pip if pip > 0 else 0.0

        stop_id = None
        tp_id = None
        protection_errors: list[str] = []
        if sl is not None:
            try:
                stop_resp = self._place_conditional(
                    side_u, "STOP_MARKET", float(sl), qty, f"{cid}_SL"
                )
                stop_id = stop_resp.get("orderId")
                if not stop_id:
                    protection_errors.append("STOP_MARKET returned no orderId")
            except RuntimeError as e:
                log.error("STOP_MARKET failed: %s", e)
                protection_errors.append(f"STOP_MARKET failed: {e}")
        if tp is not None:
            try:
                tp_resp = self._place_conditional(
                    side_u, "TAKE_PROFIT_MARKET", float(tp), qty, f"{cid}_TP"
                )
                tp_id = tp_resp.get("orderId")
                if not tp_id:
                    protection_errors.append("TAKE_PROFIT_MARKET returned no orderId")
            except RuntimeError as e:
                log.error("TAKE_PROFIT_MARKET failed: %s", e)
                protection_errors.append(f"TAKE_PROFIT_MARKET failed: {e}")

        latency_ms = round((_time.perf_counter() - t0) * 1000, 1)
        return {
            "ok": True,
            "symbol": sym,
            "side": side_u,
            "volume": qty,
            "intended_price": intended,
            "fill_price": fill,
            "spread_pips": round(spread_pips, 2),
            "slippage_pips": round(slippage_pips, 2),
            "latency_ms": latency_ms,
            "order": entry_resp.get("orderId"),
            "deal": entry_resp.get("orderId"),
            "stop_order": stop_id,
            "tp_order": tp_id,
            "protection_ok": len(protection_errors) == 0,
            "protection_errors": protection_errors,
            "naked_position": bool(protection_errors),
            "client_order_id": cid,
            "magic": magic,
            "broker": "binance",
        }

    def modify_stop(self, side: str, new_sl: float, quantity: float) -> bool:
        sym = self.cfg.symbol.upper()
        self.cancel_all_orders(sym)
        try:
            self._place_conditional(side, "STOP_MARKET", new_sl, quantity, f"{CLIENT_ID_PREFIX}_BE_{int(time.time())}")
            return True
        except RuntimeError:
            return False

    def close_by_position_side(
        self,
        symbol: str,
        position_side: str,
        volume: float | None = None,
    ) -> dict[str, Any]:
        """Market-close a single hedge leg (SHORT or LONG) without touching the other side."""
        import time as _time

        if _truthy(os.environ.get("FORWARD_DRY_RUN")):
            return {"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True}

        sym = symbol.upper()
        ps = position_side.upper()
        if ps not in ("SHORT", "LONG"):
            return {"ok": False, "error": "invalid_position_side"}

        if self.cfg.paper:
            magic = 88001 if ps == "SHORT" else 88002
            return self.close_leg(sym, magic, volume)

        if not self.cfg.api_key:
            return {"ok": False, "error": "api_key_missing"}

        targets = [
            p
            for p in self.positions(sym, force=True)
            if str(p.get("positionSide") or "").upper() == ps
            or (
                ps == "SHORT"
                and str(p.get("type", "")).upper() == "SELL"
                and str(p.get("positionSide") or "SHORT").upper() != "LONG"
            )
            or (ps == "LONG" and str(p.get("type", "")).upper() == "BUY")
        ]
        if not targets:
            return {"ok": False, "error": f"no_{ps.lower()}_leg"}

        p = targets[0]
        pos_side = str(p.get("type", "")).upper()
        hedge_side = str(p.get("positionSide") or ps).upper()
        pos_vol = float(p.get("volume", 0))
        info = self.exchange_info()
        qty = round_to_step(float(volume) if volume is not None else pos_vol, info["stepSize"])
        if qty < info["minQty"]:
            qty = info["minQty"]
        if qty > pos_vol + 1e-12:
            qty = round_to_step(pos_vol, info["stepSize"])
        exit_side = "SELL" if pos_side == "BUY" else "BUY"
        cid = f"{CLIENT_ID_PREFIX}_CL_{ps}_{int(_time.time())}"[:36]
        params = self._market_close_params(
            symbol=sym,
            side=exit_side,
            quantity=qty,
            client_order_id=cid,
            hedge_position_side=hedge_side if hedge_side in ("LONG", "SHORT") else ps,
            entry_side_for_reduce=pos_side,
        )
        t0 = _time.perf_counter()
        try:
            resp = self._request_keepalive("POST", "/fapi/v1/order", params, signed=True, timeout=8.0)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        order_id = resp.get("orderId")
        fill = float(resp.get("avgPrice") or p.get("price_open") or 0)
        entry = float(p.get("price_open") or 0)
        rpnl, commission = self.realized_pnl_for_order(sym, int(order_id) if order_id else None)
        if abs(rpnl) < 1e-12 and order_id:
            _time.sleep(0.12)
            rpnl, commission = self.realized_pnl_for_order(sym, int(order_id))
        if abs(rpnl) < 1e-12:
            rpnl = self._estimate_close_pnl(pos_side, entry, fill, qty)
        self.invalidate_positions_cache()
        self.ensure_exchange_leverage(sym)
        latency_ms = round((_time.perf_counter() - t0) * 1000, 1)
        leg_row = {
            "symbol": sym,
            "side": pos_side,
            "position_side": ps,
            "volume": qty,
            "fill_price": fill,
            "entry_price": entry,
            "profit": rpnl,
            "realized_pnl": rpnl,
            "commission": commission,
            "order": order_id,
        }
        return {"ok": True, "closed": [leg_row], **leg_row, "latency_ms": latency_ms, "broker": "binance"}

    def trade_pnl_calendar(self, days: int = 400) -> dict[str, Any]:
        """Aggregate realized PnL by UTC day from Binance income + userTrades."""
        if self.cfg.paper:
            from paper_simulator import paper_store

            deals = paper_store.recent_deals(500)
            by_day: dict[str, dict[str, float]] = {}
            for d in deals:
                ts = int(d.get("time") or 0)
                if ts <= 0:
                    continue
                key = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))
                row = by_day.setdefault(key, {"pnl": 0.0, "trades": 0})
                pnl = float(d.get("profit") or 0)
                if abs(pnl) > 1e-12:
                    row["pnl"] += pnl
                    row["trades"] += 1
            days_out = [{"date": k, **v} for k, v in sorted(by_day.items())]
            total = sum(x["pnl"] for x in days_out)
            return {"ok": True, "total_pnl": round(total, 2), "days": days_out[-days:]}

        if not self.cfg.api_key:
            return {"ok": False, "total_pnl": 0.0, "days": []}

        by_day: dict[str, dict[str, float]] = {}
        try:
            income = self._request(
                "GET",
                "/fapi/v1/income",
                {"incomeType": "REALIZED_PNL", "limit": 1000},
                signed=True,
            )
            for row in income or []:
                ts = int(row.get("time") or 0)
                if ts <= 0:
                    continue
                key = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))
                bucket = by_day.setdefault(key, {"pnl": 0.0, "trades": 0})
                bucket["pnl"] += float(row.get("income") or 0)
                bucket["trades"] += 1
        except Exception as e:
            log.warning("trade_pnl_calendar income: %s", e)

        if not by_day:
            for d in self.recent_deals(200):
                ts = int(d.get("time") or 0)
                pnl = float(d.get("profit") or 0)
                if ts <= 0 or abs(pnl) < 1e-12:
                    continue
                key = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))
                bucket = by_day.setdefault(key, {"pnl": 0.0, "trades": 0})
                bucket["pnl"] += pnl
                bucket["trades"] += 1

        days_out = [
            {"date": k, "pnl": round(v["pnl"], 2), "trades": int(v["trades"])}
            for k, v in sorted(by_day.items())
        ]
        cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
        days_out = [d for d in days_out if d["date"] >= cutoff]
        total = round(sum(d["pnl"] for d in days_out), 2)
        return {"ok": True, "total_pnl": total, "days": days_out}

    def close_position(self, symbol: str | None = None, volume: float | None = None) -> dict[str, Any]:
        import time as _time

        if _truthy(os.environ.get("FORWARD_DRY_RUN")):
            return {"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True}

        if self.cfg.paper:
            from paper_simulator import paper_store

            return paper_store.close_position(symbol, volume)

        sym = (symbol or self.cfg.symbol).upper()
        positions = self.positions(sym, force=True)
        if not positions:
            return {"ok": False, "error": "no_open_position"}

        if not self.cfg.api_key:
            return {"ok": False, "error": "api_key_missing"}

        self.cancel_all_orders(sym)
        info = self.exchange_info()
        closed: list[dict[str, Any]] = []
        t0 = _time.perf_counter()

        for p in positions:
            pos_side = str(p.get("type", "")).upper()
            hedge_side = str(p.get("positionSide") or "").upper()
            pos_vol = float(p.get("volume", 0))
            qty = round_to_step(float(volume) if volume is not None else pos_vol, info["stepSize"])
            if qty < info["minQty"]:
                qty = info["minQty"]
            if qty > pos_vol + 1e-12:
                qty = round_to_step(pos_vol, info["stepSize"])
            exit_side = "SELL" if pos_side == "BUY" else "BUY"
            cid = f"{CLIENT_ID_PREFIX}_CLS_{int(_time.time())}"[:36]
            params = self._market_close_params(
                symbol=sym,
                side=exit_side,
                quantity=qty,
                client_order_id=cid,
                hedge_position_side=hedge_side if hedge_side in ("LONG", "SHORT") else None,
                entry_side_for_reduce=pos_side,
            )
            try:
                resp = self._request_keepalive("POST", "/fapi/v1/order", params, signed=True, timeout=8.0)
            except RuntimeError as e:
                return {"ok": False, "error": str(e), "closed": closed}
            order_id = resp.get("orderId")
            fill = float(resp.get("avgPrice") or p.get("price_open") or 0)
            entry = float(p.get("price_open") or 0)
            rpnl, commission = self.realized_pnl_for_order(sym, int(order_id) if order_id else None)
            if abs(rpnl) < 1e-12 and order_id:
                import time as _wait

                _wait.sleep(0.12)
                rpnl, commission = self.realized_pnl_for_order(sym, int(order_id))
            if abs(rpnl) < 1e-12:
                rpnl = self._estimate_close_pnl(pos_side, entry, fill, qty)
            closed.append(
                {
                    "symbol": sym,
                    "side": pos_side,
                    "exit_side": exit_side,
                    "position_side": hedge_side or None,
                    "volume": qty,
                    "fill_price": fill,
                    "entry_price": entry,
                    "profit": rpnl,
                    "realized_pnl": rpnl,
                    "commission": commission,
                    "order": order_id,
                }
            )

        latency_ms = round((_time.perf_counter() - t0) * 1000, 1)
        self.invalidate_positions_cache()
        return {"ok": True, "closed": closed, "latency_ms": latency_ms, "broker": "binance"}

    def close_all_positions(self) -> dict[str, Any]:
        """Market-close every open position across all symbols."""
        if _truthy(os.environ.get("FORWARD_DRY_RUN")):
            return {"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True}
        if self.cfg.paper:
            from paper_simulator import paper_store

            return paper_store.close_all_positions()
        positions = self.positions(force=True)
        if not positions:
            return {"ok": True, "closed": [], "symbols": [], "note": "already_flat"}
        symbols = sorted({str(p.get("symbol") or "").upper() for p in positions if p.get("symbol")})
        all_closed: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        total_latency = 0.0
        for sym in symbols:
            r = self.close_position(sym, None)
            if r.get("ok"):
                all_closed.extend(r.get("closed") or [])
                total_latency += float(r.get("latency_ms") or 0)
            else:
                errors.append({"symbol": sym, "error": str(r.get("error") or "close_failed")})
        self.invalidate_positions_cache()
        return {
            "ok": len(errors) == 0,
            "closed": all_closed,
            "symbols": symbols,
            "latency_ms": round(total_latency, 1),
            "errors": errors or None,
            "broker": "binance",
        }

    def ticker_24h_map(self) -> dict[str, float]:
        """USDT-M 24h percent map — fills market view when miniTicker omits P (testnet)."""
        try:
            data = self._request("GET", "/fapi/v1/ticker/24hr", timeout=25.0)
        except Exception as e:
            log.warning("ticker_24h_map: %s", e)
            return {}
        out: dict[str, float] = {}
        if not isinstance(data, list):
            return out
        for row in data:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if not sym.endswith("USDT"):
                continue
            try:
                out[sym] = float(row.get("priceChangePercent") or 0)
            except (TypeError, ValueError):
                continue
        return out

    def ticker_24h_volume_map(self) -> dict[str, float]:
        try:
            data = self._request("GET", "/fapi/v1/ticker/24hr", timeout=25.0)
        except Exception as e:
            log.warning("ticker_24h_volume_map: %s", e)
            return {}
        out: dict[str, float] = {}
        if not isinstance(data, list):
            return out
        for row in data:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if not sym.endswith("USDT"):
                continue
            try:
                out[sym] = float(row.get("quoteVolume") or row.get("volume") or 0)
            except (TypeError, ValueError):
                continue
        return out

    def funding_rate_map(self) -> dict[str, float]:
        try:
            data = self._request("GET", "/fapi/v1/premiumIndex", timeout=25.0)
        except Exception as e:
            log.warning("funding_rate_map: %s", e)
            return {}
        out: dict[str, float] = {}
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if not sym.endswith("USDT"):
                continue
            try:
                out[sym] = float(row.get("lastFundingRate") or 0)
            except (TypeError, ValueError):
                continue
        return out

    def list_usdt_perpetual_symbols(self) -> list[str]:
        data = self._request("GET", "/fapi/v1/exchangeInfo", timeout=45.0)
        out: list[str] = []
        for s in data.get("symbols", []):
            if (
                s.get("contractType") == "PERPETUAL"
                and s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
            ):
                out.append(str(s.get("symbol", "")).upper())
        return sorted(sym for sym in out if sym)

    def prepare_symbol(self, symbol: str, leverage: int, margin_type: str = "ISOLATED") -> None:
        sym = symbol.upper()
        self.cfg.symbol = sym
        self.cfg.leverage = int(leverage)
        self.cfg.margin_type = "ISOLATED"
        self._symbol_info = None
        if self.cfg.paper:
            return
        if not self.cfg.api_key:
            return
        try:
            self._request(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": sym, "marginType": self.cfg.margin_type},
                signed=True,
            )
        except RuntimeError as e:
            if "No need to change" not in str(e):
                log.warning("prepare_symbol marginType %s: %s", sym, e)
        try:
            self._request(
                "POST",
                "/fapi/v1/leverage",
                {"symbol": sym, "leverage": int(leverage)},
                signed=True,
            )
        except RuntimeError as e:
            log.warning("prepare_symbol leverage %s: %s", sym, e)

    def order_market_leg(
        self,
        symbol: str,
        side: str,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        leverage: int = 5,
        magic: int = DEFAULT_MAGIC,
        leg: str = "",
    ) -> dict[str, Any]:
        """Scanner leg order — allows multiple legs per symbol (paper) or hedge legs (live)."""
        import time as _time

        if _truthy(os.environ.get("FORWARD_DRY_RUN")):
            return {"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True}

        sym = symbol.upper()
        side_u = side.upper()
        if self.cfg.paper:
            from paper_simulator import paper_store

            return paper_store.order_market_leg(sym, side_u, volume, sl, tp, magic)

        if not self.cfg.api_key:
            return {"ok": False, "error": "api_key_missing"}

        self.prepare_symbol_cached(sym, leverage, "ISOLATED")
        from leverage_policy import exchange_leverage

        exchange_lev = exchange_leverage(leg)
        tick = self.book_ticker(sym)
        if not tick:
            return {"ok": False, "error": f"no tick for {sym}"}
        intended = tick["ask"] if side_u == "BUY" else tick["bid"]
        info = self.get_symbol_spec(sym)
        qty = round_to_step(volume, info["stepSize"])
        qty, qty_err = self._validate_order_qty(qty, intended, info)
        if qty_err:
            return {"ok": False, "error": qty_err}

        if self.cfg.api_key and not self.cfg.paper:
            try:
                acct = self._request("GET", "/fapi/v2/account", signed=True)
                free = float(acct.get("availableBalance", 0))
                notional = qty * intended
                if free < notional / max(exchange_lev, 1) * 1.1:
                    return {"ok": False, "error": f"insufficient_margin free={free:.2f}"}
            except Exception as e:
                log.warning("order_market_leg margin check: %s", e)

        cid = f"{CLIENT_ID_PREFIX}_SC_{leg or magic}_{int(_time.time())}"[:36]
        order_resp = self.place_market_order(
            sym,
            side_u,
            qty,
            client_order_id=cid,
            reference_price=intended,
            leverage=leverage,
            leg=leg or (f"LONG{magic}" if magic in (88002, 88003) else "SHORT"),
        )
        if not order_resp.get("ok"):
            return {
                "ok": False,
                "error": order_resp.get("error"),
                "latency_ms": order_resp.get("latency_ms"),
            }
        fill = float(order_resp.get("fill_price") or intended)
        if tp is not None:
            try:
                tp_resp = self.place_tp_market(sym, side_u, float(tp), qty, client_id=f"{cid}_TP")
                if not tp_resp.get("ok"):
                    log.warning("scanner TP %s: %s", sym, tp_resp.get("error"))
            except RuntimeError as e:
                log.warning("scanner TP %s: %s", sym, e)
        return {
            "ok": True,
            "symbol": sym,
            "side": side_u,
            "volume": qty,
            "intended_price": intended,
            "fill_price": fill,
            "latency_ms": order_resp.get("latency_ms"),
            "order": order_resp.get("order_id"),
            "magic": magic,
            "leg": leg,
            "broker": "binance",
        }

    def close_leg(self, symbol: str, magic: int, volume: float | None = None) -> dict[str, Any]:
        if self.cfg.paper:
            from paper_simulator import paper_store

            return paper_store.close_leg(symbol, magic, volume)
        sym = symbol.upper()
        qty = float(volume or 0)
        if qty <= 0:
            pos = self.positions(sym)
            if not pos:
                return {"ok": False, "error": "no_position"}
            qty = float(pos[0].get("volume", 0))
        if qty <= 0:
            return {"ok": False, "error": "invalid_volume"}

        magic_i = int(magic)
        if magic_i == 88001:
            close_side = "BUY"
            hedge_side = "SHORT"
        elif magic_i in (88002, 88003):
            close_side = "SELL"
            hedge_side = "LONG"
        else:
            return self.close_position(sym, qty)

        tick = self.book_ticker(sym)
        if not tick:
            return {"ok": False, "error": f"no tick for {sym}"}
        info = self.symbol_spec(sym)
        qty = round_to_step(qty, info["stepSize"])
        qty, qty_err = self._validate_order_qty(qty, tick["bid"], info)
        if qty_err:
            return {"ok": False, "error": qty_err}

        import time as _time

        params = self._market_close_params(
            symbol=sym,
            side=close_side,
            quantity=qty,
            client_order_id=f"{CLIENT_ID_PREFIX}_CL_{magic_i}_{int(_time.time())}",
            hedge_position_side=hedge_side,
        )
        try:
            resp = self._request_keepalive("POST", "/fapi/v1/order", params, signed=True, timeout=8.0)
            order_id = resp.get("orderId")
            fill = float(resp.get("avgPrice") or tick["bid"])
            rpnl, commission = self.realized_pnl_for_order(sym, int(order_id) if order_id else None)
            return {
                "ok": True,
                "symbol": sym,
                "volume": qty,
                "fill_price": fill,
                "realized_pnl": rpnl,
                "profit": rpnl,
                "commission": commission,
                "order": order_id,
                "magic": magic_i,
            }
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}


def config_from_env() -> BinanceConfig:
    return BinanceConfig(
        api_key=os.environ.get("BINANCE_API_KEY", ""),
        api_secret=os.environ.get("BINANCE_API_SECRET", ""),
        testnet=_truthy(os.environ.get("BINANCE_TESTNET", "1")),
        symbol=os.environ.get("BINANCE_SYMBOL", "BTCUSDT").upper() or "BTCUSDT",
        leverage=int(os.environ.get("BINANCE_LEVERAGE", "5")),
        margin_type="ISOLATED",
        paper=_truthy(os.environ.get("BINANCE_PAPER", "0")),
        pip_size=float(
            os.environ.get("BINANCE_TICK_SIZE")
            or os.environ.get("BINANCE_PIP_SIZE", "0.1")
        ),
        be_trigger_pips=float(
            os.environ.get("BINANCE_BE_TRIGGER_TICKS")
            or os.environ.get("BINANCE_BE_TRIGGER_PIPS", "18")
        ),
        be_offset_pips=float(
            os.environ.get("BINANCE_BE_OFFSET_TICKS")
            or os.environ.get("BINANCE_BE_OFFSET_PIPS", "12")
        ),
        trail_start_pips=float(
            os.environ.get("BINANCE_TRAIL_START_TICKS")
            or os.environ.get("BINANCE_TRAIL_START_PIPS", "25")
        ),
        trail_step_pips=float(
            os.environ.get("BINANCE_TRAIL_STEP_TICKS")
            or os.environ.get("BINANCE_TRAIL_STEP_PIPS", "15")
        ),
    )
