/**
 * Writes myapp/expo-go-qr.png encoding exp://<LAN_IP>:<PORT>
 * Run from myapp while Metro is up (default port 8081).
 * Override: METRO_PORT=8082 EXPO_LAN_IP=192.168.1.10 node scripts/make-expo-qr.js
 */
const path = require('path');
const os = require('os');
const QRCode = require('qrcode');

function isLikelyVirtualInterface(name) {
  const n = String(name).toLowerCase();
  return (
    /virtual|vethernet|hyper-v|wsl|docker|vmware|vbox|npcap|zerotier|tailscale|nordlynx|tap-windows/i.test(
      n,
    ) || n.startsWith('veth')
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

function collectLanCandidates() {
  const nets = os.networkInterfaces();
  const rows = [];
  for (const name of Object.keys(nets)) {
    for (const addr of nets[name] || []) {
      if (addr.family !== 'IPv4' || addr.internal) continue;
      const virtual = isLikelyVirtualInterface(name);
      const score = scoreLanIp(addr.address) + (virtual ? -80 : 0);
      rows.push({ name, address: addr.address, virtual, score });
    }
  }
  rows.sort((a, b) => b.score - a.score);
  return rows;
}

function pickBestIp() {
  const rows = collectLanCandidates();
  if (rows.length === 0) return { ip: '127.0.0.1', rows };
  return { ip: rows[0].address, rows };
}

const port = process.env.METRO_PORT || process.env.EXPO_METRO_PORT || '8081';
const manualIp = process.env.EXPO_LAN_IP;
const { ip: autoIp, rows } = pickBestIp();
const ip = manualIp || autoIp;
const url = `exp://${ip}:${port}`;
const root = path.join(__dirname, '..');
const out = path.join(root, 'expo-go-qr.png');
const outHtml = path.join(root, 'expo-go-qr.html');
const outAssets = path.join(root, 'assets', 'expo-go-qr.png');

function main() {
  console.log('');
  console.log('=== Expo Go SDK 52 ===');
  console.log('Install / update: https://expo.dev/go?sdkVersion=52');
  console.log('');
  console.log('=== Expo Go LAN URLs (same Wi‑Fi as this PC) ===');
  if (manualIp) console.log('Using EXPO_LAN_IP override:', manualIp);
  for (const r of rows) {
    const tag = r.virtual ? ' (virtual?)' : '';
    console.log(`  exp://${r.address}:${port}  ← ${r.name}${tag}`);
  }
  if (rows.length === 0) console.log('  (no non-loopback IPv4 found — use USB or tunnel)');
  console.log('');
  console.log('QR payload (chosen):', url);
  console.log('');
  console.log('If the phone cannot open the app:');
  console.log('  1) npm start — plug Android via USB + USB debugging: uses adb reverse (no Wi‑Fi).');
  console.log('  2) Wi‑Fi LAN: npm run start:lan, then scan this QR (or set EXPO_LAN_IP if IP is wrong).');
  console.log('  3) Tunnel: EXPO_FORCE_TUNNEL=1 npm start (needs ngrok allowed through firewall).');
  console.log('  4) Expo Go must match SDK 52: https://expo.dev/go?sdkVersion=52');
  console.log('  5) Windows: Private Wi‑Fi + in myapp (Admin PS): npm run fix:metro-firewall');
  console.log('');
}

main();

const fs = require('fs');

async function writeAll() {
  const dataUrl = await QRCode.toDataURL(url, { width: 420, margin: 2, errorCorrectionLevel: 'M' });
  await QRCode.toFile(out, url, { width: 420, margin: 2, errorCorrectionLevel: 'M' });
  const html = `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>Expo Go QR</title>
<style>body{font-family:system-ui;background:#111;color:#e8d4a0;text-align:center;padding:24px}
img{background:#fff;padding:12px;border-radius:12px}code{display:block;margin:16px;font-size:18px;color:#fff}
p{color:#aaa;font-size:14px;max-width:480px;margin:12px auto;line-height:1.5}</style></head>
<body><h1>Bilshenz — Expo Go</h1><img src="${dataUrl}" width="420" height="420" alt="QR code"/>
<code>${url}</code>
<p>Scan with Expo Go (SDK 52). PC must run <strong>npm start</strong> in myapp; phone on same Wi‑Fi.</p>
<p>Or in Expo Go: Enter URL manually → paste the code above.</p></body></html>`;
  fs.writeFileSync(outHtml, html, 'utf8');
  fs.mkdirSync(path.join(root, 'assets'), { recursive: true });
  fs.copyFileSync(out, outAssets);
  console.log('Wrote', out);
  console.log('Wrote', outHtml, '(open in Chrome/Edge if Cursor cannot preview PNG)');
  console.log('Wrote', outAssets);
}

writeAll().catch((err) => {
  console.error(err);
  process.exit(1);
});
