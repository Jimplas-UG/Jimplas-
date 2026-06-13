import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { getMockApiLog, clearMockApiLog } from '../mocks/mockApi';
import { isDevPreview, useMockApi } from '../lib/devPreview';

const DevPreviewContext = createContext(null);

export function DevPreviewProvider({ children }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);
  const [apiLogTick, setApiLogTick] = useState(0);

  const refreshLog = useCallback(() => setApiLogTick((n) => n + 1), []);

  const value = useMemo(
    () => ({
      enabled: isDevPreview(),
      mockApi: useMockApi(),
      menuOpen,
      setMenuOpen,
      debugOpen,
      setDebugOpen,
      apiLog: getMockApiLog(),
      refreshLog,
      clearLog: () => {
        clearMockApiLog();
        refreshLog();
      },
      apiLogTick,
    }),
    [menuOpen, debugOpen, apiLogTick, refreshLog],
  );

  if (!isDevPreview()) {
    return children;
  }

  return <DevPreviewContext.Provider value={value}>{children}</DevPreviewContext.Provider>;
}

export function useDevPreview() {
  const ctx = useContext(DevPreviewContext);
  return (
    ctx ?? {
      enabled: false,
      mockApi: false,
      menuOpen: false,
      setMenuOpen: () => {},
      debugOpen: false,
      setDebugOpen: () => {},
      apiLog: [],
      refreshLog: () => {},
      clearLog: () => {},
    }
  );
}
