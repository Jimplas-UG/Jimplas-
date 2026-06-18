/** Institutional design tokens — spacing, typography, elevation. */
import { darkPalette } from './palettes';

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
};

export const typography = {
  micro: { fontSize: 9, letterSpacing: 0.8, fontWeight: '600' },
  caption: { fontSize: 11, letterSpacing: 0.4, fontWeight: '500' },
  body: { fontSize: 13, letterSpacing: 0.2, fontWeight: '400' },
  label: { fontSize: 10, letterSpacing: 1.2, fontWeight: '700', textTransform: 'uppercase' },
  title: { fontSize: 16, letterSpacing: 0.6, fontWeight: '700' },
  display: { fontSize: 22, letterSpacing: 0.4, fontWeight: '700' },
};

export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
  xl: 18,
  pill: 999,
};

export const elevation = {
  panel: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 4,
  },
  card: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 12,
    elevation: 6,
  },
};

export const motion = {
  fast: 120,
  normal: 220,
  slow: 380,
};

export function tokens(colors = darkPalette) {
  return { colors, spacing, typography, radius, elevation, motion };
}
