"""Deterministic scenarios. All market data here is synthetic; history lives in replay_history.py."""
from __future__ import annotations

import json
import math
import os
import random
from typing import Any, Callable

from fake_exchange import Fault
from harness import START_EPOCH, Sim, merge, path

T0 = START_EPOCH
A, B, C = "AAAUSDT", "BBBUSDT", "CCCUSDT"

# Short near 1596s, Long 1 near 2182s, Long 2 near 2280s, SHORT_TP exit near 3136s.
CORE = [(1200, 1.0), (360, 1.08), (40, 1.0715), (240, 1.0715), (120, 1.093), (120, 1.0715),
        (200, 1.115), (600, 1.05), (1800, 1.02), (1200, 1.02)]


def core_ticks(extra: list[tuple[float, float]] | None = None) -> list[tuple[float, str, float]]:
    a = path(T0, 1.0, CORE + (extra or []), noise=0.0002)
    n = int(a[-1][0] - T0)
    b = path(T0, 2.0, [(n, 2.0)], noise=0.0002, seed=2)
    return merge((A, a), (B, b))


def _fault_case(testnet: bool, *faults: Fault, **ex: Any) -> Callable[[str], Sim]:
    def run(code: str) -> Sim:
        s = Sim(code, [A, B], testnet=testnet, **ex)
        s.boot()
        s.ex.faults = list(faults)
        s.run(core_ticks())
        return s

    return run


def _http(status: int, code: int, msg: str, **kw: Any) -> dict[str, Any]:
    return {"kind": "http", "status": status, "code": code, "msg": msg, **kw}


ORDER_FAULTS: dict[str, dict[str, Any]] = {
    "http429": _http(429, -1003, "Too many requests.", retry_after=5.0),
    "http418": _http(418, -1003, "IP banned", retry_after=120.0),
    "http503_not_processed": _http(503, -1001, "Internal error; unable to process your request."),
    "http503_processed": {"kind": "http_after", "status": 503, "code": -1000,
                          "msg": "Unknown error, please check your request or try again later."},
    "http502_html": {"kind": "http_html", "status": 502},
    "timeout_not_processed": {"kind": "timeout_before"},
    "timeout_processed": {"kind": "timeout_after"},
    "reset_not_processed": {"kind": "reset_before"},
    "reset_processed": {"kind": "reset_after"},
    "closed_processed": {"kind": "closed_after"},
    "invalid_json_processed": {"kind": "bad_json_after"},
    "empty_body_processed": {"kind": "empty_after"},
    "truncated_processed": {"kind": "truncated_after"},
    "late_landing_5s": {"kind": "late_landing", "delay_s": 5.0},
    "late_landing_45s": {"kind": "late_landing", "delay_s": 45.0},
    "slow_response_6s": {"kind": "delay", "delay_s": 6.0},
    "auth_failure": _http(401, -2015, "Invalid API-key, IP, or permissions for action."),
    "invalid_symbol": _http(400, -1121, "Invalid symbol."),
    "invalid_quantity": _http(400, -1111, "Precision is over the maximum defined for this asset."),
    "insufficient_margin": _http(400, -2019, "Margin is insufficient."),
    "order_rejected": _http(400, -2010, "Order would immediately trigger."),
}
LEGS = {"short": "_SHORT_", "long1": "_LONG1_", "long2": "_LONG2_", "close": "_CL"}

SCENARIOS: dict[str, Callable[[str], Sim]] = {}
GROUP: dict[str, str] = {}


def register(name: str, group: str, fn: Callable[[str], Sim]) -> None:
    SCENARIOS[name] = fn
    GROUP[name] = group


