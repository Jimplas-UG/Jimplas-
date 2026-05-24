/** Shared Bilshenz hex logo geometry (viewBox 0 0 80 80). */
export const VB = 80;
export const CX = 40;
export const CY = 40;

export const MAIN_HEX = '40,10 64,23.5 64,56.5 40,70 16,56.5 16,23.5';
export const INNER_HEX = '40,18 58,28.5 58,51.5 40,62 22,51.5 22,28.5';

export const DIAMONDS = [
  '40,12.5 41.2,13.7 40,14.9 38.8,13.7',
  '40,65.1 41.2,66.3 40,67.5 38.8,66.3',
  '12.5,40 13.7,41.2 14.9,40 13.7,38.8',
  '65.1,40 66.3,41.2 67.5,40 66.3,38.8',
  '20.5,20.5 21.7,21.7 20.5,22.9 19.3,21.7',
  '59.5,59.5 60.7,60.7 59.5,61.9 58.3,60.7',
];

/** Assembly anchor points for neon connector lines (viewBox coords). */
export const FRAGMENT_ANCHORS = {
  mainHex: { x: 40, y: 40 },
  innerHex: { x: 40, y: 40 },
  diamonds: { x: 40, y: 40 },
  outerRing: { x: 40, y: 40 },
  innerRing: { x: 40, y: 40 },
  radar: { x: 40, y: 25 },
  center: { x: 40, y: 40 },
  letterB: { x: 30, y: 42 },
  letterS: { x: 44, y: 42 },
};

/** Logo layout presets — icon variants fit Android adaptive safe zone (~66%). */
export const LOGO_LAYOUTS = {
  icon: { scale: 0.62, ox: CX, oy: CY + 3.5 },
  adaptiveIcon: { scale: 0.58, ox: CX, oy: CY + 4 },
  splash: { scale: 0.76, ox: CX, oy: CY + 0.65 },
  default: { scale: 0.88, ox: CX, oy: CY },
};

export function logoTransform(variant = 'default') {
  const layout = LOGO_LAYOUTS[variant] ?? LOGO_LAYOUTS.default;
  return `translate(${layout.ox}, ${layout.oy}) scale(${layout.scale}) translate(-${CX}, -${CY})`;
}
