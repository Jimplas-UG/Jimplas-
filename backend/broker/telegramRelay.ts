import type { BrokerOrderIntent } from './brokerTypes';

export type TelegramSignalRelayPayload = {
  event: 'bilshenz_exec_ready';
  version: 1;
  /** Plain-text message for Telegram (you can paste into sendMessage text). */
  text: string;
  intent: BrokerOrderIntent;
  /** Contracts the app intends to send to Binance (optional, informational). */
  lotsEstimated?: number | null;
};

function trimSnippet(s: string, max = 240): string {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

/** Human-readable Telegram message — plain text only. */
export function formatTelegramEligibleSignal(intent: BrokerOrderIntent, lotsEstimated?: number | null): string {
  const e = intent.entry != null ? intent.entry.toFixed(2) : '—';
  const sl = intent.sl != null ? intent.sl.toFixed(2) : '—';
  const tp = intent.tp1 != null ? intent.tp1.toFixed(2) : '—';
  const setup = intent.setup ?? 'NONE';
  const trig = intent.trigger ?? 'manual';
  const lots =
    typeof lotsEstimated === 'number' && Number.isFinite(lotsEstimated)
      ? ` · est lots ${lotsEstimated.toFixed(2)}`
      : '';
  const bar = intent.barTimeIso ?? '—';
  return [
    '🟡 Bilshenz — signal ready · EXEC gated OK',
    `${intent.side} ${intent.symbol} · ${setup} · ${trig}`,
    `Entry≈ ${e}  SL ${sl}  TP ${tp}${lots}`,
    `Bar: ${bar}`,
  ].join('\n');
}

/**
 * POST eligible-signal bundle to YOUR HTTPS relay (Cloudflare Worker, VPS, etc.).
 * The relay should call Telegram sendMessage with your BOT_TOKEN kept server-side only.
 *
 * Env fallback for dev builds only:
 * EXPO_PUBLIC_TELEGRAM_NOTIFY_URL · EXPO_PUBLIC_TELEGRAM_NOTIFY_SECRET
 */
export async function postTelegramSignalRelay(
  intent: BrokerOrderIntent,
  opts: {
    relayUrl?: string;
    relaySecret?: string;
    lotsEstimated?: number | null;
  }
): Promise<{ ok: boolean; status: number; snippet: string }> {
  const url =
    opts.relayUrl?.trim() ||
    (typeof process !== 'undefined' ? process.env?.EXPO_PUBLIC_TELEGRAM_NOTIFY_URL : '') ||
    '';
  if (!url.trim()) {
    return { ok: false, status: 0, snippet: 'No Telegram relay URL' };
  }
  const secret =
    opts.relaySecret?.trim() ||
    (typeof process !== 'undefined' ? process.env?.EXPO_PUBLIC_TELEGRAM_NOTIFY_SECRET : '') ||
    '';

  const payload: TelegramSignalRelayPayload = {
    event: 'bilshenz_exec_ready',
    version: 1,
    text: formatTelegramEligibleSignal(intent, opts.lotsEstimated ?? null),
    intent,
    lotsEstimated: opts.lotsEstimated ?? null,
  };

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  };
  if (secret) headers.Authorization = `Bearer ${secret}`;

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });
    const tb = await res.text();
    return {
      ok: res.ok,
      status: res.status,
      snippet: trimSnippet(tb || (res.ok ? 'OK' : 'Empty')),
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, status: 0, snippet: trimSnippet(msg) };
  }
}