for mode, tn in (("testnet", True), ("mainnet", False)):
    register(f"clean.{mode}", "api", _fault_case(tn))
    for fname, spec in ORDER_FAULTS.items():
        for leg, match in LEGS.items():
            register(
                f"api.{mode}.{leg}.{fname}", "api",
                _fault_case(tn, Fault(leg=match, count=1, **spec)),
            )
    # The dangerous pair: the order lands, the reply is lost, and the lookup fails too.
    for leg in ("short", "long1", "long2"):
        for look_name, look in (
            ("lookup503", _http(503, -1001, "Internal error")),
            ("lookup_timeout", {"kind": "timeout_before"}),
            ("lookup_429", _http(429, -1003, "Too many requests.", retry_after=1.0)),
        ):
            register(
                f"combo.{mode}.{leg}.reply_lost_{look_name}", "combo",
                _fault_case(
                    tn,
                    Fault(kind="timeout_after", leg=LEGS[leg], count=1),
                    Fault(path="/fapi/v1/order", method="GET", count=3, **look),
                ),
            )
    # Reads failing while a trade runs.
    for rname, rpath in (("account", "/fapi/v2/account"), ("positionrisk", "/fapi/v2/positionRisk")):
        register(
            f"reads.{mode}.{rname}_503_storm", "reads",
            _fault_case(tn, Fault(path=rpath, method="GET", count=40, skip=3,
                                  **_http(503, -1001, "Internal error"))),
        )
        register(
            f"reads.{mode}.{rname}_invalid_json", "reads",
            _fault_case(tn, Fault(path=rpath, method="GET", count=10, skip=3, kind="bad_json_after")),
        )
    register(
        f"combo.{mode}.everything_503_for_60_calls", "combo",
        _fault_case(tn, Fault(path="*", method="*", count=60, skip=12,
                              **_http(503, -1001, "Internal error"))),
    )
    register(
        f"combo.{mode}.alternating_timeouts_on_orders", "combo",
        _fault_case(tn, Fault(kind="timeout_after", count=2, leg="_LONG"),
                    Fault(kind="reset_before", count=2, leg="_CL")),
    )
    register(
        f"reads.{mode}.hedge_mode_read_503", "reads",
        _fault_case(tn, Fault(path="/fapi/v1/positionSide/dual", method="GET", count=8,
                              **_http(503, -1001, "Internal error"))),
    )
    register(
        f"reads.{mode}.dup_ids_always_rejected", "reads",
        _fault_case(tn, Fault(kind="timeout_after", leg="_SHORT_", count=1), dup_mode="always"),
    )


# ---- restarts and crashes ----
def _restart(at: float, down_s: float, *, testnet: bool = True) -> Callable[[str], Sim]:
    def run(code: str) -> Sim:
        s = Sim(code, [A, B], testnet=testnet)
        s.boot()
        s.run(core_ticks(), hooks=[(at, lambda x: x.crash()), (at + down_s, lambda x: x.boot())])
        return s

    return run


for mode, tn in (("testnet", True), ("mainnet", False)):
    register(f"restart.{mode}.flat", "restart", _restart(900, 30, testnet=tn))
    register(f"restart.{mode}.while_pending", "restart", _restart(1580, 10, testnet=tn))
    register(f"restart.{mode}.short_open", "restart", _restart(1700, 30, testnet=tn))
    register(f"restart.{mode}.short_long1_open", "restart", _restart(2230, 30, testnet=tn))
    register(f"restart.{mode}.all_legs_open", "restart", _restart(2400, 30, testnet=tn))
    register(f"restart.{mode}.down_10min_all_legs", "restart", _restart(2400, 600, testnet=tn))


def _crash_on(leg: str, kind: str, down_s: float, testnet: bool = True) -> Callable[[str], Sim]:
    """The process dies at the moment an order is in flight."""

    def run(code: str) -> Sim:
        s = Sim(code, [A, B], testnet=testnet)
        s.boot()
        s.ex.faults = [Fault(kind=kind, leg=leg, count=1)]
        s.reboot_after_crash_s = down_s
        s.run(core_ticks())
        return s

    return run


for leg, match in LEGS.items():
    register(f"restart.crash_after_order_landed.{leg}", "restart", _crash_on(match, "crash_after", 20))
    register(f"restart.crash_before_order_landed.{leg}", "restart", _crash_on(match, "crash_before", 20))


