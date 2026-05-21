import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { productionFrozenConfig, verifyFrozenStrategy } from '../strategy/frozenProduction';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const check = verifyFrozenStrategy(root, productionFrozenConfig());
if (!check.ok) {
  console.error('FAIL');
  check.errors.forEach((e) => console.error(`  ${e}`));
  process.exit(1);
}
console.log('PASS — strategy frozen and signal sources unchanged');
