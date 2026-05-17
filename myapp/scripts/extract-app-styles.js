const fs = require('fs');
const path = require('path');

const appPath = path.join(__dirname, '..', 'App.js');
const outPath = path.join(__dirname, '..', 'theme', 'createAppStyles.js');
const lines = fs.readFileSync(appPath, 'utf8').split(/\r?\n/);
const start = lines.findIndex((l) => l.startsWith('const styles = StyleSheet.create'));
if (start < 0) throw new Error('styles block not found');

let endIdx = -1;
for (let i = start + 1; i < lines.length; i++) {
  if (lines[i].trim() === '});' && lines[i + 1]?.trim() === '') {
    endIdx = i;
    break;
  }
}
if (endIdx < 0) {
  for (let i = lines.length - 1; i > start; i--) {
    if (lines[i].trim() === '});') {
      endIdx = i;
      break;
    }
  }
}
if (endIdx < 0) throw new Error('end of styles block not found');

const block = lines.slice(start + 1, endIdx);
const header = `import { Platform, StyleSheet } from 'react-native';

export function createAppStyles(C) {
  return StyleSheet.create({
`;
const footer = `  });
}
`;
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, header + block.join('\n') + '\n' + footer);
console.log('Wrote', outPath, 'lines:', block.length, 'start', start, 'end', endIdx);