def blind_boot(code: str) -> Sim:
    """Reboot with the book unreadable while another coin qualifies. Must not open it."""
    s = Sim(code, [A, B], testnet=False)
    s.boot()
    a = path(T0, 1.0, CORE + [(3000, 1.02)], noise=0.0002)
    b = path(T0, 2.0, [(2500, 2.0), (360, 2.16), (40, 2.143), (2600, 2.143)], noise=0.0002, seed=2)
    outage = [
        Fault(path="/fapi/v2/positionRisk", method="GET", count=-1, **_http(503, -1001, "Internal error")),
        Fault(path="/fapi/v2/account", method="GET", count=-1, **_http(503, -1001, "Internal error")),
    ]

    def reboot(x: Sim) -> None:
        x.ex.faults = list(outage)
        x.boot()

    def heal(x: Sim) -> None:
        x.ex.faults = []

    s.run(merge((A, a), (B, b)), hooks=[(1800, lambda x: x.crash()), (1830, reboot), (3300, heal)])
    return s


register("restart.blind_boot_book_unreadable", "restart", blind_boot)


def blind_boot_no_position(code: str) -> Sim:
    s = Sim(code, [A, B], testnet=False)
    outage = [
        Fault(path="/fapi/v2/positionRisk", method="GET", count=120, **_http(503, -1001, "Internal error")),
        Fault(path="/fapi/v2/account", method="GET", count=120, **_http(503, -1001, "Internal error")),
    ]
    s.ex.faults = outage
    s.boot()
    s.run(core_ticks())
    return s


register("restart.blind_boot_flat_book", "restart", blind_boot_no_position)


def cooldown_after_restart(code: str) -> Sim:
    """Exit, restart inside the cooldown, and the same coin qualifies again."""
    s = Sim(code, [A, B], testnet=False)
    s.boot()
    segs = CORE[:8] + [(100, 1.02), (500, 1.02), (240, 1.105), (40, 1.097), (1500, 1.05)]
    a = path(T0, 1.0, segs, noise=0.0002)
    b = path(T0, 2.0, [(a[-1][0] - T0, 2.0)], noise=0.0002, seed=2)
    s.run(merge((A, a), (B, b)), hooks=[(3200, lambda x: x.crash()), (3210, lambda x: x.boot())])
    return s


register("restart.inside_entry_cooldown", "restart", cooldown_after_restart)


def cooldown_survives(code: str) -> Sim:
    """Direct check: after an exit and a restart, is the coin still cooling down?"""
    s = Sim(code, [A, B], testnet=False)
    s.boot()

    def check(x: Sim) -> None:
        x.crash()
        x.boot()
        if not x.sc._in_entry_cooldown(A):
            x.exceptions.append("cooldown_lost_on_restart")

    s.run(core_ticks(), hooks=[(3150, check)])
    return s


register("restart.cooldown_survives_restart", "restart", cooldown_survives)


# ---- circuit breaker, end to end ----
def _shorts(s: Sim) -> list[float]:
    return [r["t"] for r in s.ex.order_log if r["ps"] == "SHORT" and r["side"] == "SELL" and r["type"] == "MARKET"]


def breaker_blocks_entry(code: str) -> Sim:
    """Tripped just before the signal: no entry during the pause, entry once it ends."""
    s = Sim(code, [A, B], testnet=False)
    s.boot()

    def trip(x: Sim) -> None:
        for _ in range(3):
            x.sc._engine.breaker.record_failure("orders", "sim")

    s.run(core_ticks(), hooks=[(1590, trip)])
    times = _shorts(s)
    if not times or times[0] < 1710:
        s.exceptions.append(f"breaker_did_not_hold_entry:{times[:1]}")
    return s


register("breaker.blocks_new_entry_then_resumes", "breaker", breaker_blocks_entry)


