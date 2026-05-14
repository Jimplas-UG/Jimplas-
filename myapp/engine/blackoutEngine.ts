import type { BilshenzEngineConfig } from './types';

export function newsBlocks(cfg: BilshenzEngineConfig): boolean {
  return cfg.newsActive;
}

export function nfpBlocks(cfg: BilshenzEngineConfig): boolean {
  return cfg.nfpBlackout;
}
