import { fetchBinanceConnected, postBinanceOrderFromIntent } from './binanceFuturesApi';
import { postBrokerOrderWebhook } from './webhookBroker';
import { logForwardDemoEvent } from '../utils/forwardDemoLog';

export async function executeBrokerRoutes(opts) {
  const parts = [];
  let anyOk = false;
  let webhook;
  let binance;

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

  if (opts.useBinance && opts.binanceBaseUrl?.trim()) {
    const base = opts.binanceBaseUrl.trim();
    const connected = await fetchBinanceConnected(base);
    if (!connected) {
      binance = { ok: false, status: 0, bodySnippet: 'Binance not connected', connected: false };
      parts.push('Binance skipped (not connected)');
    } else {
      const side = opts.intent.side;
      const intended = opts.intent.entry ?? 0;
      if (side === 'BUY' || side === 'SELL') {
        await logForwardDemoEvent({
          type: 'ORDER_INTENT',
          side,
          intendedEntry: intended,
          symbol: opts.symbol || opts.intent.symbol,
        });
      }
      const t0 = Date.now();
      binance = await postBinanceOrderFromIntent(opts.intent, {
        baseUrl: base,
        quantity: opts.binanceQuantity ?? opts.quantity,
        volume: opts.binanceVolume ?? opts.volume,
        symbol: opts.symbol,
      });
      const latencyMs = binance.latencyMs ?? Date.now() - t0;
      if (side === 'BUY' || side === 'SELL') {
        if (binance.ok && binance.fillPrice != null) {
          await logForwardDemoEvent({
            type: 'ORDER_FILL',
            side,
            intendedEntry: binance.intendedPrice ?? intended,
            actualFill: binance.fillPrice,
            slippagePips: binance.slippagePips,
            spreadAtExecutionPips: binance.spreadPips,
            latencyMs,
            ticket: binance.orderId,
            broker: binance.broker || 'binance',
          });
        } else {
          await logForwardDemoEvent({
            type: 'ORDER_REJECTED',
            side,
            rejected: true,
            rejectReason: binance.bodySnippet,
            latencyMs,
          });
        }
      }
      if (binance.ok) {
        anyOk = true;
        parts.push(`Binance OK ${binance.status}`);
      } else {
        parts.push(`Binance: ${binance.bodySnippet}`);
      }
    }
  }

  if (!parts.length) {
    return { webhook, binance, summary: 'No broker route enabled', anyOk: false };
  }

  return { webhook, binance, summary: parts.join(' · '), anyOk };
}
