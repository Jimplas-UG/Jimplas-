import type { BrokerOrderIntent, BrokerWebhookResult } from './brokerTypes';
import type { BinanceOrderResult } from './binanceTypes';
import { fetchBinanceConnected, postBinanceOrderFromIntent } from './binanceFuturesApi';
import { fetchMt5Connected, postMt5OrderFromIntent, type Mt5OrderResult } from './mt5PythonApi';
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
  mt5BaseUrl?: string;
  useMt5?: boolean;
  mt5Volume?: number;
  binanceBaseUrl?: string;
  useBinance?: boolean;
  binanceQuantity?: number;
  binanceVolume?: number;
  riskUsd?: number;
  symbol?: string;
};

export type ExecuteBrokerRoutesResult = {
  webhook?: BrokerWebhookResult;
  mt5?: Mt5OrderResult;
  binance?: BinanceOrderResult;
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

  if (opts.useMt5 && opts.mt5BaseUrl?.trim()) {
    const base = opts.mt5BaseUrl.trim();
    const connected = await fetchMt5Connected(base);
    if (!connected) {
      mt5 = { ok: false, status: 0, bodySnippet: 'MT5 not connected', connected: false };
      parts.push('MT5 skipped (not connected)');
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
      mt5 = await postMt5OrderFromIntent(opts.intent, {
        baseUrl: base,
        volume: opts.mt5Volume,
        symbol: opts.symbol,
      });
      const latencyMs = mt5.latencyMs ?? Date.now() - t0;
      if (side === 'BUY' || side === 'SELL') {
        if (mt5.ok && mt5.fillPrice != null) {
          logOrderFill({
            side,
            intendedEntry: mt5.intendedPrice ?? intended,
            actualFill: mt5.fillPrice,
            spreadAtExecutionPips: mt5.spreadPips,
            latencyMs,
            ticket: mt5.orderId,
            retcode: mt5.retcode,
            broker: 'mt5',
          });
        } else {
          logOrderRejected({
            side,
            rejectReason: mt5.bodySnippet,
            latencyMs,
            symbol: opts.symbol,
          });
        }
      }
      if (mt5.ok) {
        anyOk = true;
        parts.push(`MT5 OK ${mt5.status}`);
      } else {
        parts.push(`MT5: ${mt5.bodySnippet}`);
      }
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
        volume: opts.binanceVolume ?? opts.mt5Volume,
        symbol: opts.symbol,
        riskUsd: opts.riskUsd,
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
    return { webhook, mt5, binance, summary: 'No broker route enabled', anyOk: false };
  }

  return { webhook, mt5, binance, summary: parts.join(' · '), anyOk };
}
