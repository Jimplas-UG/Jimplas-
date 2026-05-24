/**
 * Production hardening — no dev surfaces in release builds.
 */
import { IS_PRODUCTION_DESK } from './deskMode';

export function assertProductionDeskMode() {
  if (typeof __DEV__ !== 'undefined' && __DEV__ && process.env.EXPO_PUBLIC_DESK_LOCAL === '1') {
    console.warn('[Bilshenz] EXPO_PUBLIC_DESK_LOCAL=1 — strategy may bundle locally (dev only)');
  }
}

export function safeLog(...args) {
  if (!IS_PRODUCTION_DESK && typeof __DEV__ !== 'undefined' && __DEV__) {
    console.log(...args);
  }
}

export function safeWarn(...args) {
  if (!IS_PRODUCTION_DESK && typeof __DEV__ !== 'undefined' && __DEV__) {
    console.warn(...args);
  }
}

/** Strip verbose error detail in production UI. */
export function publicErrorMessage(err) {
  if (!IS_PRODUCTION_DESK) return err instanceof Error ? err.message : String(err);
  return 'Service temporarily unavailable';
}

assertProductionDeskMode();
