import React, { createContext, useContext, useMemo } from 'react';
import { createAppStyles } from '../theme/createAppStyles';
import { darkPalette } from '../theme/palettes';

const defaultStyles = createAppStyles(darkPalette);

const ThemeContext = createContext({
  isDark: true,
  colors: darkPalette,
  styles: defaultStyles,
});

/** Black / gold terminal theme only (always dark). */
export function ThemeProvider({ children }) {
  const styles = useMemo(() => createAppStyles(darkPalette), []);
  const value = useMemo(
    () => ({ isDark: true, colors: darkPalette, styles }),
    [styles]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useBilshenzTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useBilshenzTheme must be used within ThemeProvider');
  return ctx;
}