def breaker_keeps_exits(code: str) -> Sim:
    """Open during the exit window: the close must still go out, and it must not force one."""
    s = Sim(code, [A, B], testnet=False)
    s.boot()

    def trip(x: Sim) -> None:
        for _ in range(3):
            x.sc._engine.breaker.record_failure("orders", "sim")
        if x.ex.pos.get((A, "SHORT")) is None:
            x.exceptions.append("position_missing_before_trip")

    s.run(core_ticks(), hooks=[(3100, trip)])
    closes = [r["t"] for r in s.ex.order_log if r["ps"] == "SHORT" and r["side"] == "BUY" and r["type"] == "MARKET"]
    if closes != [3136.0]:
        s.exceptions.append(f"exit_changed_by_breaker:{closes}")
    return s


register("breaker.exits_run_and_nothing_is_liquidated", "breaker", breaker_keeps_exits)


def breaker_keeps_hedges(code: str) -> Sim:
    s = Sim(code, [A, B], testnet=False)
    s.boot()

    def trip(x: Sim) -> None:
        for _ in range(3):
            x.sc._engine.breaker.record_failure("orders", "sim")

    s.run(core_ticks(), hooks=[(2170, trip)])
    longs = [r["t"] for r in s.ex.order_log if r["ps"] == "LONG" and r["side"] == "BUY" and r["type"] == "MARKET"]
    if longs[:1] != [2182.0]:
        s.exceptions.append(f"hedge_blocked_by_breaker:{longs}")
    return s


register("breaker.recovery_hedges_keep_running", "breaker", breaker_keeps_hedges)


def breaker_from_real_failures(code: str) -> Sim:
    """Trips on its own from a run of book-read failures, then clears after reads recover."""
    s = Sim(code, [A, B], testnet=False)
    s.boot()
    s.ex.faults = [
        Fault(path="/fapi/v2/positionRisk", method="GET", count=-1, **_http(503, -1001, "Internal error")),
        Fault(path="/fapi/v2/account", method="GET", count=-1, **_http(503, -1001, "Internal error")),
    ]
    seen: dict[str, Any] = {}

    def look(x: Sim) -> None:
        seen["trips"] = x.sc._engine.breaker.trips

    def heal(x: Sim) -> None:
        x.ex.faults = []

    s.run(core_ticks(), hooks=[(1500, look), (1560, heal)])
    if not seen.get("trips"):
        s.exceptions.append("breaker_never_tripped_on_read_failures")
    if not _shorts(s):
        s.exceptions.append("trading_never_resumed_after_health_returned")
    return s


register("breaker.trips_on_read_failures_and_resumes", "breaker", breaker_from_real_failures)


# ---- state files ----
def _corrupt(fname: str, data: bytes) -> Callable[[str], Sim]:
    def run(code: str) -> Sim:
        s = Sim(code, [A, B], testnet=True)
        with open(os.path.join(s.state_dir, fname), "wb") as fh:
            fh.write(data)
        s.boot()
        s.run(core_ticks())
        return s

    return run


for fname in ("risk.json", "ban.json", "session.json", "history.json"):
    register(f"state.corrupt.{fname}", "state", _corrupt(fname, b'{"truncated": '))
    register(f"state.empty.{fname}", "state", _corrupt(fname, b""))
    register(f"state.binary.{fname}", "state", _corrupt(fname, bytes(range(256))))


def state_dir_unwritable(code: str) -> Sim:
    s = Sim(code, [A, B], testnet=True)
    bad = os.path.join(s.state_dir, "no", "such", "dir")
    os.environ["SCANNER_RISK_CONFIG_PATH"] = os.path.join(bad, "risk.json")
    os.environ["REST_BAN_FILE"] = os.path.join(bad, "ban.json")
    s.boot()
    s.ex.faults = [Fault(leg="_LONG1_", count=1, **_http(418, -1003, "banned", retry_after=30.0))]
    s.run(core_ticks())
    return s


register("state.persistence_unavailable", "state", state_dir_unwritable)


# ---- internal failures ----
def clock_drift(skew: float, at: float) -> Callable[[str], Sim]:
    def run(code: str) -> Sim:
        s = Sim(code, [A, B], testnet=True)
        s.boot()

        def drift(x: Sim) -> None:
            x.clock.skew = skew

        s.run(core_ticks(), hooks=[(at, drift)])
        return s

    return run


