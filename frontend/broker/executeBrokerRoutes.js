import { fetchMt5Connected, postMt5OrderFromIntent } from './mt5PythonApi';
import { postBrokerOrderWebhook } from './webhookBroker';

export async function executeBrokerRoutes(opts) {
  const parts = [];
  let anyOk = false;
  let webhook;
  let mt5;

  if (opts.useWebhook && opts.webhookUrl?.trim()) {
    webhook = await postBrokerOrderWebhook(opts.intent, {
      url: opts.webhookUrl.trim(),
      secret: opts.webhookSecret,
    });
    if (webhook.ok) {
      anyOk = true;
      parts.push(`Webhook OK ${webhook.status}`);
    } else {
      parts.push(`Webhook ${webhook.status}: ${webhook.bodySnippet}`);
    }
  }

  if (opts.useMt5 && opts.mt5BaseUrl?.trim()) {
    const base = opts.mt5BaseUrl.trim();
    const connected = await fetchMt5Connected(base);
    if (!connected) {
      mt5 = { ok: false, status: 0, bodySnippet: 'MT5 not connected', connected: false };
      parts.push('MT5 skipped (not connected)');
    } else {
      mt5 = await postMt5OrderFromIntent(opts.intent, {
        baseUrl: base,
        volume: opts.mt5Volume,
        symbol: opts.symbol,
      });
      if (mt5.ok) {
        anyOk = true;
        parts.push(`MT5 OK ${mt5.status}`);
      } else {
        parts.push(`MT5: ${mt5.bodySnippet}`);
      }
    }
  }

  if (!parts.length) {
    return { webhook, mt5, summary: 'No broker route enabled', anyOk: false };
  }

  return { webhook, mt5, summary: parts.join(' · '), anyOk };
}
