import type { IncomingMessage, ServerResponse } from 'node:http';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { ForwardDemoEvent } from '../validation/types';
import { appendForwardDemoEvent, loadForwardDemoEvents } from '../validation/forwardDemoStore';
import {
  isStrategyFreezeEnforced,
  mergeFrozenDeskCfg,
  productionFrozenConfig,
  verifyFrozenStrategy,
} from '../strategy/frozenProduction';

const BACKEND_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

export function handleValidationRoute(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL
): boolean {
  if (url.pathname === '/v1/validation/freeze-status' && req.method === 'GET') {
    const check = verifyFrozenStrategy(BACKEND_ROOT, productionFrozenConfig());
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        enforced: isStrategyFreezeEnforced(),
        ok: check.ok,
        errors: check.ok ? [] : check.errors,
      })
    );
    return true;
  }

  if (url.pathname === '/v1/validation/event' && req.method === 'POST') {
    const chunks: Buffer[] = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') as Partial<ForwardDemoEvent>;
        const now = Date.now();
        const row = appendForwardDemoEvent({
          ts: body.ts ?? new Date(now).toISOString(),
          tsMs: body.tsMs ?? now,
          type: body.type!,
          symbol: body.symbol ?? 'XAUUSD',
          ...body,
        });
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, id: row.id }));
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: msg }));
      }
    });
    return true;
  }

  if (url.pathname === '/v1/validation/events' && req.method === 'GET') {
    const since = url.searchParams.get('since_ms');
    const events = loadForwardDemoEvents(since ? parseInt(since, 10) : 0);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ count: events.length, events }));
    return true;
  }

  return false;
}