register("internal.clock_drift_plus_2s", "internal", clock_drift(2.0, 1000))
register("internal.clock_drift_plus_90s", "internal", clock_drift(90.0, 1000))
register("internal.clock_drift_minus_90s", "internal", clock_drift(-90.0, 1000))
register("internal.clock_drift_90s_while_hedged", "internal", clock_drift(90.0, 2400))


def stream_gap(at: float, dur: float) -> Callable[[str], Sim]:
    def run(code: str) -> Sim:
        s = Sim(code, [A, B], testnet=True)
        s.boot()

        def off(x: Sim) -> None:
            x.stream_alive = False

        def on(x: Sim) -> None:
            x.stream_alive = True

        s.run(core_ticks(), hooks=[(at, off), (at + dur, on)])
        return s

    return run


register("internal.market_data_gap_flat_5min", "internal", stream_gap(1100, 300))
register("internal.market_data_gap_short_open_10min", "internal", stream_gap(1700, 600))
register("internal.market_data_gap_hedged_10min", "internal", stream_gap(2400, 600))


def stale_frozen_symbol(code: str) -> Sim:
    """The stream stops sending one coin while others keep ticking, then it qualifies on old data."""
    s = Sim(code, [A, B], testnet=False)
    s.boot()
    ticks = core_ticks()
    # Coin A freezes at the moment it would enter; the true price falls 10% meanwhile.
    out = []
    for t, sym, px in ticks:
        if sym == A and 1590 <= t - T0 <= 2400:
            s.ex.px[A] = px
            continue
        out.append((t, sym, px))
    s.run(out)
    return s


register("internal.one_symbol_silent_at_entry", "internal", stale_frozen_symbol)


def external_close(code: str) -> Sim:
    """Operator closes everything on the Binance site while the bot holds state."""
    s = Sim(code, [A, B], testnet=False)
    s.boot()

    def wipe(x: Sim) -> None:
        for (sym, ps), p in list(x.ex.pos.items()):
            x.ex._book_close(sym, ps, p.qty, x.ex.px[sym], source="EXTERNAL", cid="EXT")

    s.run(core_ticks(), hooks=[(2400, wipe)])
    return s


register("internal.external_close_on_exchange", "internal", external_close)


def external_partial(code: str) -> Sim:
    s = Sim(code, [A, B], testnet=False)
    s.boot()

    def trim(x: Sim) -> None:
        p = x.ex.pos[(A, "LONG")]
        x.ex._book_close(A, "LONG", round(p.qty / 2, 1), x.ex.px[A], source="EXTERNAL", cid="EXT")

    s.run(core_ticks(), hooks=[(2400, trim)])
    return s


register("internal.external_partial_close", "internal", external_partial)


def external_open(code: str) -> Sim:
    """A short appears on another coin that the bot did not open."""
    s = Sim(code, [A, B], testnet=False)
    s.boot()

    def add(x: Sim) -> None:
        x.ex._book_open(B, "SHORT", 50.0, x.ex.px[B], "EXT")

    s.run(core_ticks(), hooks=[(1000, add)])
    return s


register("internal.unexpected_short_other_coin", "internal", external_open)


def exec_off_while_open(code: str) -> Sim:
    s = Sim(code, [A, B], testnet=True)
    s.boot()

    def off(x: Sim) -> None:
        os.environ["SCANNER_EXEC"] = "0"

    s.run(core_ticks(), hooks=[(2400, off)])
    return s


register("internal.trading_switched_off_while_open", "internal", exec_off_while_open)


