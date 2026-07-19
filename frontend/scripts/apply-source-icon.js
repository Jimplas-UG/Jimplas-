/**
 * Apply branded source-icon.png to launcher assets.
 * Emblem is inset so the golden ring stays fully visible under OS rounded masks.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SRC_CANDIDATES = [
  path.join(ROOT, 'assets', 'source-icon.png'),
  path.join(ROOT, 'assets', 'source-icon-raw.png'),
];
const OUT = path.join(ROOT, 'assets');
const BG = { r: 0, g: 0, b: 0, alpha: 1 };

async function framed(sharp, srcBuf, size, scale) {
  const inner = Math.max(1, Math.round(size * scale));
  const pad = Math.floor((size - inner) / 2);
  const resized = await sharp(srcBuf)
    .resize(inner, inner, { fit: 'contain', background: BG })
    .png()
    .toBuffer();
  return sharp({
    create: {
      width: size,
      height: size,
      channels: 4,
      background: BG,
    },
  })
    .composite([{ input: resized, top: pad, left: pad }])
    .png({ compressionLevel: 9 });
}

async function main() {
  const SRC = SRC_CANDIDATES.find((p) => fs.existsSync(p));
  if (!SRC) {
    console.error('Missing source-icon.png');
    process.exit(1);
  }
  let sharp;
  try {
    sharp = require('sharp');
  } catch {
    console.error('npm install --save-dev sharp');
    process.exit(1);
  }

  const srcBuf = await fs.promises.readFile(SRC);

  // Store / iOS-style icon: light inset so ring clears squircle mask.
  await (await framed(sharp, srcBuf, 1024, 0.90)).toFile(path.join(OUT, 'icon.png'));
  // Android adaptive foreground safe zone ~66%; keep emblem smaller.
  await (await framed(sharp, srcBuf, 1024, 0.72)).toFile(path.join(OUT, 'adaptive-icon.png'));
  await (await framed(sharp, srcBuf, 512, 0.86)).toFile(path.join(OUT, 'splash-icon.png'));
  await (await framed(sharp, srcBuf, 48, 0.90)).toFile(path.join(OUT, 'favicon.png'));

  // Keep brand copy in sync for in-app / web.
  const brandDir = path.join(OUT, 'brand');
  fs.mkdirSync(brandDir, { recursive: true });
  await (await framed(sharp, srcBuf, 512, 0.92)).toFile(path.join(brandDir, 'bs-app-logo.png'));

  const kb = Math.round(fs.statSync(path.join(OUT, 'icon.png')).size / 1024);
  console.log('ICON_OK', OUT, `from=${path.basename(SRC)} icon=${kb}KB`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
