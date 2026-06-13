/**
 * Starts Expo for Expo Go with the most reliable transport available:
 *
 * 1) Windows + Android device/emulator visible to adb:
 *    `adb reverse tcp:<port> tcp:<port>` then `expo start --localhost --go`
 *    (avoids Wi‑Fi / "Public" profile / firewall — fixes many
 *    "Failed to download remote update" cases.)
 *
 * 2) Otherwise: LAN with REACT_NATIVE_PACKAGER_HOSTNAME pinned.
 *
 * 3) EXPO_FORCE_TUNNEL=1 → `expo start --tunnel --go` (needs @expo/ngrok + outbound ngrok).
 *
 * Pass `--lan` to skip USB detection and force LAN + hostname.
 * Pass `--usb` to require USB/adb (fails if adb/device missing).
 *
 * Usage: node scripts/run-expo-go.js [--lan] [--usb] [--clear ...]
 */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const { adbHasDevice, adbReverseTcp, resolveAdbPath } = require('./resolve-adb');

const EXPO_GO_52 = 'https://expo.dev/go?sdkVersion=52';

console.log('');
console.log('[expo-go] Install / update Expo Go for SDK 52: ' + EXPO_GO_52);
console.log('[expo-go] This project uses Expo SDK 52 (expo package ~52.x).');
console.log('');

const raw = process.argv.slice(2);
const forceLan = raw.includes('--lan');
const forceUsb = raw.includes('--usb');
const forceTunnel = process.env.EXPO_FORCE_TUNNEL === '1' || process.env.EXPO_FORCE_TUNNEL === 'true';
const passThru = raw.filter((x) => x !== '--lan' && x !== '--usb');
const metroPort = process.env.METRO_PORT || process.env.RCT_METRO_PORT || '8081';

function isLikelyVirtualInterface(name) {
  const n = String(name).toLowerCase();
  return /virtual|vethernet|hyper-v|wsl|docker|vmware|vbox|npcap|zerotier|tailscale|nordlynx|tap-windows/i.test(
    n,
  );
}

function scoreLanIp(address) {
  const p = address.split('.').map(Number);
  if (p[0] === 127) return -1000;
  if (p[0] === 169 && p[1] === 254) return -500;
  if (p[0] === 192 && p[1] === 168) return 300;
  if (p[0] === 10) return 200;
  if (p[0] === 172 && p[1] >= 16 && p[1] <= 31) return 50;
  return 10;
}

function pickLanIp() {
  if (process.env.REACT_NATIVE_PACKAGER_HOSTNAME) {
    return process.env.REACT_NATIVE_PACKAGER_HOSTNAME.trim();
  }
  const nets = os.networkInterfaces();
  const rows = [];
  for (const name of Object.keys(nets)) {
    for (const addr of nets[name] || []) {
      if (addr.family !== 'IPv4' || addr.internal) continue;
      const virtual = isLikelyVirtualInterface(name);
      const score = scoreLanIp(addr.address) + (virtual ? -80 : 0);
      rows.push({ name, address: addr.address, score });
    }
  }
  rows.sort((a, b) => b.score - a.score);
  if (!rows.length) return '127.0.0.1';
  return rows[0].address;
}

const portArgs = passThru.includes('--port') ? [] : ['--port', String(metroPort)];

let expoArgs;

if (forceTunnel) {
  expoArgs = ['expo', 'start', '--tunnel', '--go', ...portArgs, ...passThru];
  console.log('');
  console.log('[expo-go] Mode: TUNNEL (EXPO_FORCE_TUNNEL=1)');
  console.log('[expo-go] Use the QR / URL from this terminal. Requires ngrok reachable from this PC.');
  console.log('');
} else if (
  (forceUsb || !forceLan) &&
  process.platform === 'win32' &&
  adbHasDevice() &&
  adbReverseTcp(metroPort)
) {
  expoArgs = ['expo', 'start', '--localhost', '--go', ...portArgs, ...passThru];
  const adbPath = resolveAdbPath() || 'adb';
  console.log('');
  console.log('[expo-go] Mode: USB / adb reverse tcp:' + metroPort + ' → Metro on localhost');
  console.log('[expo-go] adb:', adbPath);
  console.log('[expo-go] In Expo Go, use the QR from THIS terminal (often exp://127.0.0.1:' + metroPort + ').');
  console.log('');
} else {
  if (forceUsb) {
    console.error('');
    console.error('[expo-go] --usb failed: need adb in PATH + phone USB debugging + device listed as "device" in adb devices.');
    console.error('');
    process.exit(1);
  }
  const ip = pickLanIp();
  process.env.REACT_NATIVE_PACKAGER_HOSTNAME = ip;
  // Use --go only (not --lan): EXPO_OFFLINE skips expo.dev checks but cannot combine with --lan.
  expoArgs = ['expo', 'start', '--go', ...portArgs, ...passThru];
  console.log('');
  console.log('[expo-go] Mode: LAN  REACT_NATIVE_PACKAGER_HOSTNAME=' + ip);
  console.log('[expo-go] After Metro starts, open: exp://' + ip + ':' + metroPort);
  console.log('[expo-go] Use THIS terminal\'s QR/URL (not expo-go-qr.png) unless you just ran npm run qr with matching IP/port.');
  if (process.platform === 'win32') {
    console.log('');
    console.log('[expo-go] If Expo Go 52 shows "Failed to download remote update" on same Wi‑Fi:');
    console.log('[expo-go]   A) Admin PowerShell in frontend: npm run fix:metro-firewall  (allows TCP ' + metroPort + ' inbound)');
    console.log('[expo-go]   B) Plug USB + adb in PATH → npm run start:usb → open exp://127.0.0.1:' + metroPort + ' from this terminal');
    console.log('[expo-go]   C) Works through most Wi‑Fi blocks: npm run start:tunnel  (uses ngrok via @expo/ngrok)');
    console.log('[expo-go]   D) Some routers isolate clients (guest/AP isolation) → use USB or tunnel, not LAN.');
  }
  console.log('');
}

// Skip expo.dev API version checks when offline / behind firewall (Metro still bundles).
// Tunnel mode needs outbound network for ngrok — do not force offline there.
const childEnv = { ...process.env };
if (!forceTunnel && childEnv.EXPO_OFFLINE == null) {
  childEnv.EXPO_OFFLINE = '1';
}
if (!childEnv.EXPO_PUBLIC_DESK_API_URL?.trim()) {
  const apiHost = childEnv.REACT_NATIVE_PACKAGER_HOSTNAME || pickLanIp();
  childEnv.EXPO_PUBLIC_DESK_API_URL = `http://${apiHost}:8791`;
}
console.log('[expo-go] desk-api URL:', childEnv.EXPO_PUBLIC_DESK_API_URL);
console.log('[expo-go] Start strategy server: cd ..\\backend && npm run desk-api');

// CI=true disables Fast Refresh and can break Expo Go reloads — never default it on locally.
if (childEnv.CI === '1' || childEnv.CI === 'true') {
  childEnv.CI = 'false';
}

const expoCli = path.join(__dirname, '..', 'node_modules', 'expo', 'bin', 'cli');
const cliArgs = expoArgs[0] === 'expo' ? expoArgs.slice(1) : expoArgs;
const child = spawn(process.execPath, [expoCli, ...cliArgs], {
  stdio: 'inherit',
  shell: false,
  env: childEnv,
  cwd: path.join(__dirname, '..'),
});

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code == null ? 1 : code);
});
