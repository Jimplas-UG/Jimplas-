#!/usr/bin/env python3
"""Protective layer: breaker, instance lock, watchdog rules and survival regressions."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from execution_guard import CircuitBreaker, InstanceLock, atomic_write_json  # noqa: E402

ROOT = HERE.parents[1]


def _watchdog():
    spec = importlib.util.spec_from_file_location("bilshenz_watchdog", ROOT / "deploy" / "oracle" / "watchdog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_breaker_opens_and_recovers() -> None:
    b = CircuitBreaker(threshold=3, window_s=60, open_s=0.05)
    b.record_failure("orders", "x")
    b.record_failure("orders", "x")
    assert not b.blocked()
    b.record_failure("orders", "x")
    assert b.blocked() and b.state()["state"] == "open"
    time.sleep(0.3)
    assert not b.blocked()
    b.record_failure("orders", "x")
    assert b.blocked(), "one failure after the pause reopens it"
    print("OK breaker opens, closes, reopens")


def test_breaker_channels_are_separate() -> None:
    b = CircuitBreaker(threshold=2, window_s=60, open_s=10)
    b.record_failure("orders", "x")
    b.record_success("book")
    b.record_failure("orders", "x")
    assert b.blocked(), "healthy reads must not hide failing orders"
    print("OK breaker channels independent")


def test_instance_lock_blocks_second_process() -> None:
    path = os.path.join(tempfile.mkdtemp(), "bridge.lock")
    first = InstanceLock(path)
    assert first.acquire()
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from execution_guard import InstanceLock;"
        "sys.exit(0 if InstanceLock(sys.argv[2]).acquire() else 3)"
    )
    held = subprocess.run([sys.executable, "-c", code, str(HERE), path], check=False)
    assert held.returncode == 3, held.returncode
    first.release()
    free = subprocess.run([sys.executable, "-c", code, str(HERE), path], check=False)
    assert free.returncode == 0, free.returncode
    print("OK instance lock refuses a second worker and frees on exit")


def test_round_to_step_keeps_exact_multiples() -> None:
    from binance_connector import round_position_qty, round_to_step

    assert round_position_qty(19629.7875, 0.0001) == 19629.7875
    assert round_position_qty(15766.653 + 3863.1345, 0.0001) == 19629.7875
    assert round_position_qty(0.00009999999999, 0.0001) == 0.0001
    assert round_position_qty(233.154, 0.1) == 233.1, "real remainders still floor"
    assert round_position_qty(99.999, 1.0) == 99.0
    # Entry sizing is frozen, including its behaviour on near-exact values.
    assert round_to_step(4063.2779999999, 0.0001) == 4063.2779
    assert round_to_step(233.154, 0.1) == 233.1
    print("OK closes use the exact size, entry rounding unchanged")


def test_atomic_write_keeps_old_file_on_failure() -> None:
    path = os.path.join(tempfile.mkdtemp(), "state.json")
    atomic_write_json(path, {"v": 1})
    try:
        atomic_write_json(path, {"bad": object()})
    except TypeError:
        pass
    assert json.load(open(path, encoding="utf-8")) == {"v": 1}
    assert os.listdir(os.path.dirname(path)) == ["state.json"], "temp file left behind"
    print("OK atomic write keeps the previous file")


def test_watchdog_never_starts_a_stopped_bot() -> None:
    w = _watchdog()
    state: dict = {}
    for i in range(10):
        action, reason = w.decide(state, None, now=1000.0 + i * 30, service_active=False, workers=0)
        assert (action, reason) == ("hold", "service_stopped")
    print("OK watchdog leaves a stopped service stopped")


def test_watchdog_restarts_only_after_three_strikes() -> None:
    w = _watchdog()
    state: dict = {}
    hung = {"scanner": {"last_tick_age_s": 500.0}, "rest_cool_s": 0}
    got = [w.decide(state, hung, now=1000.0 + i * 30, service_active=True, workers=1)[0] for i in range(3)]
    assert got == ["hold", "hold", "restart"], got
    action, reason = w.decide(state, hung, now=1120.0, service_active=True, workers=1)
    assert (action, reason) == ("hold", "recovering_after_restart")
    print("OK watchdog needs three strikes, then gives recovery time")


def test_watchdog_healthy_clears_strikes() -> None:
    w = _watchdog()
    state: dict = {}
    hung = {"scanner": {"last_tick_age_s": 500.0}}
    fine = {"scanner": {"last_tick_age_s": 1.0}}
    w.decide(state, hung, now=1000.0, service_active=True, workers=1)
    w.decide(state, hung, now=1030.0, service_active=True, workers=1)
    assert w.decide(state, fine, now=1060.0, service_active=True, workers=1)[0] == "ok"
    assert state["fails"] == 0
    print("OK watchdog healthy check clears strikes")


def test_watchdog_holds_during_binance_pause() -> None:
    w = _watchdog()
    state: dict = {}
    paused = {"scanner": {"last_tick_age_s": 900.0}, "rest_cool_s": 300.0}
    for i in range(6):
        assert w.decide(state, paused, now=1000.0 + i * 30, service_active=True, workers=1)[0] == "hold"
    print("OK watchdog does not restart into a Binance pause")


def test_watchdog_restart_budget() -> None:
    w = _watchdog()
    state: dict = {}
    now = 10_000.0
    done = 0
    for _ in range(60):
        now += 100
        action, reason = w.decide(state, None, now=now, service_active=True, workers=1)
        done += action == "restart"
        if action == "alert":
            assert "restart_budget_spent" in reason
    assert done <= w.MAX_RESTARTS_PER_HOUR * 2, done
    print("OK watchdog restart budget stops a loop")


def test_watchdog_reports_duplicate_workers_without_acting() -> None:
    w = _watchdog()
    action, reason = w.decide({}, {"scanner": {}}, now=1.0, service_active=True, workers=2)
    assert action == "alert" and reason == "duplicate_workers:2"
    print("OK watchdog flags duplicate workers")


# Each of these failed on commit 3c9cae5.
SURVIVAL = (
    "combo.mainnet.short.reply_lost_lookup503",
    "combo.testnet.long2.reply_lost_lookup_timeout",
    "api.mainnet.short.late_landing_45s",
    "api.testnet.long1.late_landing_5s",
    "api.mainnet.long2.http429",
    "api.mainnet.close.timeout_processed",
    "api.testnet.short.http429",
    "reads.testnet.positionrisk_503_storm",
    "restart.blind_boot_flat_book",
    "restart.cooldown_survives_restart",
    "breaker.blocks_new_entry_then_resumes",
    "breaker.exits_run_and_nothing_is_liquidated",
    "breaker.recovery_hedges_keep_running",
    "breaker.trips_on_read_failures_and_resumes",
)


def test_survival_regressions() -> None:
    env = dict(os.environ, PYTHONHASHSEED="0")
    out = tempfile.mkdtemp()
    runner = HERE / "sim" / "run_matrix.py"
    sys.path.insert(0, str(HERE / "sim"))
    from run_matrix import verdict

    for name in SURVIVAL:
        subprocess.run(
            [sys.executable, str(runner), "--one", name, "--code", str(HERE), "--out", out],
            check=True, env=env, capture_output=True,
        )
        summary = json.load(open(os.path.join(out, name + ".json"), encoding="utf-8"))["summary"]
        bad = verdict(name, summary)
        assert not bad, (name, bad)
    print(f"OK {len(SURVIVAL)} survival regressions")


if __name__ == "__main__":
    for key, fn in list(globals().items()):
        if key.startswith("test_") and callable(fn):
            fn()
    print("ALL PROTECTIVE LAYER TESTS PASSED")
