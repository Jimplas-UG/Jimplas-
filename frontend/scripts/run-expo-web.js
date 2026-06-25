/**
 * Start Expo web dev server with .env.local loaded (desk-api / Binance URLs).
 *
 * Usage:
 *   npm run web
 *   node scripts/run-expo-web.js [--clear] [--port 8081]
 */
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

const frontendRoot = path.join(__dirname, '..');

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

function deskHealthUrl() {
  const base = (process.env.EXPO_PUBLIC_DESK_API_URL || 'http://127.0.0.1:8791').replace(/\/$/, '');
  return `${base}/health`;
}

function probeDeskApi(timeoutMs = 4000) {
  return new Promise((resolve) => {
    const url = new URL(deskHealthUrl());
    const req = http.get(
      { hostname: url.hostname, port: url.port || 80, path: url.pathname, timeout: timeoutMs },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      },
    );
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function main() {
  const raw = process.argv.slice(2);
const portIdx = raw.findIndex((a) => a === '--port');
const port = portIdx >= 0 ? raw[portIdx + 1] : process.env.WEB_PORT || process.env.METRO_PORT || '8081';
const passThru = raw.filter((a, i) => a !== '--port' && (portIdx < 0 || i !== portIdx + 1));

const env = {
  ...process.env,
  EXPO_NO_DOTENV: '1',
};

const isWin = process.platform === 'win32';
const cmd = isWin ? 'npx.cmd' : 'npx';
const args = ['expo', 'start', '--web', '--port', String(port), ...passThru];

console.log('');
console.log('[expo-web] Starting Bilshenz web preview on http://localhost:' + port);
console.log('[expo-web] Desk API:', process.env.EXPO_PUBLIC_DESK_API_URL || 'http://127.0.0.1:8791');

const deskUp = await probeDeskApi();
if (!deskUp) {
  console.warn('');
  console.warn('[expo-web] WARNING: desk-api is not reachable at', deskHealthUrl());
  console.warn('[expo-web] Sign-in will fail until you start it:');
  console.warn('[expo-web]   cd ..\\backend');
  console.warn('[expo-web]   $env:DESK_API_KEY="dev"; $env:AUTH_JWT_SECRET="dev-jwt-secret-min-32-chars-long!!"; npm run desk-api');
  console.warn('');
} else {
  console.log('[expo-web] desk-api: OK');
}

console.log('[expo-web] Open Chrome, Edge, or Firefox at the URL above when Metro is ready.');
console.log('');

const child = spawn(cmd, args, {
  cwd: frontendRoot,
  env,
  stdio: 'inherit',
  shell: isWin,
});

child.on('error', (err) => {
  console.error('[expo-web] Failed to start:', err.message);
  process.exit(1);
});

child.on('exit', (code) => process.exit(code ?? 0));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
