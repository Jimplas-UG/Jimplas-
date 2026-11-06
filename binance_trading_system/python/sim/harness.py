"""Boot the real connector, engine and scanner on the fake exchange and audit them from outside.

Every invariant is computed from exchange truth, never from what the bot reports about itself.
Run one scenario per process: the bot keeps module-level state, and time is patched globally.
"""
from __future__ import annotations

import logging
import os
import random
import re
import sys
import tempfile
import traceback
from typing import Any, Callable, Iterable

from fake_exchange import FakeExchange, SimCrash, VClock, install_transport

START_EPOCH = 1_790_000_000.0  # Fixed so runs are comparable.
VOL = 50_000_000.0


class Capture(logging.Handler):
    """Keeps warnings and the decision-relevant info lines, with virtual timestamps."""

    KEEP = ("scanner closed", "scanner SHORT ", "scanner LONG", "EXEC_", "adopt", "RESCUE", "reconcile")

    def __init__(self, clock: VClock) -> None:
        super().__init__(logging.INFO)
        self.clock = clock
        self.rows: list[tuple[float, str, str, str]] = []
        self.counts: dict[str, int] = {}
        self.exits: dict[str, int] = {}
        self.problems: dict[str, int] = {}

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        self.counts[record.levelname] = self.counts.get(record.levelname, 0) + 1
        if "scanner closed" in msg and "reason=" in msg:
            why = msg.split("reason=")[1].split()[0]
            self.exits[why] = self.exits.get(why, 0) + 1
        if record.levelno >= logging.WARNING:
            key = re.sub(r"[0-9.]+", "#", msg)[:70]
            self.problems[key] = self.problems.get(key, 0) + 1
        if record.levelno >= logging.WARNING or any(k in msg for k in self.KEEP):
            if len(self.rows) < 20000:
                self.rows.append((self.clock.true, record.levelname, record.name, msg[:300]))


def prepare_env(state_dir: str | None = None) -> str:
    d = state_dir or tempfile.mkdtemp(prefix="bsv3sim")
    os.environ.update(
        {
            "SCANNER_EXEC": "1",
            "SCANNER_ENABLED": "1",
            "FORWARD_DRY_RUN": "0",
            "SCANNER_RISK_CONFIG_PATH": os.path.join(d, "risk.json"),
            "REST_BAN_FILE": os.path.join(d, "ban.json"),
            "BINANCE_SESSION_FILE": os.path.join(d, "session.json"),
            "TRADE_HISTORY_CACHE_FILE": os.path.join(d, "history.json"),
            "BILSHENZ_STATE_DIR": d,
            "LOG_DIR": d,
        }
    )
    return d