def maintenance(at: float, dur: float, move: float) -> Callable[[str], Sim]:
    """REST and the stream both go dark; price moves meanwhile."""

    def run(code: str) -> Sim:
        s = Sim(code, [A, B], testnet=False)
        s.boot()

        def down(x: Sim) -> None:
            x.ex.down_until = x.clock.true + dur
            x.stream_alive = False

        def up(x: Sim) -> None:
            x.stream_alive = True

        a = path(T0, 1.0, CORE[:7] + [(dur, 1.115 * (1 + move)), (3000, 1.05)], noise=0.0002)
        b = path(T0, 2.0, [(a[-1][0] - T0, 2.0)], noise=0.0002, seed=2)
        s.run(merge((A, a), (B, b)), hooks=[(at, down), (at + dur, up)])
        return s

    return run


# ---- market regimes (all synthetic) ----
class Regime:
    """Per-coin log-price process with scheduled shocks. Seeded, and uses no future data."""

    def __init__(self, seed: int, symbols: list[str], hours: float, *, dt: float = 2.0) -> None:
        self.rng = random.Random(seed)
        self.symbols = symbols
        self.hours = hours
        self.dt = dt
        self.drift = {s: 0.0 for s in symbols}  # Per hour, in percent.
        self.vol = {s: 0.15 for s in symbols}  # Per sqrt(hour), in percent.
        self.shocks: list[tuple[float, float, str, float]] = []

    def shock(self, t_h: float, dur_s: float, sym: str, pct: float) -> None:
        self.shocks.append((t_h * 3600, dur_s, sym, pct))

    def everyone(self, t_h: float, dur_s: float, pct: float) -> None:
        for s in self.symbols:
            self.shock(t_h, dur_s, s, pct * self.rng.uniform(0.8, 1.2))

    def ticks(self, t0: float = T0) -> list[tuple[float, str, float]]:
        n = int(self.hours * 3600 / self.dt)
        out = []
        for i, s in enumerate(self.symbols):
            lp = math.log(1.0 + i)
            rng = random.Random(self.rng.random())
            mu = self.drift[s] / 100 / 3600 * self.dt
            sd = self.vol[s] / 100 * math.sqrt(self.dt / 3600)
            mine = sorted(x for x in self.shocks if x[2] == s)
            k = 0
            active: list[tuple[float, float, float]] = []
            for j in range(n):
                t = j * self.dt
                while k < len(mine) and mine[k][0] <= t:
                    st, dur, _, pct = mine[k]
                    active.append((st + dur, math.log(1 + pct / 100) / max(1.0, dur / self.dt), dur))
                    k += 1
                inc = mu + rng.gauss(0, sd)
                for end, per, _ in active:
                    if t < end:
                        inc += per
                active = [a for a in active if t < a[0]]
                lp += inc
                out.append((t0 + t, s, math.exp(lp)))
        out.sort(key=lambda r: (r[0], r[1]))
        return out


SYMS = [f"{c}{c}{c}USDT" for c in "ABCDEF"]


def _pump_fade(r: Regime, t: float, sym: str, up: float, down: float, *, up_s: float = 480, down_s: float = 900) -> None:
    r.shock(t, up_s, sym, up)
    r.shock(t + up_s / 3600 + 0.02, down_s, sym, down)


def regime_case(builder: Callable[[int], tuple[Regime, dict[str, Any], list]], seed: int) -> Callable[[str], Sim]:
    def run(code: str) -> Sim:
        r, ex, hooks = builder(seed)
        s = Sim(code, r.symbols, testnet=False, **ex)
        s.boot()
        s.run(r.ticks(), hooks=hooks)
        return s

    return run


def bull(seed: int) -> tuple:
    r = Regime(seed, SYMS, 12)
    for s in SYMS:
        r.drift[s] = r.rng.uniform(0.6, 1.4)
        r.vol[s] = 0.35
    for i in range(10):
        s = r.rng.choice(SYMS)
        t = 0.6 + i * 1.05
        r.shock(t, 420, s, r.rng.uniform(6, 11))
        # The pullback lands inside the 15m window, so the bot shorts into a rising market.
        r.shock(t + 480 / 3600, 120, s, -1.4)
        if i % 2:  # Breakout, pullback, then continuation through the entry.
            r.shock(t + 660 / 3600, 900, s, r.rng.uniform(5, 12))
        else:  # A shallow pullback inside the trend.
            r.shock(t + 660 / 3600, 600, s, r.rng.uniform(1.5, 3.5))
    return r, {}, []


