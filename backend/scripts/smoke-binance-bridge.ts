#!/usr/bin/env npx tsx
/** Smoke test Binance bridge — no secrets printed. */
const BASE = (process.env.BINANCE_API_URL ?? 'http://127.0.0.1:8766').replace(/\/$/, '');
const SYMBOL = process.env.BINANCE_SYMBOL ?? 'XAUUSDT';
const TOKEN = process.env.BRIDGE_TOKEN?.trim() ?? '';

function headers(): Record<string, string> {
  const h: Record<string, string> = {};
  if (TOKEN) h['X-Bridge-Token'] = TOKEN;
  return h;
}

async function get(path: string) {
  const res = await fetch(`${BASE}${path}`, { headers: headers(), signal: AbortSignal.timeout(30_000) });
  const text = await res.text();
  if (!res.ok) throw new Error(`${path} HTTP ${res.status}: ${text.slice(0, 200)}`);
  return JSON.parse(text) as Record<string, unknown>;
}

async function main() {
  console.log(`[smoke] ${BASE}`);
  const health = await get('/health');
  if (!health.ok) throw new Error('health not ok');
  console.log(`health ok mode=${health.mode}`);

  const tick = await get(`/api/tick/${SYMBOL}`);
  console.log(`tick bid=${tick.bid} ask=${tick.ask}`);

  const bars = await get(`/api/bars/${SYMBOL}?count=20`) as { bars?: unknown[] };
  if (!bars.bars?.length) throw new Error('no bars');
  console.log(`bars ${bars.bars.length} M30`);

  const status = await get('/api/status');
  console.log(`status connected=${status.connected}`);
  console.log('SMOKE_OK');
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : String(e));
  process.exit(1);
});
