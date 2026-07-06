/**
 * Pre-build the Android JS bundle so Expo Go does not hit IOException on first scan.
 * Usage: node scripts/warm-metro-bundle.js [port]
 */
const http = require('http');

const port = String(process.argv[2] || process.env.METRO_PORT || '8081');
const BUNDLE_PATH =
  '/index.bundle?platform=android&dev=true&minify=false&modulesOnly=false&runModule=true';

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function httpGet(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      res.on('data', () => {});
      res.on('end', () => resolve(res.statusCode || 0));
    });
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('timeout'));
    });
  });
}

async function waitMetro(maxMs = 120000) {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    try {
      const code = await httpGet(`http://127.0.0.1:${port}/status`, 5000);
      if (code === 200) return true;
    } catch {
      /* retry */
    }
    await sleep(2000);
  }
  return false;
}

async function main() {
  console.log('');
  console.log('[metro-warm] Waiting for Metro on port ' + port + '…');
  if (!(await waitMetro())) {
    console.log('[metro-warm] Metro not ready — start Metro first, then scan QR.');
    process.exit(1);
  }

  console.log('[metro-warm] Building Android bundle (first run ~30–90s). Keep Expo Go CLOSED until done…');
  const t0 = Date.now();
  try {
    const code = await httpGet(`http://127.0.0.1:${port}${BUNDLE_PATH}`, 180000);
    const sec = Math.round((Date.now() - t0) / 1000);
    if (code >= 200 && code < 300) {
      console.log('[metro-warm] OK — bundle ready in ' + sec + 's. You can scan QR in Expo Go now.');
      process.exit(0);
    }
    console.log('[metro-warm] Bundle HTTP ' + code + ' — check Metro terminal for errors.');
    process.exit(1);
  } catch (e) {
    console.log('[metro-warm] Bundle failed: ' + (e.message || e));
    console.log('[metro-warm] Try: close Metro, run CONNECT-EXPO-GO.cmd as Administrator.');
    process.exit(1);
  }
}

main();
