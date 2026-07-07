#!/usr/bin/env node
/**
 * Idempotent patch — add public APK download routes to desk-api server.ts.
 * Works on VPS (old req.url health) and latest (urlEarly health).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '../..');
const serverTs = path.join(root, 'backend/src/server.ts');
let src = fs.readFileSync(serverTs, 'utf8');

if (src.includes('/download/bilshenz.apk')) {
  console.log('OK: APK download routes already present');
  process.exit(0);
}

const helpers = `
const REPO_ROOT = path.join(BACKEND_ROOT, '..');
const APK_CANDIDATES = [
  process.env.BILSHENZ_APK_PATH?.trim(),
  path.join(REPO_ROOT, 'frontend', 'dist', 'bilshenz-release.apk'),
  path.join(REPO_ROOT, 'frontend', 'dist', 'bilshenz-release-signed.apk'),
  '/opt/bilshenz/frontend/dist/bilshenz-release.apk',
].filter((p) => !!p);

function resolveApkPath() {
  for (const p of APK_CANDIDATES) {
    try {
      if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
    } catch {}
  }
  return null;
}

function serveApkDownload(res, apkPath) {
  const stat = fs.statSync(apkPath);
  res.writeHead(200, {
    'Content-Type': 'application/vnd.android.package-archive',
    'Content-Disposition': 'attachment; filename="bilshenz-release.apk"',
    'Content-Length': stat.size,
    'Cache-Control': 'public, max-age=300',
  });
  fs.createReadStream(apkPath).pipe(res);
}
`;

if (!src.includes("import * as fs from 'node:fs'")) {
  src = src.replace(
    "import * as path from 'node:path';",
    "import * as fs from 'node:fs';\nimport * as path from 'node:path';",
  );
}

if (!src.includes('function resolveApkPath()')) {
  src = src.replace(
    "const BACKEND_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');",
    "const BACKEND_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');" + helpers,
  );
}

const routeBlock = `
  const _apkPath = (req.url ?? '/').split('?')[0];
  if (
    (_apkPath === '/download/bilshenz.apk' || _apkPath === '/download/bilshenz-release.apk') &&
    req.method === 'GET'
  ) {
    const apkFile = resolveApkPath();
    if (!apkFile) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        error: 'apk_not_found',
        detail: 'Upload bilshenz-release.apk to /opt/bilshenz/frontend/dist/',
      }));
      return;
    }
    serveApkDownload(res, apkFile);
    return;
  }
  if (_apkPath === '/download' && req.method === 'GET') {
    const apkFile = resolveApkPath();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      ok: !!apkFile,
      apkUrl: apkFile ? '/download/bilshenz.apk' : null,
      sizeBytes: apkFile ? fs.statSync(apkFile).size : null,
    }));
    return;
  }
`;

const anchors = [
  `  if (req.url === '/health' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true, service: 'desk-api' }));
    return;
  }`,
  `  if (urlEarly.pathname === '/health' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true, service: 'desk-api' }));
    return;
  }`,
];

let patched = false;
for (const anchor of anchors) {
  if (src.includes(anchor)) {
    src = src.replace(anchor, anchor + routeBlock);
    patched = true;
    break;
  }
}

if (!patched) throw new Error('Could not find health anchor in server.ts');

fs.writeFileSync(serverTs, src);
console.log('PATCHED: backend/src/server.ts — restart bilshenz-desk-api');
