import type { BrokerOrderIntent, BrokerWebhookResult } from './brokerTypes';
import type { BinanceOrderResult } from './binanceTypes';
import { fetchBinanceConnected, postBinanceOrderFromIntent } from './binanceFuturesApi';
import { postBrokerOrderWebhook } from './webhookBroker';
import {
  logOrderFill,
  logOrderIntent,
  logOrderRejected,
} from '../validation/logForwardEvent';

export type ExecuteBrokerRoutesOpts = {
  intent: BrokerOrderIntent;
  webhookUrl?: string;
  webhookSecret?: string;
  useWebhook?: boolean;
  binanceBaseUrl?: string;
  useBinance?: boolean;
  binanceQuantity?: number;
  binanceVolume?: number;
  riskUsd?: number;
  symbol?: string;
};

export type ExecuteBrokerRoutesResult = {
  webhook?: BrokerWebhookResult;
  binance?: BinanceOrderResult;
  summary: string;
  anyOk: boolean;
};

/** Sends order intent to configured broker paths (webhook and/or Binance Futures API). */
export async function executeBrokerRoutes(opts: ExecuteBrokerRoutesOpts): Promise<ExecuteBrokerRoutesResult> {
  const parts: string[] = [];
  let anyOk = false;
  let webhook: BrokerWebhookResult | undefined;
  let binance: BinanceOrderResult | undefined;

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
        logOrderIntent({
          side,
          intendedEntry: intended,
          symbol: opts.symbol ?? opts.intent.symbol,
        });
      }
      const t0 = Date.now();
      binance = await postBinanceOrderFromIntent(opts.intent, {
        baseUrl: base,
        quantity: opts.binanceQuantity,
        volume: opts.binanceVolume,
        symbol: opts.symbol,
        riskUsd: opts.riskUsd,
        skipConnectedCheck: true,
        referencePrice: intended > 0 ? intended : undefined,
      });
      const latencyMs = binance.latencyMs ?? Date.now() - t0;
      if (side === 'BUY' || side === 'SELL') {
        if (binance.ok && binance.fillPrice != null) {
          logOrderFill({
            side,
            intendedEntry: binance.intendedPrice ?? intended,
            actualFill: binance.fillPrice,
            spreadAtExecutionPips: binance.spreadPips,
            latencyMs,
            ticket: binance.orderId,
            broker: binance.broker ?? 'binance',
          });
        } else {
          logOrderRejected({
            side,
            rejectReason: binance.bodySnippet,
            latencyMs,
            symbol: opts.symbol,
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
