/**
 * Start Expo web dev server, then open Chrome/Edge in a 375×667 mobile-style window.
 * No extra npm packages — uses Node + installed Chromium browser only.
 *
 * Usage (from myapp):
 *   npm run web:mobile
 *   node scripts/start-web-mobile.js
 *
 * Env:
 *   WEB_PORT=8081          Metro / web port (default 8081)
 *   MOBILE_VIEW_W=375      Viewport width
 *   MOBILE_VIEW_H=667      Viewport height
 *   CHROME_PATH=...        Override browser executable
 *
 * Chrome / Edge flags used (Chromium):
 *   --app=<url>                    Minimal chrome; fixed “phone” window
 *   --window-size=375,667          Outer window size (CSS viewport area + chrome UI trimmed in app mode)
 *   --force-device-scale-factor=2  Retina-like density (optional; closer to phone DPR)
 *   --user-agent="…Mobile…"        Mobile Safari UA string
 *   --no-first-run --no-default-browser-check
 */
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

const root = path.join(__dirname, '..');
const port = String(process.env.WEB_PORT || process.env.METRO_PORT || '8081');
const url = `http://localhost:${port}`;
const w = process.env.MOBILE_VIEW_W || '375';
const h = process.env.MOBILE_VIEW_H || '667';
const MOBILE_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';

const BROWSER_CANDIDATES = [
  process.env.CHROME_PATH,
  process.env.EDGE_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/microsoft-edge',
].filter(Boolean);

function findBrowser() {
  for (const p of BROWSER_CANDIDATES) {
    try {
      if (fs.existsSync(p)) return p;
    } catch {
      /* ignore */
    }
  }
  return null;
}

function waitForServer(targetUrl, maxMs = 120000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tryOnce = () => {
      const req = http.get(targetUrl, (res) => {
        res.resume();
        resolve();
      });
      req.on('error', () => {
        if (Date.now() - start > maxMs) {
          reject(new Error(`Timed out waiting for ${targetUrl}`));
        } else {
          setTimeout(tryOnce, 600);
        }
      });
      req.setTimeout(4000, () => {
        req.destroy();
      });
    };
    tryOnce();
  });
}

function openMobileBrowser(browserPath, targetUrl) {
  const args = [
    `--app=${targetUrl}`,
    `--window-size=${w},${h}`,
    '--force-device-scale-factor=2',
    `--user-agent=${MOBILE_UA}`,
    '--disable-features=TranslateUI',
    '--no-first-run',
    '--no-default-browser-check',
  ];
  console.log('');
  console.log('[web:mobile] Browser:', browserPath);
  console.log('[web:mobile] Flags:', args.join(' '));
  console.log('');
  const proc = spawn(browserPath, args, { detached: true, stdio: 'ignore' });
  proc.unref();
}

function startExpoWeb() {
  const env = {
    ...process.env,
    BROWSER: 'none',
    EXPO_NO_BROWSER: '1',
  };
  const isWin = process.platform === 'win32';
  const cmd = isWin ? 'npx.cmd' : 'npx';
  const child = spawn(cmd, ['expo', 'start', '--web', '--port', port], {
    cwd: root,
    env,
    stdio: 'inherit',
    shell: isWin,
  });
  child.on('error', (err) => {
    console.error('[web:mobile] Failed to start expo:', err.message);
    process.exit(1);
  });
  child.on('exit', (code) => process.exit(code ?? 0));
  return child;
}

async function main() {
  console.log('');
  console.log('[web:mobile] Starting Expo web on', url);
  console.log('[web:mobile] Target viewport:', `${w}×${h}`);
  console.log('[web:mobile] (Full DevTools device toolbar is not available via CLI; use F12 → device mode for exact emulation.)');
  console.log('');

  startExpoWeb();

  try {
    await waitForServer(url);
  } catch (e) {
    console.warn('[web:mobile]', e.message);
    console.warn('[web:mobile] Open manually after Metro is ready:', url);
    return;
  }

  const browser = findBrowser();
  if (!browser) {
    console.warn('[web:mobile] Chrome/Edge not found. Paste this in a terminal after Metro is up:');
    printManualCommand(url);
    return;
  }
  openMobileBrowser(browser, url);
}

function printManualCommand(targetUrl) {
  const flags = `--app=${targetUrl} --window-size=${w},${h} --force-device-scale-factor=2 --user-agent="${MOBILE_UA}"`;
  console.log('');
  console.log('  Chrome:');
  console.log(`    & "${BROWSER_CANDIDATES[2] || 'chrome.exe'}" ${flags}`);
  console.log('  Edge:');
  console.log(`    & "${BROWSER_CANDIDATES[4] || 'msedge.exe'}" ${flags}`);
  console.log('');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
