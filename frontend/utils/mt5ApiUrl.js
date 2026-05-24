/**
 * Resolve MT5 Python API base URL for Expo Go on a physical device.
 * 127.0.0.1 / localhost = the phone itself — not the Windows PC running MT5.
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

export function getDefaultMt5ApiUrl(port = 8765) {
  const env = typeof process !== 'undefined' && process.env?.EXPO_PUBLIC_MT5_API_URL;
  if (env) return String(env).replace(/\/$/, '');
  const lan = getMetroLanHost();
  if (lan) return `http://${lan}:${port}`;
  return `http://127.0.0.1:${port}`;
}

export function formatMt5NetworkError(message, baseUrl) {
  const msg = message ? String(message) : 'Network request failed';
  const lan = getMetroLanHost();
  const suggest = lan ? `http://${lan}:8765` : 'http://YOUR_PC_IP:8765';
  const apiHint =
    'On your PC (keep window open):\n' +
    '  cd mt5_trading_system\\python\n' +
    '  .\\start-api.ps1\n' +
    'MT5 terminal must be open and logged in.\n' +
    `Phone API URL: ${suggest} (not 127.0.0.1). Same Wi‑Fi.`;
  if (/fetch|network|failed|ECONNREFUSED|Unable to connect/i.test(msg)) {
    return `${msg}\n\n${apiHint}`;
  }
  if (!isLocalhostApiUrl(baseUrl)) {
    return `${msg}\n\n${apiHint}\nSame Wi‑Fi · firewall allows port 8765 · URL http://PC_IP:8765`;
  }
  return (
    `${msg}\n\n` +
    `127.0.0.1 on a phone is the phone itself — not your PC.\n` +
    `Use your PC LAN address, e.g. ${suggest}\n\n` +
    apiHint
  );
}
