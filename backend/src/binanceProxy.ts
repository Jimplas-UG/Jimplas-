/**
 * Proxy Binance Python bridge through desk-api (:8791) so mobile carriers
 * reach Binance via the same URL as strategy API.
 */
import type { IncomingMessage, ServerResponse } from 'node:http';

const BINANCE_BASE = (process.env.BINANCE_API_URL || 'http://127.0.0.1:8766').replace(/\/$/, '');
const PREFIX = '/v1/binance';

export function isBinanceProxyPath(pathname: string): boolean {
  return pathname === PREFIX || pathname.startsWith(`${PREFIX}/`);
}

function binanceTargetUrl(pathname: string, search: string): string {
  const rest = pathname.slice(PREFIX.length) || '/';
  return `${BINANCE_BASE}${rest}${search}`;
}

function copyResponseHeaders(from: Response, res: ServerResponse) {
  const ct = from.headers.get('content-type');
  if (ct) res.setHeader('Content-Type', ct);
}

export async function handleBinanceProxy(
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
): Promise<boolean> {
  if (!isBinanceProxyPath(url.pathname)) return false;

  const target = binanceTargetUrl(url.pathname, url.search);
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
      body: body?.length ? new Uint8Array(body) : undefined,
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
        detail: `Binance bridge unreachable (${msg}). Ensure Bilshenz-Binance-API is running on ${BINANCE_BASE}.`,
      }),
    );
  }
  return true;
}
