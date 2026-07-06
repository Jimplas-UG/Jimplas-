/**
 * Tick momentum scanner — REST snapshot + WebSocket live updates.
 */
import { getBridgeToken } from '../lib/envConfig';
import { binanceFetch } from './binanceFuturesApi';

function wsBase(httpBase) {
  return String(httpBase || '')
    .replace(/\/$/, '')
    .replace(/^http:\/\//i, 'ws://')
    .replace(/^https:\/\//i, 'wss://');
}

export function scannerWsUrl(baseUrl) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  const path = `${wsBase(b)}/ws/scanner`;
  const token = getBridgeToken();
  if (!token) return path;
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}token=${encodeURIComponent(token)}`;
}

function normalizeSnapshot(data) {
  return {
    ok: true,
    rows: data.rows || [],
    scanner: data.scanner || null,
    signals: data.signals || [],
    blocks: data.blocks || [],
    ts: data.ts || Date.now(),
  };
}

export async function fetchScannerSnapshot(baseUrl, timeoutMs = 12000) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  if (!b) return { ok: false, rows: [], signals: [], blocks: [], error: 'no_base_url' };
  const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const t = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
  try {
    const res = await fetch(`${b}/api/scanner/snapshot`, { signal: ctrl?.signal });
    if (!res.ok) return { ok: false, rows: [], signals: [], blocks: [], error: `HTTP ${res.status}` };
    const data = await res.json();
    return normalizeSnapshot(data);
  } catch (e) {
    return { ok: false, rows: [], signals: [], blocks: [], error: e instanceof Error ? e.message : String(e) };
  } finally {
    if (t) clearTimeout(t);
  }
}

export async function postScannerClose(baseUrl, symbol) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  if (!b || !symbol) return { ok: false, error: 'missing_params' };
  try {
    const res = await binanceFetch(
      b,
      '/api/scanner/close',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) },
      20000,
    );
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok && data.ok !== false, ...data, status: res.status };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function postScannerExecEnable(baseUrl, enabled = true) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  if (!b) return { ok: false, error: 'no_base_url' };
  try {
    const res = await binanceFetch(
      b,
      '/api/scanner/exec',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !!enabled }) },
      8000,
    );
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, exec_enabled: data.exec_enabled, status: res.status };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/** Turn scanner auto-exec ON after Binance link — retries until bridge is ready. */
export async function enableScannerAutoExec(baseUrl, { retries = 4, delayMs = 1200 } = {}) {
  let last = { ok: false, error: 'no_attempt' };
  for (let i = 0; i <= retries; i += 1) {
    last = await postScannerExecEnable(baseUrl, true);
    if (last.ok && last.exec_enabled !== false) return last;
    if (i < retries) {
      await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
    }
  }
  return last;
}

export async function postScannerRiskConfig(baseUrl, config) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  if (!b) return { ok: false, error: 'no_base_url' };
  const body = {
    partition_usd: Number(config.partitionUsd) || 100,
    short_pct: Number(config.shortPartitionPct) || 50,
    long1_pct: Number(config.long1PartitionPct) || 40,
    long2_pct: Number(config.long2PartitionPct) || 40,
  };
  try {
    const res = await binanceFetch(
      b,
      '/api/scanner/risk',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      8000,
    );
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok && data.ok !== false, ...data, status: res.status };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export function subscribeScannerStream(baseUrl, onSnapshot, { onError, onOpen } = {}) {
  if (!baseUrl?.trim() || typeof WebSocket === 'undefined') {
    return () => {};
  }

  let ws = null;
  let closed = false;
  let reconnectTimer = null;
  let backoffMs = 1500;

  const connect = () => {
    if (closed) return;
    try {
      ws = new WebSocket(scannerWsUrl(baseUrl));
    } catch (e) {
      onError?.(e instanceof Error ? e.message : String(e));
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      backoffMs = 1500;
      onOpen?.();
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(String(ev.data ?? ''));
        if (msg?.type === 'snapshot' && Array.isArray(msg.rows)) {
          onSnapshot(normalizeSnapshot(msg));
        }
      } catch {
        /* ignore */
      }
    };

    ws.onerror = () => onError?.('scanner WebSocket error');
    ws.onclose = () => {
      ws = null;
      if (!closed) scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (closed || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      backoffMs = Math.min(30000, Math.round(backoffMs * 1.6));
      connect();
    }, backoffMs);
  };

  connect();

  return () => {
    closed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
    ws = null;
  };
}
