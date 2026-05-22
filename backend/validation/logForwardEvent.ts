import { appendForwardDemoEvent } from './forwardDemoStore';
import type { ForwardDemoEvent, ForwardDemoEventType } from './types';

export function logForwardEvent(
  type: ForwardDemoEventType,
  fields: Partial<ForwardDemoEvent> & { symbol?: string }
): ForwardDemoEvent {
  const now = Date.now();
  return appendForwardDemoEvent({
    ts: new Date(now).toISOString(),
    tsMs: now,
    symbol: fields.symbol ?? 'XAUUSD',
    type,
    ...fields,
  });
}

export function logSignal(args: {
  symbol?: string;
  side: 'BUY' | 'SELL';
  setup?: 'P1' | 'P2' | 'P3' | null;
  signalTsMs: number;
  intendedEntry: number;
  intendedSl?: number;
  intendedTp?: number;
  equityUsd?: number;
  meta?: Record<string, unknown>;
}): ForwardDemoEvent {
  return logForwardEvent('SIGNAL', {
    symbol: args.symbol,
    side: args.side,
    setup: args.setup,
    signalTs: new Date(args.signalTsMs).toISOString(),
    signalTsMs: args.signalTsMs,
    intendedEntry: args.intendedEntry,
    intendedSl: args.intendedSl,
    intendedTp: args.intendedTp,
    equityUsd: args.equityUsd,
    meta: args.meta,
  });
}

export function logOrderIntent(args: {
  symbol?: string;
  side: 'BUY' | 'SELL';
  intendedEntry: number;
  spreadAtExecutionPips?: number;
  meta?: Record<string, unknown>;
}): ForwardDemoEvent {
  return logForwardEvent('ORDER_INTENT', {
    symbol: args.symbol,
    side: args.side,
    intendedEntry: args.intendedEntry,
    spreadAtExecutionPips: args.spreadAtExecutionPips,
    meta: args.meta,
  });
}

export function logOrderFill(args: {
  symbol?: string;
  side: 'BUY' | 'SELL';
  intendedEntry: number;
  actualFill: number;
  pipSize?: number;
  spreadAtExecutionPips?: number;
  latencyMs?: number;
  ticket?: number;
  retcode?: number;
  broker?: string;
}): ForwardDemoEvent {
  const pip = args.pipSize ?? 0.1;
  const slip =
    args.side === 'BUY'
      ? (args.actualFill - args.intendedEntry) / pip
      : (args.intendedEntry - args.actualFill) / pip;
  return logForwardEvent('ORDER_FILL', {
    symbol: args.symbol,
    side: args.side,
    intendedEntry: args.intendedEntry,
    actualFill: args.actualFill,
    slippagePips: Math.round(slip * 100) / 100,
    spreadAtExecutionPips: args.spreadAtExecutionPips,
    latencyMs: args.latencyMs,
    ticket: args.ticket,
    retcode: args.retcode,
    broker: args.broker,
  });
}

export function logOrderRejected(args: {
  symbol?: string;
  side?: 'BUY' | 'SELL';
  rejectReason: string;
  latencyMs?: number;
}): ForwardDemoEvent {
  return logForwardEvent('ORDER_REJECTED', {
    symbol: args.symbol,
    side: args.side,
    rejected: true,
    rejectReason: args.rejectReason,
    latencyMs: args.latencyMs,
  });
}

export function logMissedTrade(args: { symbol?: string; missReason: string; signalTsMs?: number }): ForwardDemoEvent {
  return logForwardEvent('MISSED_TRADE', {
    symbol: args.symbol,
    missed: true,
    missReason: args.missReason,
    signalTsMs: args.signalTsMs,
    signalTs: args.signalTsMs != null ? new Date(args.signalTsMs).toISOString() : undefined,
  });
}

export function logEquitySnapshot(equityUsd: number, meta?: Record<string, unknown>): ForwardDemoEvent {
  return logForwardEvent('EQUITY_SNAPSHOT', { equityUsd, meta });
}

/** Alias used by run-forward-demo-30d.ts */
export function logForwardMissed(args: { reason: string; barTimeMs: number }): ForwardDemoEvent {
  return logMissedTrade({ missReason: args.reason, signalTsMs: args.barTimeMs });
}

/** Alias used by run-forward-demo-30d.ts */
export function logForwardSignal(args: {
  side: 'BUY' | 'SELL';
  entry?: number;
  sl?: number;
  tp?: number;
  setup?: 'P1' | 'P2' | 'P3' | null;
  barTimeMs: number;
}): ForwardDemoEvent {
  return logSignal({
    side: args.side,
    setup: args.setup,
    signalTsMs: args.barTimeMs,
    intendedEntry: args.entry ?? 0,
    intendedSl: args.sl,
    intendedTp: args.tp,
  });
}
