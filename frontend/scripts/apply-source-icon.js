/**
 * Apply branded source-icon.png to launcher assets (full-bleed, no crop).
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
      .png({ compressionLevel: 9 });

  await pipeline(1024).toFile(path.join(OUT, 'icon.png'));
  await pipeline(1024).toFile(path.join(OUT, 'adaptive-icon.png'));
  await pipeline(512).toFile(path.join(OUT, 'splash-icon.png'));
  await pipeline(48).toFile(path.join(OUT, 'favicon.png'));

  console.log('ICON_OK', OUT);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
