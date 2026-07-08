/**
 * Production-frozen strategy — signal math and optimization parameters are locked.
 * Do not tune these values during forward demo / live validation.
 */
import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { BilshenzEngineConfig } from '../engine/types';
import { liveProfileCfg } from '../scripts/lib/runBacktestWindow';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Files whose contents define signal generation (hash-locked). */
export const FROZEN_SIGNAL_SOURCE_FILES = [
  'engine/signalEngine.ts',
  'engine/pineV5SignalEngine.ts',
  'engine/jimplasFluiditySignalEngine.ts',
  'engine/signalThrottle.ts',
  'engine/tradeBot.ts',
  'engine/bilshenzEngine.ts',
  'engine/riskEngine.ts',
  'engine/executionHardening.ts',
  'engine/srEngine.ts',
  'engine/biasEngine.ts',
  'engine/sessionEngine.ts',
  'engine/confidenceEngine.ts',
  'engine/tradeGeometry.ts',
  'engine/wickEngine.ts',
  'engine/structureEngine.ts',
] as const;

export type FrozenManifest = {
  version: 1;
  frozenAt: string;
  strategyId: 'bilshenz-futures-m30-v1';
  gitNote: string;
  config: BilshenzEngineConfig;
  tunableKeysBlocked: string[];
  fileHashes: Record<string, string>;
};

const TUNABLE_BLOCKED: (keyof BilshenzEngineConfig)[] = [
  'p1VolumeAtrMult',
  'p2WickMinRatio',
  'p2MaxBodyRatio',
  'p2MinWickPips',
  'tp1MinRewardPips',
  'tp1MaxRewardPips',
  'minConfidencePctToTrade',
  'minRewardRiskToTrade',
  'minTradeQualityP1P3',
  'minTradeQualityP2',
  'maxDailyTrades',
  'lossCooldownBars',
  'p2UseStrictFilters',
  'enableP1',
  'enableP2',
  'enableP3',
  'usePineV5',
  'pivotLeft',
  'pivotRight',
  'leftScanBars',
  'leftScanMaxChop',
];

/** Locked production config (live profile + execution hardening as of freeze). */
export function productionFrozenConfig(): BilshenzEngineConfig {
  return liveProfileCfg({
    enableExecutionHardening: true,
    spreadBaselinePips: 3.08,
    spreadAdaptiveMaxMult: 1.65,
    hostileSpreadMult: 2.35,
    hostileAtrPips: 100,
    volChopMaxAtrPips: 48,
    volTrendMinAtrPips: 45,
    volSlScaleHigh: 1.12,
    minTradeQualityP1P3: 34,
    minTradeQualityP2: 36,
    p2BlockInChopRegime: false,
    p2BlockInHighVol: false,
    lossCooldownBars: 3,
    maxDailyLossPct: 3,
    maxDrawdownPct: 15,
    journalSizingSlPips: 20,
    maxDailyTrades: 3,
    signalOnClosedBarOnly: true,
    showHistory: false,
    showHistoryMode: false,
  });
}

function sha256File(absPath: string): string {
  const buf = fs.readFileSync(absPath);
  return crypto.createHash('sha256').update(buf).digest('hex');
}

export function computeFileHashes(rootDir: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const rel of FROZEN_SIGNAL_SOURCE_FILES) {
    const abs = path.join(rootDir, rel);
    if (!fs.existsSync(abs)) throw new Error(`Frozen signal file missing: ${rel}`);
    out[rel] = sha256File(abs);
  }
  return out;
}

export function buildFrozenManifest(rootDir: string): FrozenManifest {
  return {
    version: 1,
    frozenAt: new Date().toISOString(),
    strategyId: 'bilshenz-futures-m30-v1',
    gitNote: 'Lock signal sources + productionFrozenConfig; zero tuning during forward demo',
    config: productionFrozenConfig(),
    tunableKeysBlocked: [...TUNABLE_BLOCKED],
    fileHashes: computeFileHashes(rootDir),
  };
}

export function manifestPath(): string {
  return path.join(__dirname, 'frozen-manifest.json');
}

export function loadFrozenManifest(): FrozenManifest | null {
  const p = manifestPath();
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, 'utf8')) as FrozenManifest;
}

export function saveFrozenManifest(m: FrozenManifest): void {
  fs.writeFileSync(manifestPath(), JSON.stringify(m, null, 2), 'utf8');
}

export type FreezeCheckResult = { ok: true } | { ok: false; errors: string[] };

/** Verify on-disk signal files match manifest and runtime cfg matches frozen config. */
export function verifyFrozenStrategy(
  rootDir: string,
  runtimeCfg?: BilshenzEngineConfig
): FreezeCheckResult {
  const errors: string[] = [];
  const manifest = loadFrozenManifest();
  if (!manifest) {
    errors.push('frozen-manifest.json missing — run: npm run strategy:freeze');
    return { ok: false, errors };
  }

  const currentHashes = computeFileHashes(rootDir);
  for (const [rel, expected] of Object.entries(manifest.fileHashes)) {
    if (currentHashes[rel] !== expected) {
      errors.push(`Signal source changed: ${rel}`);
    }
  }

  if (runtimeCfg) {
    const frozen = productionFrozenConfig();
    for (const key of TUNABLE_BLOCKED) {
      const a = frozen[key];
      const b = runtimeCfg[key];
      if (JSON.stringify(a) !== JSON.stringify(b)) {
        errors.push(`Config drift on locked key "${key}": ${JSON.stringify(b)} !== ${JSON.stringify(a)}`);
      }
    }
  }

  return errors.length ? { ok: false, errors } : { ok: true };
}

export function isStrategyFreezeEnforced(): boolean {
  return process.env.STRATEGY_FREEZE === '1' || process.env.STRATEGY_FREEZE === 'true';
}

/** Runtime cfg for desk-api / forward demo — only live quote spread may differ. */
export function mergeFrozenDeskCfg(liveSpreadPips?: number): BilshenzEngineConfig {
  const cfg = productionFrozenConfig();
  if (liveSpreadPips != null && liveSpreadPips > 0) {
    return { ...cfg, currentSpreadPips: liveSpreadPips };
  }
  return cfg;
}
