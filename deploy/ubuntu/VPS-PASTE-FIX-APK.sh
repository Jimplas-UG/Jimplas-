#!/usr/bin/env bash
# Paste on VPS (root SSH) — patches desk-api for public APK download on :8791
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/bilshenz}"
SERVER="$APP_DIR/backend/src/server.ts"
mkdir -p "$APP_DIR/frontend/dist"

if grep -q '/download/bilshenz.apk' "$SERVER" 2>/dev/null; then
  echo "OK: download route already present"
else
  echo "PATCH: backend/src/server.ts"
  export SERVER="$SERVER"
  node <<'NODE'
const fs = require('fs');
const serverTs = process.env.SERVER;
let src = fs.readFileSync(serverTs, 'utf8');

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
  if (src.includes('const REPO_ROOT = path.join(BACKEND_ROOT')) {
    src = src.replace(/const REPO_ROOT[\s\S]*?function serveApkDownload[\s\S]*?\}\n/, helpers.trim() + '\n');
  } else {
    src = src.replace(
      'const BACKEND_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), \'..\');',
      'const BACKEND_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), \'..\');' + helpers,
    );
  }
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
  if (src.includes(anchor) && !src.includes('/download/bilshenz.apk')) {
    src = src.replace(anchor, anchor + routeBlock);
    patched = true;
    break;
  }
}

if (!patched) throw new Error('Could not find health anchor in server.ts — paste server.ts header manually');
fs.writeFileSync(serverTs, src);
console.log('PATCHED', serverTs);
NODE
fi

systemctl restart bilshenz-desk-api
sleep 2

echo "==> local /download"
curl -s http://127.0.0.1:8791/download || true
echo ""
PUB=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo "Install: http://${PUB}:8791/download/bilshenz.apk"
if [[ -f "$APP_DIR/frontend/dist/bilshenz-release.apk" ]]; then
  ls -lh "$APP_DIR/frontend/dist/bilshenz-release.apk"
else
  echo "Upload APK: scp bilshenz-release.apk root@${PUB}:/opt/bilshenz/frontend/dist/bilshenz-release.apk"
fi
