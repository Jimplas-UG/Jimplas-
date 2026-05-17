import type { BrokerOrderIntent, BrokerWebhookResult } from './brokerTypes';
import { fetchMt5Connected, postMt5OrderFromIntent, type Mt5OrderResult } from './mt5PythonApi';
import { postBrokerOrderWebhook } from './webhookBroker';

export type ExecuteBrokerRoutesOpts = {
  intent: BrokerOrderIntent;
  webhookUrl?: string;
  webhookSecret?: string;
  useWebhook?: boolean;
  mt5BaseUrl?: string;
  useMt5?: boolean;
  mt5Volume?: number;
  symbol?: string;
};

export type ExecuteBrokerRoutesResult = {
  webhook?: BrokerWebhookResult;
  mt5?: Mt5OrderResult;
  summary: string;
  anyOk: boolean;
};

/**
 * Sends order intent to configured broker paths (webhook and/or Python MT5 API).
 */
export async function executeBrokerRoutes(opts: ExecuteBrokerRoutesOpts): Promise<ExecuteBrokerRoutesResult> {
  const parts: string[] = [];
  let anyOk = false;
  let webhook: BrokerWebhookResult | undefined;
  let mt5: Mt5OrderResult | undefined;

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
