import * as fs from 'node:fs';
import * as path from 'node:path';

export type LogEvent =
  | 'trade'
  | 'error'
  | 'reconnect'
  | 'restart'
  | 'safety'
  | 'info'
  | 'missed';

const DEFAULT_LOG_DIR =
  process.platform === 'win32' ? 'C:\\logs\\tradingbot' : '/var/log/tradingbot';
const LOG_DIR = process.env.TRADINGBOT_LOG_DIR ?? DEFAULT_LOG_DIR;

function ensureDir(): void {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
}

function writeJsonl(file: string, row: Record<string, unknown>): void {
  ensureDir();
  const line = JSON.stringify({ ts: new Date().toISOString(), ...row }) + '\n';
  fs.appendFileSync(path.join(LOG_DIR, file), line, 'utf8');
}

export function logTrade(row: Record<string, unknown>): void {
  writeJsonl('trades.jsonl', { event: 'trade', ...row });
}

export function logError(msg: string, extra?: Record<string, unknown>): void {
  writeJsonl('errors.jsonl', { event: 'error', message: msg, ...extra });
}

export function logReconnect(msg: string, extra?: Record<string, unknown>): void {
  writeJsonl('reconnect.jsonl', { event: 'reconnect', message: msg, ...extra });
}

export function logSafety(msg: string, extra?: Record<string, unknown>): void {
  writeJsonl('safety.jsonl', { event: 'safety', message: msg, ...extra });
}

export function logInfo(msg: string, extra?: Record<string, unknown>): void {
  writeJsonl('bot.jsonl', { event: 'info', message: msg, ...extra });
}
