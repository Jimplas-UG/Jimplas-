/**
 * Lock strategy: write frozen-manifest.json with config + signal-file SHA-256 hashes.
 * Usage: npm run strategy:freeze
 */
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { buildFrozenManifest, saveFrozenManifest } from '../strategy/frozenProduction';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifest = buildFrozenManifest(root);
saveFrozenManifest(manifest);
console.log(`Frozen manifest written (${Object.keys(manifest.fileHashes).length} signal files)`);
console.log(`Strategy: ${manifest.strategyId} @ ${manifest.frozenAt}`);
