/**
 * Local dev preview — mock APIs, dev menu, skip splash.
 * Enable: EXPO_PUBLIC_DEV_PREVIEW=1 (set by npm run start:dev)
 */

export function isDevPreview() {
  if (typeof __DEV__ === 'undefined' || !__DEV__) return false;
  const v = process.env.EXPO_PUBLIC_DEV_PREVIEW?.trim();
  if (v === '1' || v === 'true') return true;
  return process.env.EXPO_PUBLIC_MOCK_API === '1';
}

export function useMockApi() {
  if (typeof __DEV__ !== 'undefined' && !__DEV__) return false;
  if (process.env.EXPO_PUBLIC_MOCK_API === '0') return false;
  return isDevPreview() || process.env.EXPO_PUBLIC_MOCK_API === '1';
}

export function skipSplash() {
  if (!isDevPreview()) return false;
  if (process.env.EXPO_PUBLIC_SKIP_SPLASH !== '0') {
    return true;
  }
  return false;
}

export function devScreens() {
  return [
    { id: 'home', label: 'Home', icon: '⌂' },
    { id: 'desk', label: 'Intel / Desk', icon: '◈' },
    { id: 'trade', label: 'Trade', icon: '⚡' },
    { id: 'profile', label: 'Profile & Broker', icon: '👤' },
    { id: 'risk', label: 'Risk', icon: '◎' },
    { id: 'showcase', label: 'UI Showcase', icon: '▦' },
  ];
}
