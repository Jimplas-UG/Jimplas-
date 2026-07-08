/**
 * WebSocket proxy: desk-api /v1/binance/ws/* → Python bridge ws://127.0.0.1:8766/ws/*
 */
import type { IncomingMessage, Server } from 'node:http';
import type { Socket } from 'node:net';
import { WebSocketServer, WebSocket } from 'ws';
import { isBinanceProxyPath } from './binanceProxy';

const BINANCE_HTTP = (process.env.BINANCE_API_URL || 'http://127.0.0.1:8766').replace(/\/$/, '');
const BINANCE_WS = BINANCE_HTTP.replace(/^http/i, 'ws');
const BRIDGE_TOKEN = process.env.BRIDGE_TOKEN?.trim() ?? '';
const DESK_KEY = process.env.DESK_API_KEY?.trim() ?? '';

function wsAuthOk(req: IncomingMessage, url: URL): boolean {
  if (!DESK_KEY) return true;
  const auth = req.headers.authorization ?? '';
  if (auth === `Bearer ${DESK_KEY}`) return true;
  const q = url.searchParams.get('token')?.trim();
  return q === DESK_KEY;
}

function upstreamWsUrl(pathname: string, search: string): string {
  const rest = pathname.replace(/^\/v1\/binance/, '') || '/';
  // Client auth is DESK_API_KEY; Python bridge expects BRIDGE_TOKEN.
  // Always strip client token and inject bridge token so WS upgrades never 403.
  const incoming = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  incoming.delete('token');
  if (BRIDGE_TOKEN) incoming.set('token', BRIDGE_TOKEN);
  const qs = incoming.toString();
  return `${BINANCE_WS}${rest}${qs ? `?${qs}` : ''}`;
}

export function attachBinanceWebSocketProxy(
  server: Server,
  onUnauthorized: (socket: Socket) => void,
): void {
  const wss = new WebSocketServer({ noServer: true });

  server.on('upgrade', (req, socket, head) => {
    const host = req.headers.host ?? '127.0.0.1';
    const url = new URL(req.url ?? '/', `http://${host}`);
    if (!isBinanceProxyPath(url.pathname) || !url.pathname.includes('/ws/')) {
      return;
    }
    if (!wsAuthOk(req, url)) {
      onUnauthorized(socket as Socket);
      return;
    }

    wss.handleUpgrade(req, socket, head, (client) => {
      const target = upstreamWsUrl(url.pathname, url.search);
      const upstream = new WebSocket(target);

      const closeBoth = (code?: number, reason?: Buffer) => {
        try {
          if (client.readyState === WebSocket.OPEN) client.close(code, reason);
        } catch { /* ignore */ }
        try {
          if (upstream.readyState === WebSocket.OPEN) upstream.close(code, reason);
        } catch { /* ignore */ }
      };

      upstream.on('open', () => {
        client.on('message', (data, isBinary) => {
          if (upstream.readyState === WebSocket.OPEN) upstream.send(data, { binary: isBinary });
        });
        upstream.on('message', (data, isBinary) => {
          if (client.readyState === WebSocket.OPEN) client.send(data, { binary: isBinary });
        });
      });

      upstream.on('error', () => closeBoth(1011));
      client.on('error', () => closeBoth(1011));
      upstream.on('close', (code, reason) => closeBoth(code, reason));
      client.on('close', (code, reason) => closeBoth(code, reason));
    });
  });
}
