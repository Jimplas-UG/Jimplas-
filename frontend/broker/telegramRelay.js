function trimSnippet(s, max = 240) {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max)}…`;
}

export function formatTelegramEligibleSignal(intent, lotsEstimated) {
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

export async function postTelegramSignalRelay(intent, opts) {
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

  const payload = {
    event: 'bilshenz_exec_ready',
    version: 1,
    text: formatTelegramEligibleSignal(intent, opts.lotsEstimated ?? null),
    intent,
    lotsEstimated: opts.lotsEstimated ?? null,
  };

  const headers = {
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
