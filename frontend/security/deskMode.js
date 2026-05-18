/**
 * Desk security mode — when true, UI must not show strategy internals and
 * the client should prefer the remote desk API over bundled engine code.
 */
export const IS_PRODUCTION_DESK =
  typeof __DEV__ !== 'undefined'
    ? !__DEV__ || process.env.EXPO_PUBLIC_DESK_REMOTE === '1'
    : process.env.EXPO_PUBLIC_DESK_REMOTE === '1';

/** Show INTEL panels, gate names, formulas, scanner math (dev / local engine only). */
export const SHOW_STRATEGY_INTEL = !IS_PRODUCTION_DESK;

/** Log verbose engine / gate diagnostics to console. */
export const ENABLE_DESK_DIAGNOSTICS = !IS_PRODUCTION_DESK && process.env.EXPO_PUBLIC_DESK_DIAG !== '0';

export function getDeskApiBase() {
  const base = process.env.EXPO_PUBLIC_DESK_API_URL?.trim();
  return base || 'http://127.0.0.1:8791';
}

export function deskApiHeaders() {
  const key = process.env.EXPO_PUBLIC_DESK_API_KEY?.trim();
  if (!key) return {};
  return { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' };
}
