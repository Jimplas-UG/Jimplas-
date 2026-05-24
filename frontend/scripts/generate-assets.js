/**
 * Branded PNG assets from the Bilshenz hex logo (UI / CinematicSplash geometry).
 */
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, '..', 'assets');

async function main() {
  const { buildHexLogoSvg } = await import('../components/logo/buildHexLogoSvg.js');
  let sharp;
  try {
    sharp = require('sharp');
  } catch {
    console.error('Install sharp: npm install --save-dev sharp');
    process.exit(1);
  }

  if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

  const iconSvg = Buffer.from(buildHexLogoSvg({ background: '#000000', variant: 'icon' }));
  const adaptiveSvg = Buffer.from(buildHexLogoSvg({ background: '#000000', variant: 'adaptiveIcon' }));
  const splashSvg = Buffer.from(buildHexLogoSvg({ background: '#000000', variant: 'splash' }));
  const faviconSvg = Buffer.from(buildHexLogoSvg({ background: '#000000', variant: 'icon' }));

  await sharp(iconSvg).resize(1024, 1024, { fit: 'contain', background: '#000000' }).png().toFile(path.join(OUT, 'icon.png'));
  await sharp(adaptiveSvg).resize(1024, 1024, { fit: 'contain', background: '#000000' }).png().toFile(path.join(OUT, 'adaptive-icon.png'));
  await sharp(splashSvg).resize(512, 512, { fit: 'contain', background: '#000000' }).png().toFile(path.join(OUT, 'splash-icon.png'));
  await sharp(faviconSvg).resize(48, 48, { fit: 'contain', background: '#000000' }).png().toFile(path.join(OUT, 'favicon.png'));

  fs.writeFileSync(path.join(OUT, 'logo.svg'), iconSvg);
  fs.writeFileSync(path.join(OUT, 'logo-splash.svg'), splashSvg);
  console.log('ASSETS_OK', OUT);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
