/**
 * Delegates to myapp/scripts/make-expo-qr.js (smart LAN IP + SDK 52 hints).
 * From repo root: node scripts/make-expo-qr.js
 * Or: cd myapp && npm run qr
 */
const { spawnSync } = require('child_process');
const path = require('path');

const script = path.join(__dirname, '..', 'myapp', 'scripts', 'make-expo-qr.js');
const r = spawnSync(process.execPath, [script, ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: process.env,
});
process.exit(r.status === null ? 1 : r.status);
