/**
 * Proxy MT5 Python bridge through desk-api (:8791) so mobile carriers
 * that block port 8765 still reach MT5 via the same URL as strategy API.
 */
import http from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';

const MT5_BASE = (process.env.MT5_API_URL || 'http://127.0.0.1:8765').replace(/\/$/, '');
const PREFIX = '/v1/mt5';

export function isMt5ProxyPath(pathname: string): boolean {
  return pathname === PREFIX || pathname.startsWith(`${PREFIX}/`);
}

function mt5TargetUrl(pathname: string, search: string): string {
  const rest = pathname.slice(PREFIX.length) || '/';
  return `${MT5_BASE}${rest}${search}`;
}

function copyResponseHeaders(from: Response, res: ServerResponse) {
  const ct = from.headers.get('content-type');
  if (ct) res.setHeader('Content-Type', ct);
}

export async function handleMt5Proxy(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<boolean> {
  if (!isMt5ProxyPath(url.pathname)) return false;

  const target = mt5TargetUrl(url.pathname, url.search);
  const method = req.method ?? 'GET';
  const headers: Record<string, string> = {};
  if (req.headers['content-type']) headers['Content-Type'] = String(req.headers['content-type']);

  let body: Buffer | undefined;
  if (method !== 'GET' && method !== 'HEAD') {
    body = await new Promise<Buffer>((resolve, reject) => {
      const chunks: Buffer[] = [];
      req.on('data', (c) => chunks.push(c));
      req.on('end', () => resolve(Buffer.concat(chunks)));
      req.on('error', reject);
    });
  }

  try {
    const timeoutMs = target.includes('/health') ? 8_000 : 45_000;
    const upstream = await fetch(target, {
      method,
      headers,
      body: body?.length ? body : undefined,
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await upstream.text();
    copyResponseHeaders(upstream, res);
    res.writeHead(upstream.status, { 'Content-Type': upstream.headers.get('content-type') || 'application/json' });
    res.end(text);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        detail: `MT5 bridge unreachable on VPS (${msg}). Ensure Bilshenz-MT5-API task is running.`,
      }),
    );
  }
  return true;
}
