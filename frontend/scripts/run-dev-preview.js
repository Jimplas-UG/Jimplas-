/**
 * Dev preview launcher — mock APIs, hot reload via Metro.
 * Usage: npm run start:dev
 *        npm run android:dev   (USB emulator + Metro)
 */
const { spawn } = require('child_process');
const path = require('path');
const { adbHasDevice, adbReverseTcp, resolveAdbPath } = require('./resolve-adb');

const frontendRoot = path.join(__dirname, '..');
const passThru = process.argv.slice(2).filter((x) => x !== '--android');

const childEnv = {
  ...process.env,
  EXPO_PUBLIC_DEV_PREVIEW: '1',
  EXPO_PUBLIC_MOCK_API: '1',
  EXPO_PUBLIC_SKIP_SPLASH: process.env.EXPO_PUBLIC_SKIP_SPLASH ?? '0',
  EXPO_PUBLIC_DESK_REMOTE: '1',
  EXPO_PUBLIC_DESK_DIAG: '1',
  EXPO_PUBLIC_BROKER_MODE: process.env.EXPO_PUBLIC_BROKER_MODE || 'binance',
};

console.log('');
console.log('[dev-preview] Mock API ON — backend optional');
console.log('[dev-preview] Tap ⚙ floating button → Dev Navigator → all screens');
console.log('[dev-preview] Hot reload: save any file (Metro Fast Refresh)');
console.log('');

const forceLan = passThru.includes('--lan');
const hasAdbDevice = adbHasDevice();

if (process.argv.includes('--android')) {
  if (!resolveAdbPath()) {
    console.warn('[dev-preview] adb not found — install Android SDK platform-tools or Android Studio.');
    console.warn('[dev-preview] Typical path: %LOCALAPPDATA%\\Android\\Sdk\\platform-tools');
  } else if (!hasAdbDevice) {
    console.warn('[dev-preview] No adb device — enable USB debugging and accept the RSA prompt on the phone.');
  } else {
    adbReverseTcp(8081);
    adbReverseTcp(8791);
    console.log('[dev-preview] adb reverse OK (8081, 8791)');
  }
}

// Without USB/adb, LAN often fails on Windows (firewall / guest Wi‑Fi isolation) → use tunnel by default.
if (
  !forceLan &&
  !hasAdbDevice &&
  process.env.EXPO_FORCE_TUNNEL !== '1' &&
  process.env.EXPO_FORCE_TUNNEL !== 'true' &&
  process.platform === 'win32'
) {
  childEnv.EXPO_FORCE_TUNNEL = '1';
  console.log('[dev-preview] No USB device — starting TUNNEL mode (avoids "Failed to download remote update").');
  console.log('[dev-preview] LAN instead: npm run start:dev:lan  |  USB: npm run android:dev');
  console.log('');
}

const child = spawn(process.execPath, [path.join(__dirname, 'run-expo-go.js'), ...passThru], {
  stdio: 'inherit',
  env: childEnv,
  cwd: frontendRoot,
});

child.on('exit', (code) => process.exit(code == null ? 1 : code));
