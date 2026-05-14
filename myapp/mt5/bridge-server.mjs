/**
 * Minimal queue between the Bilshenz app (webhook POST) and MT5 (EA GET poll).
 *
 * Run on the same PC as MT5 (or on a VPS; EA must reach the URL — use LAN IP or tunnel).
 *
 *   set MT5_BRIDGE_SECRET=your-long-secret
 *   node mt5/bridge-server.mjs
 *
 * App Profile: set webhook URL to e.g. http://192.168.1.10:8788/webhook
 * Optional same secret in EXPO_PUBLIC_BROKER_WEBHOOK_SECRET (Bearer) as the app already sends.
 *
 * EA: set QueueUrl to http://127.0.0.1:8788/poll?key=YOUR_LONG_SECRET
 *
 * Poll response (plain text, one line) when a job is waiting:
 *   TRADE BUY XAUUSD 2650.12 2639.50 2660.00 <intentAtIso>
 * When empty queue:
 *   NONE
 */
import http from 'http';

const PORT = Number(process.env.MT5_BRIDGE_PORT || 8788);
const SECRET = (process.env.MT5_BRIDGE_SECRET || '').trim();

/** @type {{ line: string, raw: object }[]} */
const queue = [];
const MAX = 50;

function send(res, code, body, type = 'text/plain; charset=utf-8') {
  res.writeHead(code, {
    'Content-Type': type,
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

function authBearer(req) {
  if (!SECRET) return true;
  const h = req.headers.authorization || '';
  const m = /^Bearer\s+(.+)$/i.exec(h);
  return m && m[1].trim() === SECRET;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);

  if (req.method === 'GET' && url.pathname === '/health') {
    return send(res, 200, 'ok');
  }

  if (req.method === 'GET' && url.pathname === '/poll') {
    if (SECRET && url.searchParams.get('key') !== SECRET) {
      return send(res, 403, 'FORBIDDEN');
    }
    const job = queue.shift();
    if (!job) return send(res, 200, 'NONE');
    return send(res, 200, job.line);
  }

  if (req.method === 'POST' && url.pathname === '/webhook') {
    if (!authBearer(req)) {
      return send(res, 403, 'FORBIDDEN');
    }
    let body = '';
    req.on('data', (c) => {
      body += c;
      if (body.length > 1e6) req.destroy();
    });
    req.on('end', () => {
      try {
        const j = JSON.parse(body || '{}');
        const side = j.side === 'SELL' ? 'SELL' : j.side === 'BUY' ? 'BUY' : '';
        if (!side) return send(res, 400, 'BAD_JSON side');
        const sym = typeof j.symbol === 'string' ? j.symbol : 'XAUUSD';
        const entry = Number(j.entry);
        const sl = Number(j.sl);
        const tp = Number(j.tp1);
        const id = typeof j.intentAtIso === 'string' ? j.intentAtIso : `${Date.now()}`;
        if (!Number.isFinite(entry) || !Number.isFinite(sl) || !Number.isFinite(tp)) {
          return send(res, 400, 'BAD_JSON prices');
        }
        const brokerSymbol = process.env.MT5_SYMBOL || sym;
        const line = `TRADE ${side} ${brokerSymbol} ${entry} ${sl} ${tp} ${encodeURIComponent(id)}`;
        if (queue.length >= MAX) queue.shift();
        queue.push({ line, raw: j });
        return send(res, 200, 'QUEUED');
      } catch {
        return send(res, 400, 'BAD_JSON');
      }
    });
    return;
  }

  send(res, 404, 'NOT_FOUND');
});

server.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`MT5 bridge listening on http://0.0.0.0:${PORT}  (secret ${SECRET ? 'ON' : 'OFF'})`);
});