def bear(seed: int) -> tuple:
    r = Regime(seed, SYMS, 12)
    for s in SYMS:
        r.drift[s] = r.rng.uniform(-1.4, -0.6)
        r.vol[s] = 0.35
    for i in range(10):
        s = r.rng.choice(SYMS)
        t = 0.6 + i * 1.05
        _pump_fade(r, t, s, r.rng.uniform(5.5, 8), r.rng.uniform(-10, -6))
        if i % 3 == 0:
            r.everyone(t + 0.6, 240, -4.5)
    return r, {}, []


def chop_narrow(seed: int) -> tuple:
    r = Regime(seed, SYMS, 12)
    for s in SYMS:
        r.vol[s] = 0.08
    for i in range(12):
        s = r.rng.choice(SYMS)
        _pump_fade(r, 0.5 + i * 0.9, s, 5.4, -5.0, up_s=500, down_s=300)
    return r, {}, []


def chop_wide(seed: int) -> tuple:
    r = Regime(seed, SYMS, 12)
    for s in SYMS:
        r.vol[s] = 0.9
    for i in range(30):
        s = r.rng.choice(SYMS)
        sign = 1 if i % 2 else -1
        r.shock(0.4 + i * 0.37, 180, s, sign * r.rng.uniform(4, 7))
    return r, {}, []


def highvol(seed: int) -> tuple:
    r = Regime(seed, SYMS, 12)
    hooks = []
    for s in SYMS:
        r.vol[s] = 1.6
    for i in range(16):
        s = r.rng.choice(SYMS)
        t = 0.5 + i * 0.7
        r.shock(t, 4, s, r.rng.uniform(5, 12) * (1 if i % 3 else -1))  # Near-instant gap.
        r.shock(t + 0.03, 60, s, r.rng.uniform(-9, -3))  # Wick reverses.

        def wide(x: Sim, bps: float = r.rng.uniform(30, 80)) -> None:
            x.ex.spread_bps = bps

        def tight(x: Sim) -> None:
            x.ex.spread_bps = 2.0

        hooks += [(t * 3600, wide), (t * 3600 + 300, tight)]
    return r, {}, hooks


def thin(seed: int) -> tuple:
    r = Regime(seed, SYMS, 12)
    for i in range(10):
        s = r.rng.choice(SYMS)
        _pump_fade(r, 0.5 + i * 1.05, s, r.rng.uniform(6, 9), r.rng.uniform(-9, -4))
    return r, {"depth_usd": 120.0, "spread_bps": 35.0, "slip_bps": 15.0}, []


def event(seed: int) -> tuple:
    """NFP/CPI/rate-style shock, synthetic: spike, reversal, wide spreads, a burst of 5xx."""
    r = Regime(seed, SYMS, 12)
    hooks = []
    for k, t in enumerate((1.5, 4.0, 6.5, 9.0)):
        s = r.rng.choice(SYMS)
        _pump_fade(r, t - 0.4, s, r.rng.uniform(6, 9), -1.2, up_s=420, down_s=120)
        r.everyone(t, 30, 7.0 if k % 2 else -6.0)
        r.everyone(t + 0.02, 120, -9.0 if k % 2 else 8.0)

        def burst(x: Sim) -> None:
            x.ex.spread_bps = 60.0
            x.ex.faults.append(Fault(kind="http", path="*", method="*", count=25, status=503,
                                     code=-1001, msg="Internal error"))

        def calm(x: Sim) -> None:
            x.ex.spread_bps = 2.0

        hooks += [(t * 3600, burst), (t * 3600 + 400, calm)]
    return r, {}, hooks


