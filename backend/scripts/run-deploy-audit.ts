#!/usr/bin/env npx tsx
/**
 * Pre-deploy audit — infrastructure smoke (no secrets printed).
 * Usage: npm run audit:deploy
 */
import { execSync } from 'node:child_process';

const BINANCE = (process.env.BINANCE_API_URL ?? 'http://127.0.0.1:8766').replace(/\/$/, '');
const DESK = (process.env.DESK_API_URL ?? `http://127.0.0.1:${process.env.DESK_API_PORT ?? '8791'}`).replace(
  /\/$/,
  '',
);
const DESK_KEY = process.env.DESK_API_KEY?.trim() ?? '';
const BRIDGE_TOKEN = process.env.BRIDGE_TOKEN?.trim() ?? '';
const SYMBOL = process.env.BINANCE_SYMBOL ?? 'XAUUSDT';

type Check = { name: string; ok: boolean; detail: string };

const checks: Check[] = [];

function run(name: string, fn: () => void) {
  try {
    fn();
    checks.push({ name, ok: true, detail: 'ok' });
  } catch (e) {
    checks.push({ name, ok: false, detail: e instanceof Error ? e.message : String(e) });
  }
}

function bridgeHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  if (BRIDGE_TOKEN) h['X-Bridge-Token'] = BRIDGE_TOKEN;
  return h;
}

function deskHeaders(): Record<string, string> {
  const h: Record<string, string> = { ...bridgeHeaders() };
  if (DESK_KEY) h.Authorization = `Bearer ${DESK_KEY}`;
  return h;
}

async function getJson(url: string, headers: Record<string, string> = {}, timeoutMs = 30_000) {
  const res = await fetch(url, { headers, signal: AbortSignal.timeout(timeoutMs) });
  const text = await res.text();
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0, 240)}`);
  return JSON.parse(text) as Record<string, unknown>;
}

async function main() {
  console.log('BILSHENZ — DEPLOY READINESS AUDIT');
  console.log(`binance=${BINANCE} desk=${DESK} symbol=${SYMBOL}`);
  console.log('');

  run('tsc --noEmit', () => {
    execSync('npx tsc --noEmit', { stdio: 'pipe', cwd: process.cwd() });
  });

  run('smoke:auth', () => {
    execSync('npx tsx scripts/smoke-auth.ts', { stdio: 'pipe', cwd: process.cwd() });
  });

  try {
    const health = await getJson(`${BINANCE}/health`, bridgeHeaders(), 10_000);
    checks.push({
      name: 'binance /health',
      ok: !!health.ok,
      detail: health.ok ? `mode=${String(health.mode ?? '?')}` : 'not ok',
    });
  } catch (e) {
    checks.push({ name: 'binance /health', ok: false, detail: e instanceof Error ? e.message : String(e) });
  }

  try {
    const bars = (await getJson(
      `${BINANCE}/api/bars/${SYMBOL}?count=220`,
      bridgeHeaders(),
      45_000,
    )) as { bars?: unknown[] };
    const n = bars.bars?.length ?? 0;
    checks.push({
      name: 'binance M30 bars (220)',
      ok: n >= 50,
      detail: n >= 50 ? `${n} bars` : `only ${n} bars`,
    });
  } catch (e) {
    checks.push({
      name: 'binance M30 bars (220)',
      ok: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }

  try {
    const deskHealth = await getJson(`${DESK}/health`, {}, 8_000);
    checks.push({
      name: 'desk-api /health',
      ok: !!deskHealth.ok,
      detail: String(deskHealth.service ?? 'desk-api'),
    });
  } catch (e) {
    checks.push({ name: 'desk-api /health', ok: false, detail: e instanceof Error ? e.message : String(e) });
  }

  try {
    const proxyHealth = await getJson(`${DESK}/v1/binance/health`, deskHeaders(), 10_000);
    checks.push({
      name: 'desk binance proxy /health',
      ok: !!proxyHealth.ok,
      detail: String(proxyHealth.mode ?? proxyHealth.service ?? 'ok'),
    });
  } catch (e) {
    checks.push({
      name: 'desk binance proxy /health',
      ok: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }

  try {
    const proxyBars = (await getJson(
      `${DESK}/v1/binance/api/bars/${SYMBOL}?count=220`,
      deskHeaders(),
      45_000,
    )) as { bars?: unknown[] };
    const n = proxyBars.bars?.length ?? 0;
    checks.push({
      name: 'desk binance proxy M30 bars',
      ok: n >= 50,
      detail: n >= 50 ? `${n} bars` : `only ${n} bars`,
    });
  } catch (e) {
    checks.push({
      name: 'desk binance proxy M30 bars',
      ok: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }

  const failed = checks.filter((c) => !c.ok);
  for (const c of checks) {
    console.log(`${c.ok ? 'PASS' : 'FAIL'}  ${c.name} — ${c.detail}`);
  }
  console.log('');
  console.log(`Result: ${checks.length - failed.length}/${checks.length} passed`);

  if (failed.length) {
    console.error('\nDeploy blockers:');
    for (const f of failed) console.error(`  - ${f.name}: ${f.detail}`);
    process.exit(1);
  }
  console.log('DEPLOY_AUDIT_OK');
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : String(e));
  process.exit(1);
});
