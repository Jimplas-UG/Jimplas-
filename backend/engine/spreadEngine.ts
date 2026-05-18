import type { BilshenzEngineConfig } from './types';

export function spreadBlocked(cfg: BilshenzEngineConfig): boolean {
  return cfg.currentSpreadPips > cfg.maxSpreadPips;
}
