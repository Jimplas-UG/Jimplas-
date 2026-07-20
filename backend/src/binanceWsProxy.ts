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
const UPSTREAM_RETRY_MS = [0, 50, 150, 400];

function wsAuthOk(req: IncomingMessage, url: URL): boolean {
  if (!DESK_KEY) return true;
  const auth = req.headers.authorization ?? '';
  if (auth === `Bearer ${DESK_KEY}`) return true;
  const q = url.searchParams.get('token')?.trim();
  return q === DESK_KEY;
}

function upstreamWsUrl(pathname: string, search: string): string {
  const rest = pathname.replace(/^\/v1\/binance/, '') || '/';
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
      let upstream: WebSocket | null = null;
      let closed = false;
      let retryTimer: ReturnType<typeof setTimeout> | null = null;
      let connectAttempt = 0;
      const pending: Array<{ data: WebSocket.RawData; isBinary: boolean }> = [];

      const closeBoth = (code?: number, reason?: Buffer) => {
        if (closed) return;
        closed = true;
        if (retryTimer) {
          clearTimeout(retryTimer);
          retryTimer = null;
        }
        try {
          if (client.readyState === WebSocket.OPEN || client.readyState === WebSocket.CONNECTING) {
            client.close(code, reason);
          }
        } catch { /* ignore */ }
        try {
          upstream?.removeAllListeners();
          if (upstream?.readyState === WebSocket.OPEN || upstream?.readyState === WebSocket.CONNECTING) {
            upstream.close(code, reason);
          }
        } catch { /* ignore */ }
        upstream = null;
      };

      const flushPending = () => {
        while (pending.length && upstream?.readyState === WebSocket.OPEN) {
          const item = pending.shift();
          if (item) upstream.send(item.data, { binary: item.isBinary });
        }
      };

      const scheduleConnect = () => {
        if (closed || client.readyState !== WebSocket.OPEN) return;
        if (connectAttempt >= UPSTREAM_RETRY_MS.length) {
          closeBoth(1011);
          return;
        }
        const delay = UPSTREAM_RETRY_MS[connectAttempt] ?? 400;
        connectAttempt += 1;
        retryTimer = setTimeout(connectUpstream, delay);
      };

      const connectUpstream = () => {
        retryTimer = null;
        if (closed || client.readyState !== WebSocket.OPEN) return;
        try {
          upstream?.removeAllListeners();
          upstream?.close();
        } catch { /* ignore */ }

        const ws = new WebSocket(target);
        upstream = ws;

        ws.on('open', () => {
          connectAttempt = 0;
          ws.on('message', (data, isBinary) => {
            if (client.readyState === WebSocket.OPEN) client.send(data, { binary: isBinary });
          });
          flushPending();
        });

        ws.on('close', () => {
          upstream = null;
          if (!closed && client.readyState === WebSocket.OPEN) scheduleConnect();
        });

        ws.on('error', () => {
          /* close handler schedules reconnect */
        });
      };

      client.on('message', (data, isBinary) => {
        if (upstream?.readyState === WebSocket.OPEN) {
          upstream.send(data, { binary: isBinary });
          return;
        }
        pending.push({ data, isBinary });
        if (pending.length > 64) pending.shift();
      });

      client.on('error', () => closeBoth(1011));
      client.on('close', (code, reason) => closeBoth(code, reason));

      connectUpstream();
    });
  });
}