class Sim:
    def __init__(
        self,
        code_dir: str,
        symbols: list[str],
        *,
        testnet: bool = True,
        state_dir: str | None = None,
        **exchange_kw: Any,
    ) -> None:
        self.state_dir = prepare_env(state_dir)
        if code_dir not in sys.path:
            sys.path.insert(0, code_dir)
        self.clock = VClock(START_EPOCH)
        self.clock.install()
        self.ex = FakeExchange(self.clock, symbols, **exchange_kw)
        install_transport(lambda: self.ex)
        self.symbols = symbols
        self.testnet = testnet
        self.log = Capture(self.clock)
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.handlers = [self.log]
        self.exceptions: list[str] = []
        self.tracebacks: list[list[str]] = []
        self.conn: Any = None
        self.sc: Any = None
        self.boots = 0
        self.boot_recovery: list[dict[str, Any]] = []
        self.quote_vol = VOL
        self.stream_alive = True
        self.reboot_after_crash_s = 0.0
        self._reboot_at = 0.0
        self._next_sample = 0.0
        self.m: dict[str, Any] = {
            "multi_symbol_s": 0.0, "naked_long_s": 0.0, "unmanaged_s": 0.0, "phantom_s": 0.0,
            "qty_mismatch_s": 0.0, "worst_unmanaged_s": 0.0, "worst_phantom_s": 0.0,
            "worst_mismatch_s": 0.0, "peak_notional": 0.0, "peak_margin": 0.0, "peak_equity": 0.0,
            "max_drawdown": 0.0, "ticks": 0,
        }
        self._streak = {"unmanaged": 0.0, "phantom": 0.0, "mismatch": 0.0}

    # ---- lifecycle ----
    def boot(self, *, startup_ok: bool = True) -> None:
        """Fresh process: new connector and scanner, the same steps as main.py startup."""
        import binance_connector as bc
        import momentum_scanner as ms
        from pair_isolation import pair_gate

        pair_gate.__init__()
        self.boots += 1
        cfg = bc.BinanceConfig(api_key="simkey", api_secret="simsecret", testnet=self.testnet)
        self.conn = bc.BinanceConnector(cfg)
        self.conn.configure("simkey", "simsecret", self.testnet)
        self.sc = ms.MomentumScanner(self.conn, lambda: self.testnet)
        if hasattr(self.sc, "require_startup_recovery"):
            self.sc.require_startup_recovery()
        self.sc.load_symbols(self.symbols)
        self.sc.apply_volume_map({s: self.quote_vol for s in self.symbols})
        self.sc._volume_map_ready = True
        try:
            self.conn.load_all_symbol_specs()
        except Exception as e:  # noqa: BLE001
            self.exceptions.append(f"boot specs: {e}")
        if startup_ok:
            self.startup_recovery()

    def startup_recovery(self) -> None:
        """Mirror of main.startup_session_and_recovery."""
        from pair_isolation import pair_gate

        t0 = self.clock.true
        try:
            pair_gate.force_clear_close_gates("startup")
            self.conn.positions()
            self.conn.open_orders()
            self.sc.adopt_open_strategies_from_exchange()
            self.sc.reconcile_from_exchange()
            pair_gate.release_stale_close_gates(lambda: self.conn.positions() or [])
            ok = True
        except Exception as e:  # noqa: BLE001
            ok = False
            self.log.rows.append((self.clock.true, "WARNING", "sim", f"startup recovery skipped: {e}"))
        self.boot_recovery.append({"ok": ok, "virtual_s": self.clock.true - t0})

    def crash(self) -> None:
        """Process dies: all memory is lost. The exchange and files on disk remain."""
        self.conn = None
        self.sc = None

    # ---- driving ----
    def tick(self, sym: str, px: float, t: float) -> None:
        if t > self.clock.true:
            self.clock.true = t
        self.ex.set_price(sym, px)
        if self._reboot_at and self.clock.true >= self._reboot_at:
            self._reboot_at = 0.0
            self.boot()
        if self.sc is None or not self.stream_alive:
            self._sample()
            return
        self.m["ticks"] += 1
        vol = None if self.testnet else self.quote_vol
        try:
            self.sc.on_tick(sym, px, int(self.clock.true * 1000), None, vol)
        except SimCrash:
            self.crash()
            self._reboot_at = self.clock.true + self.reboot_after_crash_s
        except Exception as e:  # noqa: BLE001
            # scanner_stream._dispatch_ticks swallows these, so a raised tick skips its exits.
            self.exceptions.append(f"{type(e).__name__}: {str(e)[:160]}")
            if len(self.tracebacks) < 3:
                frames = traceback.extract_tb(e.__traceback__)
                self.tracebacks.append([f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in frames[-6:]])
        self._sample()

    def run(
        self,
        ticks: Iterable[tuple[float, str, float]],
        hooks: list[tuple[float, Callable[["Sim"], None]]] | None = None,
    ) -> None:
        pending = sorted(hooks or [], key=lambda h: h[0])
        for t, sym, px in ticks:
            while pending and START_EPOCH + pending[0][0] <= t:
                pending.pop(0)[1](self)
            self.tick(sym, px, t)
        for _, fn in pending:
            fn(self)

    # ---- invariants ----
    def _scanner_view(self) -> dict[str, tuple[float, float]]:
        out: dict[str, tuple[float, float]] = {}
        if self.sc is None:
            return out
        for c in self.sc._coins.values():
            s = c.short.qty if c.short else 0.0
            lg = (c.long1.qty if c.long1 else 0.0) + (c.long2.qty if c.long2 else 0.0)
            if s > 0 or lg > 0:
                out[c.symbol] = (s, lg)
        return out

    def _sample(self) -> None:
        now = self.clock.true
        if now < self._next_sample:
            return
        step = 1.0 if self._next_sample == 0 else now - self._next_sample + 1.0
        self._next_sample = now + 1.0
        ex = self.ex
        book: dict[str, list[float]] = {}
        for (sym, ps), p in ex.pos.items():
            row = book.setdefault(sym, [0.0, 0.0])
            row[0 if ps == "SHORT" else 1] += p.qty
        m = self.m
        if len(book) > 1:
            m["multi_symbol_s"] += step
        if any(s <= 0 and lg > 0 for s, lg in book.values()):
            m["naked_long_s"] += step
        view = self._scanner_view()
        unmanaged = self.sc is not None and any(sym not in view for sym in book)
        phantom = any(sym not in book for sym in view)
        mismatch = False
        for sym, (s, lg) in view.items():
            if sym in book:
                es, el = book[sym]
                # Two lot steps of slack: the bot books the unrounded size on a full fill.
                step = 2.0 * ex.step_of.get(sym, ex.step)
                if abs(s - es) > max(step, 0.001 * es) or abs(lg - el) > max(step, 0.001 * el):
                    mismatch = True
        for key, flag, total, worst in (
            ("unmanaged", unmanaged, "unmanaged_s", "worst_unmanaged_s"),
            ("phantom", phantom, "phantom_s", "worst_phantom_s"),
            ("mismatch", mismatch, "qty_mismatch_s", "worst_mismatch_s"),
        ):
            if flag:
                self._streak[key] += step
                m[total] += step
                m[worst] = max(m[worst], self._streak[key])
            else:
                self._streak[key] = 0.0
        notional = sum(p.qty * ex.px[s] for (s, _), p in ex.pos.items())
        m["peak_notional"] = max(m["peak_notional"], notional)
        m["peak_margin"] = max(m["peak_margin"], ex.margin_used())
        eq = ex.equity()
        m["peak_equity"] = max(m["peak_equity"], eq)
        m["max_drawdown"] = max(m["max_drawdown"], m["peak_equity"] - eq)

    def summary(self) -> dict[str, Any]:
        ex = self.ex
        opens = [f for f in ex.fills if f["action"] == "OPEN"]
        by_cid: dict[str, int] = {}
        for f in opens:
            by_cid[f["cid"]] = by_cid.get(f["cid"], 0) + 1
        dups = sorted(c for c, n in by_cid.items() if n > 1)
        # Replay the fills: a trade holds one SHORT fill and at most two LONG fills.
        stacked = 0
        held: dict[tuple[str, str], int] = {}
        qty: dict[tuple[str, str], float] = {}
        for f in ex.fills:
            k = (f["symbol"], f["ps"])
            if f["action"] == "OPEN":
                held[k] = held.get(k, 0) + 1
                qty[k] = qty.get(k, 0.0) + f["qty"]
                if held[k] > (1 if f["ps"] == "SHORT" else 2):
                    stacked += 1
            else:
                qty[k] = qty.get(k, 0.0) - f["qty"]
                if qty[k] <= 1e-9:
                    held[k] = 0
                    qty[k] = 0.0
        wrong_lev = sum(
            1 for f in opens
            if (f["ps"] == "SHORT" and f["leverage"] != 5) or (f["ps"] == "LONG" and f["leverage"] != 10)
        )
        pnl = sum(f["pnl"] for f in ex.fills)
        out = {
            "signals": sum(1 for f in opens if f["ps"] == "SHORT"),
            "orders_sent": ex.requests.get("POST /fapi/v1/order", 0),
            "fills": len(ex.fills),
            "opens": len(opens),
            "rejects": len(ex.rejects),
            "faults_fired": len(ex.fault_hits),
            "dup_client_ids": dups,
            "stacked_fills": stacked,
            "wrong_leverage_fills": wrong_lev,
            "liquidations": len(ex.liquidations),
            "partial_fills": sum(
                1 for o in ex.orders.values() if o["status"] == "EXPIRED" and float(o["executedQty"]) > 0
            ),
            "unhandled_tick_exceptions": len(self.exceptions),
            "exception_sample": sorted(set(self.exceptions))[:4],
            "tracebacks": self.tracebacks,
            "end_open_positions": {f"{s}:{p}": round(v.qty, 4) for (s, p), v in ex.pos.items()},
            "scanner_open": {k: [round(x, 4) for x in v] for k, v in self._scanner_view().items()},
            "realized_pnl": round(pnl, 4),
            "fees": round(ex.fees, 4),
            "funding": round(ex.funding_paid, 4),
            "slippage": round(ex.slippage_cost, 4),
            "net": round(ex.equity() - ex.start_wallet, 4),
            "api_calls": sum(ex.requests.values()),
            "log_counts": dict(self.log.counts),
            "exit_reasons": dict(self.log.exits),
            "top_problems": dict(sorted(self.log.problems.items(), key=lambda kv: -kv[1])[:12]),
        }
        out.update({k: round(v, 2) if isinstance(v, float) else v for k, v in self.m.items()})
        return out

    def trace(self) -> list[dict[str, Any]]:
        """Every order the exchange saw, for baseline-versus-patched comparison."""
        return [dict(r) for r in self.ex.order_log]


def path(
    t0: float,
    px0: float,
    segments: list[tuple[float, float]],
    *,
    dt: float = 1.0,
    noise: float = 0.0,
    seed: int = 1,
) -> list[tuple[float, float]]:
    """Piecewise path: segments are (seconds, end_multiple_of_px0), with optional seeded noise."""
    rng = random.Random(seed)
    t = t0
    px = px0
    out = []
    for dur, mult in segments:
        target = px0 * mult
        n = max(1, int(dur / dt))
        step = (target - px) / n
        for _ in range(n):
            px += step
            t += dt
            out.append((t, px * (1 + rng.gauss(0, noise)) if noise else px))
    return out


def merge(*series: tuple[str, list[tuple[float, float]]]) -> list[tuple[float, str, float]]:
    rows = [(t, sym, px) for sym, pts in series for t, px in pts]
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows
