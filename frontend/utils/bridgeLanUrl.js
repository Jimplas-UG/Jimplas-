/**
 * Expo Go LAN / localhost helpers for Python bridge URLs on a physical device.
 * 127.0.0.1 on the phone is the phone itself — not the PC running the bridge.
 */

export function isLocalhostApiUrl(url) {
  const u = String(url || '').trim();
  return /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(u);
}

/** LAN host Metro used when you opened Expo Go (e.g. 192.168.1.154). */
export function getMetroLanHost() {
  try {
    const Constants = require('expo-constants').default;
    const candidates = [
      Constants.expoGoConfig?.debuggerHost,
      Constants.manifest2?.extra?.expoGo?.debuggerHost,
      Constants.manifest?.debuggerHost,
    ];
    for (const dbg of candidates) {
      if (typeof dbg !== 'string') continue;
      const host = dbg.split(':')[0]?.trim();
      if (host && !isLoopbackHost(host)) return host;
    }
    const hostUri = Constants.expoConfig?.hostUri;
    if (typeof hostUri === 'string') {
      const m = hostUri.match(/\/\/([^/:]+)/);
      if (m?.[1] && !isLoopbackHost(m[1])) return m[1];
    }
  } catch {
    /* expo-constants optional */
  }
  return null;
}

function isLoopbackHost(host) {
  return host === 'localhost' || host === '127.0.0.1';
}

/** On Expo Go, 127.0.0.1 is the phone — rewrite to Metro LAN host when available. */
export function rewriteLocalhostBridgeUrl(url, port = 8766) {
  const u = String(url || '').trim();
  if (!isLocalhostApiUrl(u)) return u.replace(/\/$/, '');
  const lan = getMetroLanHost();
  if (!lan) return u.replace(/\/$/, '');
  try {
    const parsed = new URL(u);
    const p = parsed.port || String(port);
    return `http://${lan}:${p}`.replace(/\/$/, '');
  } catch {
    return `http://${lan}:${port}`.replace(/\/$/, '');
  }
}
