const fs = require('fs');
const path = require('path');

const appPath = path.join(__dirname, '..', 'App.js');
let src = fs.readFileSync(appPath, 'utf8');

// Remove old C constant block
src = src.replace(
  /const C = \{[\s\S]*?\};\n\nconst BilshenzEngineCtx/,
  'const BilshenzEngineCtx'
);

// buildGmAlertRows signature
src = src.replace(
  'function buildGmAlertRows(r, nfpBlackout, newsActive) {',
  'function buildGmAlertRows(r, nfpBlackout, newsActive, C) {'
);

const componentsNeedingHook = [
  'Row',
  'BlinkDot',
  'SessionBlock',
  'LeftColumn',
  'Panel',
  'TfRow',
  'DxyRow',
  'ScannerRows',
  'VerdictBar',
  'ScannerTabPanels',
  'CenterColumn',
  'FilterCell',
  'EeCell',
  'RrCell',
  'HistHeader',
  'HistRow',
  'RightColumn',
  'PmCell',
  'NewsRow',
  'ProfileTab',
  'GodmodeHome',
  'MobileCompactStrip',
  'MobileBottomNav',
  'AppContent',
];

for (const name of componentsNeedingHook) {
  const re = new RegExp(`(function ${name}\\([^)]*\\) \\{)\\n`);
  if (!re.test(src)) {
    console.warn('skip', name);
    continue;
  }
  src = src.replace(re, `$1\n  const { colors: C, styles, isDark, setIsDark, toggleDark } = useBilshenzTheme();\n`);
}

// Remove styles block and DR before it (keep DR only in createAppStyles)
src = src.replace(/\n\/\*\* Corner radii[\s\S]*?^const styles = StyleSheet\.create\(\{[\s\S]*?\n\}\);\n/m, '\n');

// Add imports after BinanceBridgeContext import if missing
if (!src.includes('useBilshenzTheme')) {
  src = src.replace(
    "import { BinanceBridgeProvider, useBinanceBridge } from './contexts/BinanceBridgeContext';",
    "import { BinanceBridgeProvider, useBinanceBridge } from './contexts/BinanceBridgeContext';\nimport { ThemeProvider, useBilshenzTheme } from './contexts/ThemeContext';"
  );
}

// ProfileTab dark switch
src = src.replace(
  `<Text style={styles.psToggleHint}>Always on</Text>\n          </View>\n          <Switch value={true} disabled trackColor={{ false: C.border, true: 'rgba(212,180,90,0.35)' }} thumbColor={C.goldL} />`,
  `<Text style={styles.psToggleHint}>{isDark ? 'Black / gold' : 'Ivory / gold'}</Text>\n          </View>\n          <Switch\n            value={isDark}\n            onValueChange={setIsDark}\n            trackColor={{ false: C.border, true: 'rgba(212,180,90,0.35)' }}\n            thumbColor={C.goldL}\n          />`
);

// App export wrap ThemeProvider
src = src.replace(
  '<BinanceBridgeProvider>\n        <AppRoot />',
  '<ThemeProvider>\n      <BinanceBridgeProvider>\n        <AppRoot />\n      </BinanceBridgeProvider>\n    </ThemeProvider>'
);
if (src.includes('</BinanceBridgeProvider>\n    </SafeAreaProvider>')) {
  src = src.replace(
    '      </BinanceBridgeProvider>\n    </ThemeProvider>\n    </SafeAreaProvider>',
    '    </ThemeProvider>\n    </SafeAreaProvider>'
  );
}

// buildGmAlertRows call in AppContent - find tickerItems useMemo
src = src.replace(
  'buildGmAlertRows(bzSnapshot.risk, nfpBlackout, newsActive)',
  'buildGmAlertRows(bzSnapshot.risk, nfpBlackout, newsActive, C)'
);

// BlurView tint in ProfileTab - replace tint="dark" with dynamic
src = src.replace(
  /<BlurView intensity={22} tint="dark"/g,
  '<BlurView intensity={22} tint={colors.blurTint}'
);
src = src.replace(
  /<BlurView intensity={28} tint="dark"/g,
  '<BlurView intensity={28} tint={colors.blurTint}'
);

// ProfileTab needs colors in destructure - already has C from colors alias
// Fix BlurView to use colors.blurTint - ProfileTab has colors: C so use C.blurTint
src = src.replace(/tint={colors\.blurTint}/g, 'tint={C.blurTint}');

fs.writeFileSync(appPath, src);
console.log('patched App.js');