def flash(seed: int) -> tuple:
    r = Regime(seed, SYMS, 12)
    hooks = []
    for k, t in enumerate((1.5, 3.5, 3.56, 6.0, 8.5)):
        s = r.rng.choice(SYMS)
        _pump_fade(r, t - 0.35, s, 7.0, -1.0, up_s=420, down_s=100)
        r.everyone(t, 20, -25.0 if k % 2 == 0 else 22.0)
        r.everyone(t + 0.02, 90, 30.0 if k % 2 == 0 else -18.0)

        def wide(x: Sim) -> None:
            x.ex.spread_bps = 150.0

        def tight(x: Sim) -> None:
            x.ex.spread_bps = 2.0

        hooks += [(t * 3600, wide), (t * 3600 + 200, tight)]
    return r, {}, hooks


def session(seed: int) -> tuple:
    """Quiet book, funding crossings, a maintenance window with moved price, and reconnection."""
    r = Regime(seed, SYMS, 20)
    hooks = []
    for s in SYMS:
        r.vol[s] = 0.1
    for i in range(10):
        s = r.rng.choice(SYMS)
        _pump_fade(r, 0.6 + i * 1.8, s, r.rng.uniform(5.5, 8), -5.0)

    def down(x: Sim) -> None:
        x.ex.down_until = x.clock.true + 1800
        x.stream_alive = False

    def up(x: Sim) -> None:
        x.stream_alive = True

    r.everyone(9.0 + 0.1, 900, 6.0)
    hooks += [(9.0 * 3600, down), (9.0 * 3600 + 1800, up)]
    return r, {"depth_usd": 400.0, "spread_bps": 8.0, "funding_rate": 0.0005}, hooks


REGIMES = {
    "A_bull": bull, "B_bear": bear, "C1_chop_narrow": chop_narrow, "C2_chop_wide": chop_wide,
    "D_high_vol": highvol, "E_low_liquidity": thin, "F_event_shock": event,
    "G_flash_crash": flash, "H_session_maintenance": session,
}
for name, fn in REGIMES.items():
    for seed in (11, 22, 33):
        register(f"market.{name}.seed{seed}", "market", regime_case(fn, seed))
    register(f"market.{name}.seed44.tp_accepted", "market",
             (lambda f: lambda code: _with_tp(f, code))(fn))


def _with_tp(builder: Callable[[int], tuple], code: str) -> Sim:
    r, ex, hooks = builder(44)
    s = Sim(code, r.symbols, testnet=False, tp_mode="accept", **ex)
    s.boot()
    s.run(r.ticks(), hooks=hooks)
    return s


for mv, label in ((0.03, "up3"), (0.08, "up8"), (-0.08, "down8")):
    register(f"internal.maintenance_30min_hedged_{label}", "internal", maintenance(2400, 1800, mv))


# Price gaps with every leg open: Short, Long 1 and Long 2 are all live near 2280s.
GAP_LEAD = CORE[:7] + [(60, 1.115)]


def gap_case(pct: float, *faults: Fault) -> Callable[[str], Sim]:
    def run(code: str) -> Sim:
        level = 1.115 * (1 + pct / 100)
        a = path(T0, 1.0, GAP_LEAD + [(1, level), (2400, level)], noise=0.0002)
        n = int(a[-1][0] - T0)
        b = path(T0, 2.0, [(n, 2.0)], noise=0.0002, seed=2)
        s = Sim(code, [A, B], testnet=False)
        s.boot()
        s.ex.faults = list(faults)
        s.run(merge((A, a), (B, b)))
        return s

    return run


for label, pct in (("down5", -5.0), ("down12", -12.0), ("down20", -20.0), ("up25", 25.0)):
    register(f"gap.all_legs_open.{label}", "gap", gap_case(pct))
register(
    "gap.all_legs_open.down12_reads_failing", "gap",
    gap_case(-12.0, Fault(path="/fapi/v2/positionRisk", method="GET", count=60, skip=40,
                          **_http(503, -1001, "Internal error"))),
)


def dump(s: Sim, name: str, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"name": name, "summary": s.summary(), "trace": s.trace(), "boot": s.boot_recovery,
                   "log_tail": [r[1:] for r in s.log.rows[-40:]]}, fh)
