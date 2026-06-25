/**
 * Download Android platform-tools (adb) into frontend/.tools if missing.
 * Usage: node scripts/ensure-adb.js
 */
const fs = require('fs');
const path = require('path');
const https = require('https');
const { execSync } = require('child_process');

const root = path.join(__dirname, '..');
const toolsDir = path.join(root, '.tools');
const ptDir = path.join(toolsDir, 'platform-tools');
const adbPath = path.join(ptDir, process.platform === 'win32' ? 'adb.exe' : 'adb');
const ZIP_URL = 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip';
const zipPath = path.join(toolsDir, 'platform-tools.zip');

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    https
      .get(url, (res) => {
        if (res.statusCode === 302 || res.statusCode === 301) {
          file.close();
          fs.unlinkSync(dest);
          return download(res.headers.location, dest).then(resolve, reject);
        }
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }
        res.pipe(file);
        file.on('finish', () => {
          file.close(resolve);
        });
      })
      .on('error', reject);
  });
}

async function main() {
  if (fs.existsSync(adbPath)) {
    console.log('[adb] OK:', adbPath);
    return;
  }
  console.log('[adb] Downloading platform-tools (one-time, ~15 MB)...');
  fs.mkdirSync(toolsDir, { recursive: true });
  await download(ZIP_URL, zipPath);
  fs.mkdirSync(ptDir, { recursive: true });
  if (process.platform === 'win32') {
    execSync(
      `powershell -NoProfile -Command "Expand-Archive -Path '${zipPath.replace(/'/g, "''")}' -DestinationPath '${toolsDir.replace(/'/g, "''")}' -Force"`,
      { stdio: 'inherit' },
    );
  } else {
    execSync(`unzip -o "${zipPath}" -d "${toolsDir}"`, { stdio: 'inherit' });
  }
  fs.unlinkSync(zipPath);
  if (!fs.existsSync(adbPath)) {
    throw new Error('adb not found after extract — check .tools/platform-tools');
  }
  console.log('[adb] Installed:', adbPath);
  console.log('[adb] Plug phone via USB, enable USB debugging, accept RSA prompt.');
  console.log('[adb] Then: npm run start:usb');
}

main().catch((e) => {
  console.error('[adb]', e.message || e);
  process.exit(1);
});
