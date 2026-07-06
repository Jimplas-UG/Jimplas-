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
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { adbHasDevice, adbReverseTcp, resolveAdbPath } = require('./resolve-adb');

const frontendRoot = path.join(__dirname, '..');

/** Load .env.local before picking LAN IP (avoids stale shell hostname). */
function loadEnvLocal() {
  const p = path.join(frontendRoot, '.env.local');
  if (!fs.existsSync(p)) return;
  for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq < 1) continue;
    const key = trimmed.slice(0, eq).trim();
    const val = trimmed.slice(eq + 1).trim();
    if (key.startsWith('EXPO_PUBLIC_') && !process.env[key]) process.env[key] = val;
  }
}

loadEnvLocal();

const raw = process.argv.slice(2);
const forceLan = raw.includes('--lan');
const forceUsb = raw.includes('--usb');
const forceTunnelFlag = raw.includes('--tunnel');

const { ensureMetroFirewall } = require('./ensure-metro-firewall');

const EXPO_GO_52 = 'https://expo.dev/go?sdkVersion=52';

console.log('');
console.log('[expo-go] Install / update Expo Go for SDK 52: ' + EXPO_GO_52);
console.log('[expo-go] This project uses Expo SDK 52 (expo package ~52.x).');
console.log('');

const hasAdbDevice = adbHasDevice();
const passThru = raw.filter((x) => x !== '--lan' && x !== '--usb' && x !== '--tunnel');
const metroPort = process.env.METRO_PORT || process.env.RCT_METRO_PORT || '8081';

let useTunnel =
  !forceLan &&
  (forceTunnelFlag || process.env.EXPO_FORCE_TUNNEL === '1' || process.env.EXPO_FORCE_TUNNEL === 'true');

if (!useTunnel && !forceLan && !forceUsb && process.platform === 'win32' && !hasAdbDevice) {
  useTunnel = true;
  console.log('[expo-go] No USB device — using TUNNEL mode (avoids Expo Go download fatal errors).');
  console.log('[expo-go] Same Wi‑Fi LAN: npm run start:lan  |  USB: npm run start:usb');
  console.log('');
}

const usbReverseOk =
  !useTunnel &&
  (forceUsb || !forceLan) &&
  process.platform === 'win32' &&
  hasAdbDevice &&
  adbReverseTcp(metroPort);

if (!useTunnel && !usbReverseOk && process.platform === 'win32' && !ensureMetroFirewall()) {
  useTunnel = true;
  console.log('[expo-go] LAN blocked by firewall — switching to TUNNEL so Expo Go can connect.');
  console.log('[expo-go] For Wi‑Fi LAN later: Admin → npm run fix:metro-firewall → npm run start:lan');
  console.log('');
}

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

function applyPhoneApiUrls(env, host) {
  if (!host || host === '127.0.0.1') return;
  for (const [key, port] of [
    ['EXPO_PUBLIC_DESK_API_URL', 8791],
    ['EXPO_PUBLIC_BINANCE_API_URL', 8766],
  ]) {
    const v = env[key]?.trim() || '';
    if (!v || /127\.0\.0\.1|localhost/i.test(v)) {
      env[key] = `http://${host}:${port}`;
    }
  }
}

function pickLanIp() {
  const fromDesk = process.env.EXPO_PUBLIC_DESK_API_URL?.match(/https?:\/\/([^:/]+)/)?.[1];
  if (fromDesk && !fromDesk.includes('127.0.0.1') && !fromDesk.includes('localhost')) {
    return fromDesk;
  }
  const pinned = process.env.EXPO_PACKAGER_PINNED?.trim();
  if (pinned) return pinned;
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

if (useTunnel) {
  expoArgs = ['expo', 'start', '--tunnel', '--go', ...portArgs, ...passThru];
  console.log('');
  console.log('[expo-go] Mode: TUNNEL — scan the QR / exp URL from THIS terminal in Expo Go 52.');
  console.log('[expo-go] Requires outbound internet (ngrok). If tunnel fails, try USB + npm run start:usb.');
  console.log('');
} else if (usbReverseOk) {
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
  process.env.EXPO_PACKAGER_HOSTNAME = ip;
  process.env.EXPO_PACKAGER_PINNED = ip;
  applyPhoneApiUrls(process.env, ip);
  expoArgs = ['expo', 'start', '--lan', '--go', ...portArgs, ...passThru];
  console.log('');
  console.log('[expo-go] Mode: LAN  REACT_NATIVE_PACKAGER_HOSTNAME=' + ip);
  console.log('[expo-go] After Metro starts, open: exp://' + ip + ':' + metroPort);
  try {
    spawnSync(process.execPath, [path.join(__dirname, 'make-expo-qr.js')], {
      stdio: 'inherit',
      env: { ...process.env, EXPO_LAN_IP: ip, METRO_PORT: metroPort },
      cwd: frontendRoot,
    });
  } catch {
    /* qr optional */
  }
  console.log('[expo-go] Open frontend/expo-go-qr.html in your browser to scan.');
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

// Do not force EXPO_OFFLINE — it breaks Expo Go manifest fetch on many devices.
const childEnv = { ...process.env };
delete childEnv.EXPO_OFFLINE;
if (!useTunnel) delete childEnv.EXPO_FORCE_TUNNEL;
if (!childEnv.EXPO_PUBLIC_SKIP_SPLASH?.trim()) {
  childEnv.EXPO_PUBLIC_SKIP_SPLASH = '1';
}
if (!childEnv.EXPO_PUBLIC_DESK_API_URL?.trim()) {
  const apiHost = pickLanIp();
  childEnv.EXPO_PUBLIC_DESK_API_URL = `http://${apiHost}:8791`;
}
if (!childEnv.EXPO_PUBLIC_BINANCE_API_URL?.trim()) {
  const apiHost = pickLanIp();
  childEnv.EXPO_PUBLIC_BINANCE_API_URL = `http://${apiHost}:8766`;
}
const packHost =
  childEnv.REACT_NATIVE_PACKAGER_HOSTNAME ||
  childEnv.EXPO_PACKAGER_HOSTNAME ||
  pickLanIp();
applyPhoneApiUrls(childEnv, packHost);
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
