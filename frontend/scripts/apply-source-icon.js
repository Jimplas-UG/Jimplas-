/**
 * Apply the shared source-icon.png to launcher assets.
 * Never AI-regenerate — only resize/pad the provided artwork.
 *
 * The full icon (including golden ring) is inset on black so Android/iOS
 * rounded masks do not clip the celestial ring or diamond markers.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SRC_CANDIDATES = [
  path.join(ROOT, 'assets', 'source-icon-raw.png'),
  path.join(ROOT, 'assets', 'source-icon.png'),
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
    console.error('Missing source-icon-raw.png (shared BS icon)');
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
  // Keep an exact working copy of the shared file for inspection / re-runs.
  await fs.promises.writeFile(path.join(OUT, 'source-icon.png'), srcBuf);

  // Android adaptive safe zone ~66% diameter — inset until full golden ring clears squircle.
  const SCALES = {
    icon: 0.66,
    adaptive: 0.48,
    splash: 0.76,
    favicon: 0.76,
    brand: 0.86,
  };

  await (await framed(sharp, srcBuf, 1024, SCALES.icon)).toFile(path.join(OUT, 'icon.png'));
  await (await framed(sharp, srcBuf, 1024, SCALES.adaptive)).toFile(path.join(OUT, 'adaptive-icon.png'));
  await (await framed(sharp, srcBuf, 1024, SCALES.splash)).toFile(path.join(OUT, 'splash-icon.png'));
  await (await framed(sharp, srcBuf, 48, SCALES.favicon)).toFile(path.join(OUT, 'favicon.png'));

  const brandDir = path.join(OUT, 'brand');
  fs.mkdirSync(brandDir, { recursive: true });
  // In-app / opening splash mark — shared art, light pad only.
  await (await framed(sharp, srcBuf, 512, SCALES.brand)).toFile(path.join(brandDir, 'bs-app-logo.png'));

  const kb = Math.round(fs.statSync(path.join(OUT, 'icon.png')).size / 1024);
  console.log('ICON_OK', OUT, `from=${path.basename(SRC)} icon=${kb}KB`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
