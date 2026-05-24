/**
 * Apply branded source-icon.png to launcher assets (full-bleed, optimized).
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SRC = path.join(ROOT, 'assets', 'source-icon.png');
const OUT = path.join(ROOT, 'assets');

async function main() {
  if (!fs.existsSync(SRC)) {
    console.error('Missing', SRC);
    process.exit(1);
  }
  let sharp;
  try {
    sharp = require('sharp');
  } catch {
    console.error('npm install --save-dev sharp');
    process.exit(1);
  }

  const pipeline = (size) =>
    sharp(SRC)
      .resize(size, size, { fit: 'cover', position: 'centre' })
      .png({ compressionLevel: 9, palette: true });

  await pipeline(1024).toFile(path.join(OUT, 'icon.png'));
  await pipeline(1024).toFile(path.join(OUT, 'adaptive-icon.png'));
  await pipeline(512).toFile(path.join(OUT, 'splash-icon.png'));
  await pipeline(48).toFile(path.join(OUT, 'favicon.png'));

  const kb = Math.round(fs.statSync(path.join(OUT, 'icon.png')).size / 1024);
  console.log('ICON_OK', OUT, `icon=${kb}KB`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
