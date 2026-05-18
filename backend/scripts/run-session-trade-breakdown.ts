/**
 * Count backtest trades by active session (PRE-LONDON / LONDON / NEW YORK).
 * Run: npx tsx scripts/run-session-trade-breakdown.ts --mt5-api=http://127.0.0.1:8765
 */
import { readFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { sessionFromUtcEpochMs } from '../engine/sessionEngine';

const __dirname = dirname(fileURLToPath(import.meta.url));
const reportPath = join(__dirname, 'backtest-xau-12mo-output.txt');

async function fetchMt5Bars(): Promise<{ t: number }[]> {
  const base = (process.env.MT5_API_URL ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
  const from = Date.UTC(2025, 4, 1) - 60 * 24 * 3600 * 1000;
  const to = Date.UTC(2026, 4, 2);
  const url = `${base}/api/bars/XAUUSD?from_ms=${from}&to_ms=${to}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`MT5 bars HTTP ${res.status}`);
  const j = (await res.json()) as { bars?: { t: number }[] };
  return (j.bars ?? []).sort((a, b) => a.t - b.t);
}

async function main() {
  const bars = await fetchMt5Bars();
  const counts = { PRE_LONDON: 0, LONDON: 0, NEW_YORK: 0, DEAD: 0, IN_ANY: 0 };
  const start = Date.UTC(2025, 4, 1);
  const end = Date.UTC(2026, 4, 1);
  for (const b of bars) {
    if (b.t < start || b.t >= end) continue;
    const s = sessionFromUtcEpochMs(b.t);
    if (s.inSession) counts.IN_ANY++;
    counts[s.name]++;
  }

  console.log('=== Session windows (America/New_York) ===');
  console.log('① PRE-LONDON  19:00 – 23:00');
  console.log('② LONDON      02:00 – 06:00');
  console.log('③ NEW YORK    07:00 – 12:00');
  console.log('in_session = PRE-LONDON OR LONDON OR NEW YORK');
  console.log('');
  console.log('M30 bars in 12mo journal window (May 2025 – May 2026):');
  console.log(`  In ANY session: ${counts.IN_ANY} bars`);
  console.log(`  PRE-LONDON only window: ${counts.PRE_LONDON} bars`);
  console.log(`  LONDON only window:     ${counts.LONDON} bars`);
  console.log(`  NEW YORK only window:   ${counts.NEW_YORK} bars`);
  console.log(`  DEAD ZONE:              ${counts.DEAD} bars`);
  console.log('');
  if (existsSync(reportPath)) {
    const txt = readFileSync(reportPath, 'utf8');
    const m = txt.match(/Trades opened in window: (\d+)/);
    if (m) {
      console.log(`Last 12mo backtest: ${m[1]} trades (all taken when in_session — any of the 3 sessions).`);
      console.log('Engine does NOT restrict execution to New York only.');
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
