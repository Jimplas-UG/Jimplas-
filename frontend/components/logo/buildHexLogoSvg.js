import { CX, CY, DIAMONDS, INNER_HEX, LOGO_LAYOUTS, MAIN_HEX, VB, logoTransform } from './hexLogoGeometry.js';

/**
 * Static Bilshenz hex logo SVG (matches CinematicSplash solid mode).
 * @param {{ size?: number, background?: string, variant?: 'icon'|'adaptiveIcon'|'splash'|'default' }} [options]
 */
export function buildHexLogoSvg({ size = VB, background = '#000000', variant = 'default' } = {}) {
  const isIcon = variant === 'icon' || variant === 'adaptiveIcon';
  const transform = logoTransform(variant);
  const bX = isIcon ? 30.5 : 27;
  const sX = isIcon ? 41.5 : 39;
  const textY = isIcon ? 44.5 : 45;

  const diamondPolys = DIAMONDS.map(
    (pts, i) =>
      `<polygon points="${pts}" fill="${i < 4 ? '#F2E2B0' : '#D4B45A'}" fill-opacity="${i < 4 ? 0.92 : 0.62}"/>`,
  ).join('\n    ');

  const outerTicks = isIcon
    ? ''
    : `
    <line x1="40" y1="5" x2="40" y2="9" stroke="url(#goldLine)" stroke-width="1" stroke-opacity="0.92"/>
    <line x1="40" y1="71" x2="40" y2="75" stroke="url(#goldLine)" stroke-width="1" stroke-opacity="0.92"/>
    <line x1="71" y1="40" x2="75" y2="40" stroke="url(#goldLine)" stroke-width="1" stroke-opacity="0.92"/>
    <line x1="5" y1="40" x2="9" y2="40" stroke="url(#goldLine)" stroke-width="1" stroke-opacity="0.92"/>`;

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${VB} ${VB}">
  <defs>
    <linearGradient id="metalFill" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#3A3020"/>
      <stop offset="35%" stop-color="#1A160E"/>
      <stop offset="70%" stop-color="#0A0806"/>
      <stop offset="100%" stop-color="#000000"/>
    </linearGradient>
    <linearGradient id="goldLine" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FFF4D0"/>
      <stop offset="45%" stop-color="#D4B45A"/>
      <stop offset="100%" stop-color="#7A5C18"/>
    </linearGradient>
    <linearGradient id="gradB" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#F2E2B0"/>
      <stop offset="100%" stop-color="#C98A2E"/>
    </linearGradient>
    <linearGradient id="gradS" x1="100%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#F2E2B0"/>
      <stop offset="100%" stop-color="#7A5C18"/>
    </linearGradient>
    <radialGradient id="iconBg" cx="50%" cy="54%" r="62%">
      <stop offset="0%" stop-color="#221c14"/>
      <stop offset="45%" stop-color="#12100c"/>
      <stop offset="100%" stop-color="${background}"/>
    </radialGradient>
  </defs>
  <rect x="0" y="0" width="${VB}" height="${VB}" fill="${isIcon ? 'url(#iconBg)' : background}"/>
  <g transform="${transform}">${outerTicks}
    <circle cx="${CX}" cy="${CY}" r="35" fill="none" stroke="#D4B45A" stroke-width="0.4" stroke-opacity="0.55" stroke-dasharray="2,4"/>
    <polygon points="${MAIN_HEX}" fill="url(#metalFill)" stroke="url(#goldLine)" stroke-width="1.2"/>
    <polygon points="${INNER_HEX}" fill="none" stroke="#D4B45A" stroke-width="0.58" stroke-opacity="0.72" stroke-dasharray="2,2"/>
    ${diamondPolys}
    <circle cx="${CX}" cy="${CY}" r="28" fill="none" stroke="#D4B45A" stroke-width="0.34" stroke-dasharray="1,5" stroke-opacity="0.48"/>
    <line x1="40" y1="40" x2="40" y2="11" stroke="#F2E2B0" stroke-width="1" stroke-opacity="0.7" stroke-linecap="round"/>
    <circle cx="40" cy="11" r="1.6" fill="#F2E2B0" fill-opacity="0.95"/>
    <circle cx="${CX}" cy="${CY}" r="2.6" fill="#F2E2B0"/>
    <text x="${bX}" y="${textY}" font-size="16" font-weight="700" font-family="Georgia, serif" fill="url(#gradB)" stroke="url(#goldLine)" stroke-width="0.32">B</text>
    <text x="${sX}" y="${textY}" font-size="16" font-weight="700" font-family="Georgia, serif" fill="url(#gradS)" stroke="url(#goldLine)" stroke-width="0.32">S</text>
  </g>
</svg>`;
}
