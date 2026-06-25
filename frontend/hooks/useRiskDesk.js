import { useCallback, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { RISK_DESK_DEFAULTS, STORAGE_RISK_DESK, normalizeRiskDeskConfig } from '../lib/riskDeskDefaults';
import {
  computeRiskDeskMetrics,
  evaluateRiskDeskGate,
  sizingEquityFromRiskDesk,
} from '../lib/riskDeskModel';
import { resolveAccountEquity } from '../utils/riskSizing';
import { SIM_DESK_EQUITY } from '../security/deskConstants';

export function useRiskDesk({
  brokerAccount,
  brokerPositions,
  brokerDeals,
  markPrice,
  simEquity = SIM_DESK_EQUITY,
}) {
  const [config, setConfig] = useState(RISK_DESK_DEFAULTS);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_RISK_DESK);
        if (!cancelled && raw) {
          setConfig(normalizeRiskDeskConfig(JSON.parse(raw)));
        }
      } catch {
        /* defaults */
      } finally {
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const persist = useCallback((next) => {
    const normalized = normalizeRiskDeskConfig(next);
    setConfig(normalized);
    AsyncStorage.setItem(STORAGE_RISK_DESK, JSON.stringify(normalized)).catch(() => {});
    return normalized;
  }, []);

  const updateConfig = useCallback(
    (patch) => {
      setConfig((prev) => {
        const next = normalizeRiskDeskConfig({ ...prev, ...patch });
        AsyncStorage.setItem(STORAGE_RISK_DESK, JSON.stringify(next)).catch(() => {});
        return next;
      });
    },
    [],
  );

  const resetConfig = useCallback(() => {
    persist(RISK_DESK_DEFAULTS);
  }, [persist]);

  const totalBalance = useMemo(() => {
    return resolveAccountEquity(brokerAccount, simEquity);
  }, [brokerAccount, simEquity]);

  const metrics = useMemo(() => {
    const peak = (() => {
      const eq = Number(brokerAccount?.equity) || totalBalance;
      const stored = config.peakEquity;
      return Math.max(stored ?? eq, eq);
    })();
    return computeRiskDeskMetrics({
      config,
      totalBalance,
      brokerAccount,
      positions: brokerPositions,
      brokerDeals,
      markPrice,
      peakEquity: peak,
    });
  }, [config, totalBalance, brokerAccount, brokerPositions, brokerDeals, markPrice]);

  useEffect(() => {
    if (!hydrated) return;
    const eq = Number(brokerAccount?.equity) || totalBalance;
    if (eq > (config.peakEquity ?? 0)) {
      updateConfig({ peakEquity: eq });
    }
  }, [hydrated, brokerAccount?.equity, totalBalance, config.peakEquity, updateConfig]);

  const checkExecution = useCallback(
    (positions = brokerPositions) => evaluateRiskDeskGate(config, metrics, positions),
    [config, metrics, brokerPositions],
  );

  const sizingEquity = useMemo(() => sizingEquityFromRiskDesk(metrics), [metrics]);
  const sizingRiskPct = config.riskPerTradePct;

  const recordApiError = useCallback(() => {
    updateConfig({ apiErrorStreak: (config.apiErrorStreak ?? 0) + 1 });
  }, [config.apiErrorStreak, updateConfig]);

  const clearApiErrors = useCallback(() => {
    if (config.apiErrorStreak) updateConfig({ apiErrorStreak: 0 });
  }, [config.apiErrorStreak, updateConfig]);

  const triggerEmergencyStop = useCallback(() => {
    updateConfig({ emergencyStop: true, pauseNewTrades: true });
  }, [updateConfig]);

  const resumeTrading = useCallback(() => {
    updateConfig({ emergencyStop: false, pauseNewTrades: false, apiErrorStreak: 0 });
  }, [updateConfig]);

  return {
    config,
    metrics,
    hydrated,
    updateConfig,
    resetConfig,
    checkExecution,
    sizingEquity,
    sizingRiskPct,
    recordApiError,
    clearApiErrors,
    triggerEmergencyStop,
    resumeTrading,
  };
}
